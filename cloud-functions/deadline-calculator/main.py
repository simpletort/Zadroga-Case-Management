"""
Enrollment Workflow — Deadline Calculator Cloud Function (Gen 2)

Trigger: Firestore Eventarc — google.cloud.firestore.document.v1.written
         on: projects/{PROJECT_ID}/databases/{db}/documents/cases/{caseId}

Calculates the program registration filing deadline whenever:
  1. A case is created WITH a certificationDate
  2. The medicalInfo.certificationDate field changes
  3. The enrollment.certificationStatus changes to 'Enrolled'

Rule: Filing Deadline = Date of Condition Certification + N years (default: 2)

Generic field names used (not program-specific):
  enrollment.certificationStatus   — replaces enrollment.wtcEnrollmentStatus
  enrollment.filingDeadline        — replaces enrollment.vcfFilingDeadline
  enrollment.deadlineStatus        — unchanged
  enrollment.daysUntilDeadline     — unchanged
  enrollment.deadlineCalculatedAt  — unchanged

Edge cases handled:
  - No certification date: skip (deadline set later when cert date arrives)
  - Invalid date format: log warning, skip
  - Deadline already in the past: set status = 'expired', write timeline warning
  - Case is Closed/Settled/Rejected: skip recalculation

Environment variables:
  GCP_PROJECT_ID          — GCP project
  FIRESTORE_DATABASE_ID   — Firestore database (default: (default))
  PUBSUB_TOPIC_ENROLLMENT — Pub/Sub topic for enrollment events
  DEADLINE_YEARS          — years to add to certificationDate (default: 2)
"""

import json
import logging
import os
import sys
from datetime import date, datetime, timezone

import functions_framework
from cloudevents.http import CloudEvent
from dateutil.relativedelta import relativedelta
from google.cloud import firestore, pubsub_v1

logging.basicConfig(
    stream=sys.stdout,
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)

PROJECT_ID = os.environ["GCP_PROJECT_ID"]
FIRESTORE_DB = os.environ.get("FIRESTORE_DATABASE_ID", "simpletort-dev")
PUBSUB_TOPIC = os.environ.get("PUBSUB_TOPIC_ENROLLMENT", "enrollment-status-changes")
DEADLINE_YEARS = int(os.environ.get("DEADLINE_YEARS", "2"))

SKIP_STATUSES = {"Closed", "Settled", "Does Not Qualify", "Rejected"}

_db: firestore.Client | None = None
_publisher: pubsub_v1.PublisherClient | None = None


def _get_db() -> firestore.Client:
    global _db
    if _db is None:
        _db = firestore.Client(project=PROJECT_ID, database=FIRESTORE_DB)
    return _db


def _get_publisher() -> pubsub_v1.PublisherClient:
    global _publisher
    if _publisher is None:
        _publisher = pubsub_v1.PublisherClient()
    return _publisher


