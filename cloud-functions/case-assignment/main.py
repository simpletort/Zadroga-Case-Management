"""
SimpleTort — Case Assignment Cloud Function (Gen 2)

Trigger: Firestore Eventarc — google.cloud.firestore.document.v1.written
         on: projects/{PROJECT_ID}/databases/(default)/documents/cases/{caseId}

Flow:
  1. Extract caseId from the document resource name
  2. Check if status changed TO "Pending Paralegal Review" (idempotency guard)
  3. Skip if assignment.assignedParalegal already set
  4. Call assigner.assign_case() → picks paralegal via round-robin or load-balancing
  5a. Success  → publishes Pub/Sub assignment notification
  5b. No paralegal available → writes timeline event flagging manual assignment required

Environment variables (set via --set-env-vars in cloudbuild.yaml):
  GCP_PROJECT_ID              — GCP project
  PUBSUB_TOPIC_ASSIGNMENT     — default: assignment-notifications
  FIRESTORE_DATABASE_ID       — default: (default)
"""

import logging
import os
import sys
from datetime import datetime, timezone

import functions_framework
from cloudevents.http import CloudEvent
from google.cloud import firestore

from assigner import assign_case
from notifier import publish_assignment_notification

logging.basicConfig(
    stream=sys.stdout,
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)

# ── Configuration ──────────────────────────────────────────────────────────
PROJECT_ID   = os.environ["GCP_PROJECT_ID"]
PUBSUB_TOPIC = os.environ.get("PUBSUB_TOPIC_ASSIGNMENT", "assignment-notifications")
FIRESTORE_DB = os.environ.get("FIRESTORE_DATABASE_ID", "(default)")

TARGET_STATUS = "Pending Paralegal Review"

_db: firestore.Client | None = None


def _get_db() -> firestore.Client:
    global _db
    if _db is None:
        _db = firestore.Client(project=PROJECT_ID, database=FIRESTORE_DB)
    return _db


# ── Entry point ────────────────────────────────────────────────────────────

@functions_framework.cloud_event
def case_assignment(event: CloudEvent) -> None:
    """
    Triggered by a Firestore document write event via Eventarc.
    event.data contains 'value', 'oldValue', and 'updateMask' in Firestore proto format.
    """
    # Eventarc may deliver the CloudEvent payload as raw bytes or a JSON string
    # rather than a pre-parsed dict depending on the SDK version and trigger type.
    # Decode to dict before processing.
    data = event.data
    if isinstance(data, (bytes, str)):
        import json
        data = json.loads(data)
    data = data or {}

    # ── Extract case_id from the document resource name ───────────────────
    # Format: projects/{project}/databases/{db}/documents/cases/{caseId}
    doc_name: str = (data.get("value") or {}).get("name", "")
    if not doc_name:
        # On document delete, value is absent — nothing to assign
        logger.info("No document value in event; skipping")
        return

    case_id = doc_name.rsplit("/", 1)[-1]
    logger.info("case_assignment triggered for caseId=%s", case_id)

    # ── Read new and old status from Firestore proto ───────────────────────
    new_fields = (data.get("value") or {}).get("fields", {})
    old_fields = (data.get("oldValue") or {}).get("fields", {})

    new_status = _str_field(new_fields, "status")
    old_status = _str_field(old_fields, "status")

    # ── Idempotency guards ─────────────────────────────────────────────────
    if new_status != TARGET_STATUS:
        logger.info(
            "Status is '%s', not '%s'; skipping caseId=%s",
            new_status, TARGET_STATUS, case_id,
        )
        return

    if old_status == TARGET_STATUS:
        logger.info(
            "Status unchanged at '%s'; skipping caseId=%s (already processed)",
            TARGET_STATUS, case_id,
        )
        return

    # Skip if already assigned (e.g. re-triggered after manual override)
    assignment_map = new_fields.get("assignment", {}).get("mapValue", {}).get("fields", {})
    existing_paralegal = _str_field(assignment_map, "assignedParalegal")
    if existing_paralegal:
        logger.info(
            "caseId=%s already assigned to %s; skipping auto-assignment",
            case_id, existing_paralegal,
        )
        return

    # ── Run assignment ─────────────────────────────────────────────────────
    db = _get_db()
    paralegal_id = assign_case(db, case_id)

    if paralegal_id is None:
        logger.warning(
            "No available paralegal for caseId=%s — writing manual-assignment-required timeline event",
            case_id,
        )
        _write_no_paralegal_timeline(db, case_id)
        return

    # ── Publish notification ───────────────────────────────────────────────
    publish_assignment_notification(
        project_id=PROJECT_ID,
        topic_name=PUBSUB_TOPIC,
        case_id=case_id,
        paralegal_id=paralegal_id,
        assigned_at=datetime.now(tz=timezone.utc),
    )

    logger.info(
        "Auto-assignment complete: caseId=%s paralegalId=%s",
        case_id, paralegal_id,
    )


# ── Helpers ────────────────────────────────────────────────────────────────

def _str_field(fields: dict, key: str) -> str:
    """Extract a string value from a Firestore proto fields map."""
    return fields.get(key, {}).get("stringValue", "")


def _write_no_paralegal_timeline(db: firestore.Client, case_id: str) -> None:
    """Append a timeline event indicating no paralegal was available."""
    try:
        db.collection("cases").document(case_id).collection("timeline").add({
            "caseId": case_id,
            "timestamp": firestore.SERVER_TIMESTAMP,
            "eventType": "Assignment",
            "description": "Auto-assignment skipped — no available paralegal. Manual assignment required.",
            "performedBy": "system",
            "metadata": {"reason": "no_available_paralegal"},
        })
    except Exception as exc:
        logger.error("Failed to write no-paralegal timeline event for caseId=%s: %s", case_id, exc)
