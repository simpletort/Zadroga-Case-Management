"""
Submit-for-Attorney-Review Service

Pre-flight checks:
  1. Case exists and is in a submittable status ("Pending Paralegal Review")
  2. Required document categories all have at least one clean upload
     (configurable via firmSettings/document_checklists; resolution order is
     cases/{caseId}.case_type override -> default)
  3. Questionnaire is marked complete (cases/{caseId}.questionnaireComplete == True)
  4. AI summary has been generated (cases/{caseId}.aiSummaryGenerated == True)

On submit (atomic batch):
  - Case status → "Pending Attorney Review"
  - cases/{caseId}.submittedForReviewAt + submittedForReviewBy set
  - If no attorney assigned, least-loaded junior_partner is auto-assigned on the case
  - cases/{caseId}/tasks/{taskId} created for the reviewing attorney / junior_partner
  - Timeline event appended
  - Notification document written to notifications/{notifId}
"""

import logging
import uuid
from datetime import datetime, timezone

from fastapi import HTTPException, status
from google.cloud import firestore

from app.services.document_checklist_service import get_required_document_categories
from app.services.feature_flags_service import get_feature_flags

logger = logging.getLogger(__name__)

# Statuses from which a paralegal may submit for attorney review
SUBMITTABLE_STATUSES = {"Pending Paralegal Review"}

# New status after submission
TARGET_STATUS = "Pending Attorney Review"


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

    # Required categories are configurable via firmSettings/document_checklists.
    # Resolution order: case_type override -> default.
    required_categories = get_required_document_categories(db, case_data.get("case_type"))

    for category in required_categories:
        present = category in uploaded_categories
        checks.append({
            "name":   "document_{}".format(category.replace(" ", "_")),
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
    # Gate is configurable via firmSettings/feature_flags.require_ai_summary
    # (default: True). When disabled, this check passes unconditionally.
    require_ai_summary = get_feature_flags(db)["require_ai_summary"]
    ai_done = bool(case_data.get("aiSummaryGenerated", False))
    ai_check_passed = ai_done or not require_ai_summary
    checks.append({
        "name":   "ai_summary_generated",
        "passed": ai_check_passed,
        "detail": None if ai_check_passed else "AI case summary has not been generated.",
    })

    all_passed = all(c["passed"] for c in checks)
    return {"all_passed": all_passed, "checks": checks}


def _find_least_loaded_junior_partner(db: firestore.Client) -> dict | None:
    """
    Query staff for junior_partner members, sort by activeCaseCount in Python
    (avoids a Firestore composite index on role + activeCaseCount), and return
    the staff dict of the least-loaded one.

    Checks both "junior_partner" and "Junior Partner" to handle mixed-case
    role values in the collection (mirrors assignment_service.get_workload).

    Returns None if no junior_partner records are found.
    """
    seen: set[str] = set()
    candidates: list[dict] = []

    for role_val in ("junior_partner", "Junior Partner"):
        for doc in db.collection("staff").where("role", "==", role_val).stream():
            if doc.id in seen:
                continue
            seen.add(doc.id)
            data = doc.to_dict() or {}
            candidates.append({
                "uid":             doc.id,
                "displayName":     data.get("displayName", ""),
                "activeCaseCount": data.get("activeCaseCount") or 0,
            })

    if not candidates:
        return None

    candidates.sort(key=lambda x: x["activeCaseCount"])
    return candidates[0]


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

    # ── Auto-assign least-loaded junior_partner if no attorney is set ──────
    auto_assigned_attorney_id: str | None = None
    auto_assigned_attorney_name: str | None = None
    if assigned_attorney is None:
        jp = _find_least_loaded_junior_partner(db)
        if jp is not None:
            assigned_attorney = jp["uid"]
            auto_assigned_attorney_id = jp["uid"]
            auto_assigned_attorney_name = jp["displayName"]
            logger.info(
                "Case %s: no attorney assigned — auto-assigning junior_partner %s",
                case_id, auto_assigned_attorney_id,
            )

    # Resolve actor display name
    staff_snap = db.collection("staff").document(actor_uid).get()
    actor_name = (staff_snap.to_dict() or {}).get("displayName") if staff_snap.exists else None

    now      = datetime.now(tz=timezone.utc)
    notif_id = str(uuid.uuid4())
    task_id  = str(uuid.uuid4())

    case_ref     = db.collection("cases").document(case_id)
    timeline_ref = case_ref.collection("timeline").document()
    task_ref     = case_ref.collection("tasks").document(task_id)
    notif_ref    = db.collection("notifications").document(notif_id)

    batch = db.batch()

    # ── Update case status + submission metadata ───────────────────────────
    case_update_payload: dict = {
        "status":               TARGET_STATUS,
        "submittedForReviewAt": now,
        "submittedForReviewBy": actor_uid,
        "updatedAt":            now,
    }
    if auto_assigned_attorney_id is not None:
        case_update_payload["assignment.assignedAttorney"]     = auto_assigned_attorney_id
        case_update_payload["assignment.assignedAttorneyName"] = auto_assigned_attorney_name
        case_update_payload["assignment.autoAssigned"]         = True

    batch.update(case_ref, case_update_payload)

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
            "previousStatus":       case_data.get("status"),
            "newStatus":            TARGET_STATUS,
            "autoAssignedAttorney": auto_assigned_attorney_id,
        },
    })

    # ── Attorney review task ───────────────────────────────────────────────
    batch.set(task_ref, {
        "taskId":     task_id,
        "caseId":     case_id,
        "type":       "attorney_review",
        "title":      "Review Case {} for attorney approval.".format(case_id),
        "assignedTo": assigned_attorney,
        "status":     "open",
        "priority":   "normal",
        "createdAt":  now,
        "createdBy":  actor_uid,
    })

    # ── Attorney notification ──────────────────────────────────────────────
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
        "Case %s submitted for attorney review by %s; attorney=%s auto_jp=%s task=%s",
        case_id, actor_uid, assigned_attorney, auto_assigned_attorney_id, task_id,
    )

    return {
        "case_id":                   case_id,
        "status":                    TARGET_STATUS,
        "submitted_at":              now,
        "submitted_by":              actor_uid,
        "notified_attorney_id":      assigned_attorney,
        "task_id":                   task_id,
        "auto_assigned_attorney_id": auto_assigned_attorney_id,
    }
