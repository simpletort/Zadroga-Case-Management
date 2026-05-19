"""
Attorney Review Service

Review Queue:
  - Returns cases in "Pending Attorney Review" scoped to the requesting attorney
    (junior_partner sees only their assigned cases; senior_partner/system_admin see all)
  - Sorted by: VCF deadline proximity → submission date → qualification score

Approve for Filing (atomic batch per case):
  1. Verify case is "Pending Attorney Review"
  2. Verify actor is the assigned attorney OR has senior_partner+ level
  3. Set case status → "Approved for Filing"
  4. Record approvedForFilingAt, approvedForFilingBy, approvalNotes
  5. Create 3 filing-prep tasks in cases/{caseId}/tasks/
  6. Create paralegal notification in notifications/
  7. Append timeline event (audit trail)

Bulk approval processes cases sequentially; errors are captured per case (never raises).
"""

import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException, status
from google.cloud import firestore

from app.utils.roles import normalize_role
from app.utils.decision_audit import (
    write_decision_audit_event,
    DECISION_TYPE_APPROVE_FOR_FILING,
)

logger = logging.getLogger(__name__)

REVIEW_STATUS = "Pending Attorney Review"
APPROVED_STATUS = "Approved for Filing"

# Roles that can see all attorneys' queues and approve any case
SENIOR_ROLES = {"senior_partner", "system_admin"}

# Filing-prep tasks auto-created on approval
_FILING_TASKS = [
    {
        "type":     "filing_prep",
        "title":    "Prepare VCF filing package",
        "priority": "high",
    },
    {
        "type":     "filing_prep",
        "title":    "File with VCF program",
        "priority": "high",
        # due date set to vcfRegDeadline when available
    },
    {
        "type":     "filing_prep",
        "title":    "Notify client of filing status",
        "priority": "normal",
    },
]


# ─────────────────────────────────────────────────────────────────────────────
# Review Queue
# ─────────────────────────────────────────────────────────────────────────────

