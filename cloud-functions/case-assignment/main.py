"""
SimpleTort — Case Assignment Cloud Function (Gen 2)

Trigger: Firestore Eventarc — google.cloud.firestore.document.v1.written
         on: projects/{PROJECT_ID}/databases/(default)/documents/cases/{caseId}

Flow:
  1. Extract caseId from the CloudEvent subject attribute
     (Eventarc sets subject = "documents/cases/{caseId}" for Firestore events)
  2. Read current case document directly from Firestore
  3. Skip if status is not "Pending Paralegal Review"
  4. Skip if assignment.assignedParalegal is already set
  5. Call assigner.assign_case() → picks paralegal via round-robin or load-balancing
  5a. Success  → publishes Pub/Sub assignment notification
  5b. No paralegal available → writes timeline event flagging manual assignment required

Reading from Firestore (rather than parsing the binary protobuf Eventarc payload)
keeps the code simple and avoids a google-cloudevents dependency.  Double-assignment
is prevented by the atomic transaction guard inside assigner._do_assign().

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

    Reads current case state directly from Firestore — avoids parsing the
    binary protobuf payload (DocumentEventData) that Eventarc delivers.
    """
    # ── Extract case_id from the CloudEvent subject ────────────────────────
    # Eventarc Firestore events set: subject = "documents/{collection}/{docId}"
    # e.g.  "documents/cases/ZAD-2026-01-0001"
    try:
        subject: str = event["subject"] or ""
    except (KeyError, TypeError, AttributeError):
        subject = ""

    if not subject.startswith("documents/cases/"):
        logger.info("subject '%s' is not a cases document; skipping", subject)
        return

    case_id = subject.rsplit("/", 1)[-1]
    if not case_id:
        logger.info("Could not parse caseId from subject '%s'; skipping", subject)
        return

    logger.info("case_assignment triggered for caseId=%s", case_id)

    # ── Read current case state from Firestore ─────────────────────────────
    db = _get_db()
    case_snap = db.collection("cases").document(case_id).get()
    if not case_snap.exists:
        logger.info("Case document %s not found in Firestore; skipping", case_id)
        return

    case_data = case_snap.to_dict() or {}
    new_status = case_data.get("status", "")

    # ── Idempotency guards ─────────────────────────────────────────────────
    if new_status != TARGET_STATUS:
        logger.info(
            "Status is '%s', not '%s'; skipping caseId=%s",
            new_status, TARGET_STATUS, case_id,
        )
        return

    # Skip if already assigned (also re-checked atomically in _do_assign)
    existing_paralegal = (case_data.get("assignment") or {}).get("assignedParalegal", "")
    if existing_paralegal:
        logger.info(
            "caseId=%s already assigned to %s; skipping auto-assignment",
            case_id, existing_paralegal,
        )
        return

    # ── Run assignment ─────────────────────────────────────────────────────
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
