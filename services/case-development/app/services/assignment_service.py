"""
Manual case assignment service.

Handles admin/senior-partner override of the auto-assignment, keeping
activeCaseCount consistent and the timeline up to date.
"""

import logging
from datetime import datetime, timezone

from fastapi import HTTPException, status
from google.cloud import firestore

from app.utils.roles import normalize_role

logger = logging.getLogger(__name__)

PARALEGAL_ROLE = "paralegal"


def get_assignment_info(db: firestore.Client, case_id: str) -> dict:
    """
    Return the assignment map from the case document plus the paralegal's
    displayName looked up from the staff collection.
    """
    case_snap = db.collection("cases").document(case_id).get()
    if not case_snap.exists:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Case '{}' not found.".format(case_id),
        )

    case_data  = case_snap.to_dict() or {}
    assignment = case_data.get("assignment") or {}
    paralegal_id = assignment.get("assignedParalegal", "")

    display_name = None
    if paralegal_id:
        staff_snap = db.collection("staff").document(paralegal_id).get()
        if staff_snap.exists:
            display_name = (staff_snap.to_dict() or {}).get("displayName")

    return {
        "assigned_paralegal":      paralegal_id or None,
        "assigned_paralegal_name": display_name,
        "assignment_date":         assignment.get("assignmentDate"),
    }


def manual_assign(
    db: firestore.Client,
    case_id: str,
    new_paralegal_id: str,
    actor_uid: str,
    reason: str | None,
) -> dict:
    """
    Atomically override the case assignment:
      - Decrement old paralegal's activeCaseCount (if previously assigned)
      - Set new assignment fields on the case
      - Increment new paralegal's activeCaseCount
      - Append a timeline event

    Returns the new assignment info dict.
    """
    # Validate new paralegal exists and has the correct role
    new_staff_snap = db.collection("staff").document(new_paralegal_id).get()
    logger.info("New staff snap: %s", new_staff_snap)
    if not new_staff_snap.exists:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Staff member '{}' not found.".format(new_paralegal_id),
        )
    new_staff_data = new_staff_snap.to_dict() or {}
    logger.info("New staff data: %s", new_staff_data)
    if normalize_role(new_staff_data.get("role", "")) != PARALEGAL_ROLE:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Staff member '{}' is not a Paralegal.".format(new_paralegal_id),
        )

    display_name = new_staff_data.get("displayName", new_paralegal_id)
    assigned_at  = datetime.now(tz=timezone.utc)

    case_ref      = db.collection("cases").document(case_id)
    new_staff_ref = db.collection("staff").document(new_paralegal_id)
    timeline_ref  = db.collection("cases").document(case_id).collection("timeline").document()
    logger.info("Case ref: %s", case_ref)
    logger.info("New staff ref: %s", new_staff_ref)
    logger.info("Timeline ref: %s", timeline_ref)

    @firestore.transactional
    def _txn(transaction: firestore.Transaction) -> str | None:
        case_snap  = case_ref.get(transaction=transaction)
        if not case_snap.exists:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Case '{}' not found.".format(case_id),
            )
        case_data       = case_snap.to_dict() or {}
        old_paralegal   = (case_data.get("assignment") or {}).get("assignedParalegal", "")

        new_staff_snap2 = new_staff_ref.get(transaction=transaction)
        new_count       = (new_staff_snap2.to_dict() or {}).get("activeCaseCount", 0) or 0

        # Decrement old paralegal's count if there was a prior assignment
        if old_paralegal and old_paralegal != new_paralegal_id:
            old_staff_ref   = db.collection("staff").document(old_paralegal)
            old_staff_snap  = old_staff_ref.get(transaction=transaction)
            old_count       = (old_staff_snap.to_dict() or {}).get("activeCaseCount", 0) or 0
            transaction.update(old_staff_ref, {
                "activeCaseCount": max(0, old_count - 1),
            })

        # Update case assignment
        transaction.update(case_ref, {
            "assignment.assignedParalegal": new_paralegal_id,
            "assignment.assignmentDate":   assigned_at,
        })

        # Increment new paralegal count (only if not self-reassignment)
        if old_paralegal != new_paralegal_id:
            transaction.update(new_staff_ref, {
                "activeCaseCount": new_count + 1,
            })

        # Append timeline event
        transaction.set(timeline_ref, {
            "eventId":     timeline_ref.id,
            "caseId":      case_id,
            "timestamp":   firestore.SERVER_TIMESTAMP,
            "eventType":   "Assignment",
            "description": "Case manually assigned to {} by staff override.".format(display_name),
            "performedBy": actor_uid,
            "metadata": {
                "assignedTo":      new_paralegal_id,
                "assignedName":    display_name,
                "overriddenFrom":  old_paralegal or None,
                "reason":          reason,
                "mode":            "manual_override",
            },
        })

        return old_paralegal or None

    transaction  = db.transaction()
    overridden_from = _txn(transaction)

    logger.info(
        "Manual assignment: caseId=%s assignedTo=%s overriddenFrom=%s actor=%s",
        case_id, new_paralegal_id, overridden_from, actor_uid,
    )

    return {
        "assigned_paralegal":      new_paralegal_id,
        "assigned_paralegal_name": display_name,
        "assignment_date":         assigned_at,
        "overridden_from":         overridden_from,
    }


def get_workload(db: firestore.Client) -> list[dict]:
    """
    Return all paralegals with their current caseload, sorted by
    activeCaseCount descending (busiest first).

    Dual-queries both "paralegal" (code format) and "Paralegal" (display format)
    to handle the mixed role values currently present in the DB.  Deduplication
    by document ID ensures no paralegal appears twice.
    """
    seen: set[str] = set()
    results: list[dict] = []

    for role_val in (PARALEGAL_ROLE, "Paralegal"):
        for doc in db.collection("staff").where("role", "==", role_val).stream():
            if doc.id in seen:
                continue
            seen.add(doc.id)
            data = doc.to_dict() or {}
            results.append({
                "user_id":           data.get("userId", doc.id),
                "display_name":      data.get("displayName", ""),
                "active_case_count": data.get("activeCaseCount") or 0,
                "max_caseload":      data.get("maxCaseload"),
                "is_active":         data.get("isActive", False),
            })

    results.sort(key=lambda x: x["active_case_count"], reverse=True)
    return results
