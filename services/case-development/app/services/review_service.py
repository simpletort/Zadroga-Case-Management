"""
Submit-for-Attorney-Review Service

Pre-flight checks:
  1. Case exists and is in a submittable status ("Pending Paralegal Review")
  2. Required document categories all have at least one clean upload
  3. Questionnaire is marked complete (cases/{caseId}.questionnaireComplete == True)
  4. AI summary has been generated (cases/{caseId}.aiSummaryGenerated == True)

On submit (atomic batch):
  - Case status → "Pending Attorney Review"
  - cases/{caseId}.submittedForReviewAt + submittedForReviewBy set
  - Timeline event appended
  - Notification document written to notifications/{notifId}
"""

import logging
import uuid
from datetime import datetime, timezone

from fastapi import HTTPException, status
from google.cloud import firestore

logger = logging.getLogger(__name__)

# Statuses from which a paralegal may submit for attorney review
SUBMITTABLE_STATUSES = {"Pending Paralegal Review"}

# New status after submission
TARGET_STATUS = "Pending Attorney Review"

# Document categories that must have at least one clean file before submission
REQUIRED_DOCUMENT_CATEGORIES = [
    "medical-records",
    "proof-of-presence",
    "id-documents",
]


def _check_case_exists(db: firestore.Client, case_id: str) -> dict:
    snap = db.collection("cases").document(case_id).get()
    if not snap.exists:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Case '{}' not found.".format(case_id),
        )
    return snap.to_dict() or {}


def run_preflight(db: firestore.Client, case_id: str) -> dict:
    """
    Run all pre-flight checks and return structured pass/fail results.
    Does NOT mutate any documents.
    """
    case_data = _check_case_exists(db, case_id)

    checks: list[dict] = []

    # ── 1. Status check ────────────────────────────────────────────────────
    current_status = case_data.get("status", "")
    status_ok = current_status in SUBMITTABLE_STATUSES
    checks.append({
        "name":   "case_status",
        "passed": status_ok,
        "detail": (
            None if status_ok
            else "Case status is '{}'. Must be one of: {}.".format(
                current_status, ", ".join(sorted(SUBMITTABLE_STATUSES))
            )
        ),
    })

    # ── 2. Required documents ──────────────────────────────────────────────
    docs_snap = (
        db.collection("cases")
        .document(case_id)
        .collection("documents")
        .stream()
    )

    uploaded_categories: set[str] = set()
    for doc in docs_snap:
        data = doc.to_dict() or {}
        if data.get("scanStatus") == "clean":
            category = data.get("category", "")
            if category:
                uploaded_categories.add(category)

    for category in REQUIRED_DOCUMENT_CATEGORIES:
        present = category in uploaded_categories
        checks.append({
            "name":   "document_{}".format(category.replace("-", "_")),
            "passed": present,
            "detail": None if present else "No clean upload found for category '{}'.".format(category),
        })

    # ── 3. Questionnaire complete ──────────────────────────────────────────
    q_complete = bool(case_data.get("questionnaireComplete", False))
    checks.append({
        "name":   "questionnaire_complete",
        "passed": q_complete,
        "detail": None if q_complete else "Questionnaire has not been marked complete.",
    })

    # ── 4. AI summary generated ────────────────────────────────────────────
    ai_done = bool(case_data.get("aiSummaryGenerated", False))
    checks.append({
        "name":   "ai_summary_generated",
        "passed": ai_done,
        "detail": None if ai_done else "AI case summary has not been generated.",
    })

    all_passed = all(c["passed"] for c in checks)
    return {"all_passed": all_passed, "checks": checks}


def submit_for_review(
    db: firestore.Client,
    case_id: str,
    actor_uid: str,
) -> dict:
    """
    Run pre-flight then, if all checks pass, atomically:
      - Update case status to TARGET_STATUS
      - Record submission metadata on the case
      - Append a timeline event
      - Write an attorney notification document

    Raises HTTP 422 if any pre-flight check fails.
    Returns submission result dict on success.
    """
    # Re-run preflight inside the call to prevent TOCTOU races
    preflight = run_preflight(db, case_id)
    if not preflight["all_passed"]:
        failed = [c["detail"] for c in preflight["checks"] if not c["passed"]]
        raise HTTPException(
            status_code=422,
            detail={
                "message": "Pre-flight checks failed. Submission blocked.",
                "failed_checks": failed,
            },
        )

    case_data = _check_case_exists(db, case_id)
    assigned_attorney = (case_data.get("assignment") or {}).get("assignedAttorney")

    # Resolve actor display name
    staff_snap = db.collection("staff").document(actor_uid).get()
    actor_name = (staff_snap.to_dict() or {}).get("displayName") if staff_snap.exists else None

    now = datetime.now(tz=timezone.utc)
    notif_id = str(uuid.uuid4())

    case_ref     = db.collection("cases").document(case_id)
    timeline_ref = case_ref.collection("timeline").document()
    notif_ref    = db.collection("notifications").document(notif_id)

    batch = db.batch()

    # Update case status + submission metadata
    batch.update(case_ref, {
        "status":                TARGET_STATUS,
        "submittedForReviewAt":  now,
        "submittedForReviewBy":  actor_uid,
        "updatedAt":             now,
    })

    # Timeline event
    batch.set(timeline_ref, {
        "eventId":          timeline_ref.id,
        "caseId":           case_id,
        "eventType":        "StatusChange",
        "description":      "Case submitted for attorney review by {}.".format(
            actor_name or actor_uid
        ),
        "performedBy":      actor_uid,
        "performedByName":  actor_name,
        "timestamp":        now,
        "metadata": {
            "previousStatus": case_data.get("status"),
            "newStatus":      TARGET_STATUS,
        },
    })

    # Attorney notification
    batch.set(notif_ref, {
        "notificationId":  notif_id,
        "type":            "review_requested",
        "caseId":          case_id,
        "recipientId":     assigned_attorney,
        "message":         "Case {} is ready for your review.".format(case_id),
        "createdAt":       now,
        "read":            False,
        "createdBy":       actor_uid,
        "createdByName":   actor_name,
    })

    batch.commit()

    logger.info(
        "Case %s submitted for attorney review by %s; attorney=%s",
        case_id, actor_uid, assigned_attorney,
    )

    return {
        "case_id":               case_id,
        "status":                TARGET_STATUS,
        "submitted_at":          now,
        "submitted_by":          actor_uid,
        "notified_attorney_id":  assigned_attorney,
    }