def get_review_queue(
    db: firestore.Client,
    page: int,
    page_size: int,
) -> dict:
    """
    Return a paginated, prioritised attorney review queue.

    Sort order (all Python-side — avoids Firestore composite indexes):
      1. VCF deadline proximity — soonest first; cases with no deadline sort last
      2. submittedForReviewAt — oldest first (longest waiting)
      3. qual_score — highest first (strongest cases)
    """
    query = db.collection("cases").where("status", "==", REVIEW_STATUS)

    docs = list(query.stream())

    now = datetime.now(tz=timezone.utc)
    items: list[dict] = []

    for doc in docs:
        data   = doc.to_dict() or {}
        assign = data.get("assignment") or {}

        submitted_for_review = data.get("submittedForReviewAt")

        if submitted_for_review is not None and hasattr(submitted_for_review, "tzinfo") and submitted_for_review.tzinfo is None:
            submitted_for_review = submitted_for_review.replace(tzinfo=timezone.utc)

        vcf_details = data.get("vcfScreeningDetails") or {}
        score_raw   = vcf_details.get("score")
        qual_score  = float(score_raw) if score_raw is not None else None

        items.append({
            "case_id":                 doc.id,
            "first_name":              data.get("firstName", ""),
            "last_name":               data.get("lastName", ""),
            "case_type":               None,
            "vcf_deadline":            None,
            "qual_score":              qual_score,
            "submitted_for_review_at": submitted_for_review,
            "assigned_paralegal":      assign.get("assignedParalegal"),
            "assigned_paralegal_name": assign.get("assignedParalegalName"),
            "days_until_deadline":     None,
        })

    # ── Sort ──────────────────────────────────────────────────────────────────
    # 1. VCF deadline: soonest first; None deadline sorts to end (inf)
    # 2. submittedForReviewAt: oldest first (0 = never submitted, sorts last)
    # 3. qual_score: highest first (negate for ascending sort trick)
    def _sort_key(c: dict):
        dl = c["vcf_deadline"].timestamp() if c["vcf_deadline"] else float("inf")
        sub = c["submitted_for_review_at"].timestamp() if c["submitted_for_review_at"] else float("inf")
        qs = -(c["qual_score"] or 0.0)
        return (dl, sub, qs)

    items.sort(key=_sort_key)

    total       = len(items)
    overdue     = 0  # vcf_deadline not present in current schema
    total_pages = max(1, (total + page_size - 1) // page_size)
    start       = (page - 1) * page_size
    page_items  = items[start: start + page_size]

    return {
        "total_pending": total,
        "overdue_count": overdue,
        "page": {
            "items":       page_items,
            "total":       total,
            "page":        page,
            "page_size":   page_size,
            "total_pages": total_pages,
        },
    }


# ─────────────────────────────────────────────────────────────────────────────
# Approval
# ─────────────────────────────────────────────────────────────────────────────

def _approve_single(
    db: firestore.Client,
    case_id: str,
    actor_uid: str,
    actor_name: Optional[str],
    actor_role: str,
    notes: Optional[str],
    now: datetime,
) -> dict:
    """
    Atomically approve a single case for filing.
    Raises HTTPException on validation failure.
    Returns result dict on success.
    """
    case_ref  = db.collection("cases").document(case_id)
    case_snap = case_ref.get()

    if not case_snap.exists:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Case '{}' not found.".format(case_id),
        )

    case_data = case_snap.to_dict() or {}
    current_status = case_data.get("status", "")

    if current_status != REVIEW_STATUS:
        raise HTTPException(
            status_code=422,
            detail=(
                "Case '{}' cannot be approved: status is '{}', expected '{}'.".format(
                    case_id, current_status, REVIEW_STATUS
                )
            ),
        )

    # Authorisation: junior_partner must be the assigned attorney
    assigned_attorney = (case_data.get("assignment") or {}).get("assignedAttorney")
    is_senior = normalize_role(actor_role) in SENIOR_ROLES
    if not is_senior and assigned_attorney != actor_uid:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are not the assigned attorney for case '{}'.".format(case_id),
        )

    # Paralegal to notify
    assign        = case_data.get("assignment") or {}
    paralegal_uid = assign.get("assignedParalegal")
    vcf_deadline  = None  # not present in current schema

    notif_id    = str(uuid.uuid4())
    timeline_id = str(uuid.uuid4())
    task_ids: list[str] = []

    batch = db.batch()

    # ── 1. Update case ────────────────────────────────────────────────────────
    case_update: dict = {
        "status":               APPROVED_STATUS,
        "approvedForFilingAt":  now,
        "approvedForFilingBy":  actor_uid,
        "updatedAt":            now,
    }
    if notes:
        case_update["approvalNotes"] = notes
    batch.update(case_ref, case_update)

    # ── 2. Filing-prep tasks ──────────────────────────────────────────────────
    for task_template in _FILING_TASKS:
        task_id  = str(uuid.uuid4())
        task_ref = case_ref.collection("tasks").document(task_id)
        task_doc: dict = {
            "taskId":     task_id,
            "caseId":     case_id,
            "type":       task_template["type"],
            "title":      task_template["title"],
            "assignedTo": paralegal_uid,
            "status":     "open",
            "priority":   task_template["priority"],
            "createdAt":  now,
            "createdBy":  actor_uid,
        }
        # Pin the "File with VCF" task due date to the VCF registration deadline
        if task_template["title"] == "File with VCF program" and vcf_deadline is not None:
            task_doc["dueDate"] = vcf_deadline
        batch.set(task_ref, task_doc)
        task_ids.append(task_id)

    # ── 3. Paralegal notification ─────────────────────────────────────────────
    notif_ref = db.collection("notifications").document(notif_id)
    batch.set(notif_ref, {
        "notificationId": notif_id,
        "type":           "case_approved_for_filing",
        "caseId":         case_id,
        "recipientId":    paralegal_uid,
        "message":        "Case {} has been approved for filing. Please prepare the VCF filing package.".format(case_id),
        "createdAt":      now,
        "read":           False,
        "createdBy":      actor_uid,
        "createdByName":  actor_name,
    })

    # ── 4. Timeline event (audit trail) ──────────────────────────────────────
    timeline_ref = case_ref.collection("timeline").document(timeline_id)
    batch.set(timeline_ref, {
        "eventId":         timeline_id,
        "caseId":          case_id,
        "eventType":       "StatusChange",
        "description":     "Case approved for filing by {}.".format(actor_name or actor_uid),
        "performedBy":     actor_uid,
        "performedByName": actor_name,
        "timestamp":       now,
        "metadata": {
            "previousStatus": REVIEW_STATUS,
            "newStatus":      APPROVED_STATUS,
            "approvalNotes":  notes,
            "taskIds":        task_ids,
        },
    })

    # ── 5. Decision audit (immutable cross-case record) ───────────────────────
    write_decision_audit_event(
        batch=batch,
        db=db,
        event_id=timeline_id,
        case_id=case_id,
        decision_type=DECISION_TYPE_APPROVE_FOR_FILING,
        event_type="StatusChange",
        performed_by=actor_uid,
        performed_by_name=actor_name,
        performed_by_role=actor_role,
        timestamp=now,
        previous_status=REVIEW_STATUS,
        new_status=APPROVED_STATUS,
        notes=notes,
        case_submitted_for_review_at=case_data.get("submittedForReviewAt"),
    )

    batch.commit()

    logger.info(
        "Case %s approved for filing by %s; tasks=%s notif=%s",
        case_id, actor_uid, task_ids, notif_id,
    )

    return {
        "case_id":     case_id,
        "status":      APPROVED_STATUS,
        "approved_at": now,
        "approved_by": actor_uid,
        "notes":       notes,
        "task_ids":    task_ids,
    }