@functions_framework.cloud_event
def calculate_filing_deadline(event: CloudEvent) -> None:
    """
    Triggered by Firestore document write on cases/{caseId}.
    Calculates and stores the program filing deadline when certificationDate is present.
    """
    data = event.data or {}

    doc_name: str = (data.get("value") or {}).get("name", "")
    if not doc_name:
        logger.info("No document value in event; skipping (delete event)")
        return

    case_id = doc_name.rsplit("/", 1)[-1]
    logger.info("calculate_filing_deadline triggered caseId=%s", case_id)

    new_fields = (data.get("value") or {}).get("fields", {})
    old_fields = (data.get("oldValue") or {}).get("fields", {})

    # ── Check if we should process this event ────────────────────────────
    case_status = _str_field(new_fields, "status")
    if case_status in SKIP_STATUSES:
        logger.info("Skipping closed/final case caseId=%s status=%s", case_id, case_status)
        return

    # ── Check triggering conditions ───────────────────────────────────────
    # Get certificationDate from medicalInfo map
    new_medical = _map_field(new_fields, "medicalInfo")
    old_medical = _map_field(old_fields, "medicalInfo")
    new_cert = _str_field(new_medical, "certificationDate")
    old_cert = _str_field(old_medical, "certificationDate")

    # Get certification status from enrollment map (generic field name)
    new_enrollment = _map_field(new_fields, "enrollment")
    old_enrollment = _map_field(old_fields, "enrollment")
    new_cert_status = _str_field(new_enrollment, "certificationStatus")
    old_cert_status = _str_field(old_enrollment, "certificationStatus")

    # Determine if we need to (re)calculate
    cert_date_changed = new_cert != old_cert and new_cert
    just_enrolled = new_cert_status == "Enrolled" and old_cert_status != "Enrolled"
    is_new_doc = not old_fields   # creation event

    if not (cert_date_changed or just_enrolled or (is_new_doc and new_cert)):
        logger.info(
            "No relevant change for deadline calc caseId=%s; skipping", case_id
        )
        return

    # ── Get certification date ─────────────────────────────────────────────
    if not new_cert:
        logger.info(
            "No certificationDate for caseId=%s; deadline will be set when cert date arrives",
            case_id,
        )
        return

    try:
        cert_date = date.fromisoformat(new_cert[:10])
    except (ValueError, TypeError) as exc:
        logger.warning(
            "Invalid certificationDate='%s' for caseId=%s: %s", new_cert, case_id, exc
        )
        return

    # ── Calculate deadline ─────────────────────────────────────────────────
    deadline = cert_date + relativedelta(years=DEADLINE_YEARS)
    today = date.today()
    days_remaining = (deadline - today).days

    # Determine deadline status bucket
    if days_remaining < 0:
        deadline_status = "expired"
    elif days_remaining <= 30:
        deadline_status = "warning_30"
    elif days_remaining <= 60:
        deadline_status = "warning_60"
    elif days_remaining <= 90:
        deadline_status = "warning_90"
    else:
        deadline_status = "active"

    logger.info(
        "filing_deadline_calculated caseId=%s certDate=%s deadline=%s daysRemaining=%d status=%s",
        case_id, cert_date.isoformat(), deadline.isoformat(), days_remaining, deadline_status,
    )

    # ── Persist deadline to case document (generic field name) ────────────
    db = _get_db()
    case_ref = db.collection("cases").document(case_id)

    try:
        case_ref.update({
            "enrollment.filingDeadline": deadline.isoformat(),   # generic (was vcfFilingDeadline)
            "enrollment.deadlineStatus": deadline_status,
            "enrollment.daysUntilDeadline": days_remaining,
            "enrollment.deadlineCalculatedAt": firestore.SERVER_TIMESTAMP,
        })
    except Exception as exc:
        logger.error("Failed to update deadline for caseId=%s: %s", case_id, exc)
        return

    # ── Write timeline event ───────────────────────────────────────────────
    try:
        timeline_ref = case_ref.collection("timeline").document()
        description = (
            f"Filing deadline calculated: {deadline.isoformat()} ({days_remaining} days remaining)"
            if days_remaining >= 0
            else (
                f"Filing deadline EXPIRED: {deadline.isoformat()} "
                f"({abs(days_remaining)} days ago)"
            )
        )
        timeline_ref.set({
            "eventId": timeline_ref.id,
            "caseId": case_id,
            "timestamp": firestore.SERVER_TIMESTAMP,
            "eventType": "DeadlineCalculated",
            "description": description,
            "performedBy": "system",
            "metadata": {
                "filingDeadline": deadline.isoformat(),
                "certificationDate": cert_date.isoformat(),
                "daysRemaining": days_remaining,
                "deadlineStatus": deadline_status,
                "trigger": "certification_date_change" if cert_date_changed else "certification_enrolled",
                "deadlineYears": DEADLINE_YEARS,
            },
        })
    except Exception as exc:
        logger.warning("Failed to write timeline event for caseId=%s: %s", case_id, exc)

    # ── Publish Pub/Sub event ──────────────────────────────────────────────
    try:
        publisher = _get_publisher()
        topic_path = publisher.topic_path(PROJECT_ID, PUBSUB_TOPIC)
        payload = json.dumps({
            "caseId": case_id,
            "eventType": "FilingDeadlineCalculated",
            "filingDeadline": deadline.isoformat(),
            "deadlineStatus": deadline_status,
            "daysRemaining": days_remaining,
            "timestamp": datetime.now(tz=timezone.utc).isoformat(),
        }).encode("utf-8")
        publisher.publish(topic_path, data=payload)
    except Exception as exc:
        logger.warning("Pub/Sub publish failed for caseId=%s: %s", case_id, exc)

    # ── Warn if expired ────────────────────────────────────────────────────
    if deadline_status == "expired":
        logger.warning(
            "EXPIRED_DEADLINE caseId=%s deadline=%s daysOverdue=%d",
            case_id, deadline.isoformat(), abs(days_remaining),
        )


# ── Firestore proto field helpers ──────────────────────────────────────────────

def _str_field(fields: dict, key: str) -> str:
    """Extract a string value from a Firestore proto fields map."""
    val = fields.get(key, {})
    return val.get("stringValue") or val.get("timestampValue", "")


def _map_field(fields: dict, key: str) -> dict:
    """Extract a nested map from a Firestore proto fields map."""
    return fields.get(key, {}).get("mapValue", {}).get("fields", {})