def approve_for_filing(
    db: firestore.Client,
    case_id: str,
    actor_uid: str,
    actor_role: str,
    notes: Optional[str],
) -> dict:
    """Single-case approval. Raises HTTPException on any failure."""
    actor_snap = db.collection("staff").document(actor_uid).get()
    actor_name = (actor_snap.to_dict() or {}).get("displayName") if actor_snap.exists else None
    now = datetime.now(tz=timezone.utc)
    return _approve_single(db, case_id, actor_uid, actor_name, actor_role, notes, now)


def bulk_approve_for_filing(
    db: firestore.Client,
    case_ids: list[str],
    actor_uid: str,
    actor_role: str,
    notes: Optional[str],
) -> dict:
    """
    Approve multiple cases. Errors are captured per-case; never raises.
    Returns a summary with per-case ApprovalResult dicts.
    """
    actor_snap = db.collection("staff").document(actor_uid).get()
    actor_name = (actor_snap.to_dict() or {}).get("displayName") if actor_snap.exists else None
    now = datetime.now(tz=timezone.utc)

    results: list[dict] = []
    approved_count = 0

    for case_id in case_ids:
        try:
            result = _approve_single(db, case_id, actor_uid, actor_name, actor_role, notes, now)
            results.append({
                "case_id":     result["case_id"],
                "success":     True,
                "status":      result["status"],
                "approved_at": result["approved_at"],
                "task_ids":    result["task_ids"],
                "error":       None,
            })
            approved_count += 1
        except HTTPException as exc:
            detail = exc.detail if isinstance(exc.detail, str) else str(exc.detail)
            results.append({
                "case_id":     case_id,
                "success":     False,
                "status":      None,
                "approved_at": None,
                "task_ids":    [],
                "error":       detail,
            })
            logger.warning("Bulk approve: case %s failed — %s", case_id, detail)
        except Exception as exc:
            results.append({
                "case_id":     case_id,
                "success":     False,
                "status":      None,
                "approved_at": None,
                "task_ids":    [],
                "error":       "Unexpected error: {}".format(exc),
            })
            logger.error("Bulk approve: case %s unexpected error — %s", case_id, exc)

    return {
        "requested": len(case_ids),
        "approved":  approved_count,
        "failed":    len(case_ids) - approved_count,
        "results":   results,
    }
