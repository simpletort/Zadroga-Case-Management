"""
Escalation Service

Escalate a Case (junior_partner → senior_partner review):
  1. Verify case is "Pending Attorney Review"
  2. Verify actor is the assigned attorney (junior_partner) OR senior_partner+
  3. If reason == "other", notes must not be empty (enforced in model; guard here too)
  4. Atomically:
     a. Set case status → "Pending Senior Review", write .escalation.* fields
     b. Create cases/{caseId}/escalations/{id} record (status="pending")
     c. Append cases/{caseId}/timeline/{id} event (eventType="Escalation")
     d. Write escalation_events/{id} top-level doc (metrics)
     e. Query all active senior_partner staff → create notifications/{id} per senior partner

Escalation Queue (senior_partner+):
  - Returns cases in "Pending Senior Review"
  - Sort: VCF deadline → escalated_at → qual_score (mirrors attorney review queue)

Decide Escalation (senior_partner+):
  - approve            → status "Approved for Filing" (reuses _approve_single), notifies junior_partner
  - reject             → status "Pending Attorney Review", notifies junior_partner
  - return_to_paralegal → status "Pending Paralegal Review", notifies junior_partner + paralegal
  All paths: resolve the escalation sub-doc + escalation_events doc, timeline event, notification(s).
"""

import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException, status
from google.cloud import firestore

from app.services.attorney_review_service import _approve_single, SENIOR_ROLES
from app.utils.roles import normalize_role

logger = logging.getLogger(__name__)

REVIEW_STATUS      = "Pending Attorney Review"
ESCALATED_STATUS   = "Pending Senior Review"
PARALEGAL_STATUS   = "Pending Paralegal Review"
APPROVED_STATUS    = "Approved for Filing"

REASON_LABELS = {
    "high_value_claim":           "High-Value Claim",
    "unusual_medical_condition":  "Unusual Medical Condition",
    "prior_attorney_conflict":    "Prior Attorney Conflict",
    "other":                      "Other",
}


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _get_actor_name(db: firestore.Client, actor_uid: str) -> Optional[str]:
    snap = db.collection("staff").document(actor_uid).get()
    return (snap.to_dict() or {}).get("displayName") if snap.exists else None


def _get_all_senior_partners(db: firestore.Client) -> list[dict]:
    """Return list of {uid, displayName} for all active senior_partner staff."""
    seen: set[str] = set()
    results: list[dict] = []
    for role_val in ("senior_partner", "Senior Partner"):
        for doc in (
            db.collection("staff")
            .where("role", "==", role_val)
            .where("isActive", "==", True)
            .stream()
        ):
            if doc.id in seen:
                continue
            seen.add(doc.id)
            data = doc.to_dict() or {}
            results.append({"uid": doc.id, "displayName": data.get("displayName", "")})
    return results


def _resolve_escalation_doc(
    db: firestore.Client,
    case_id: str,
) -> Optional[tuple[str, dict]]:
    """Find the most recent pending escalation sub-document for the case.
    Returns (escalation_id, escalation_data) or None."""
    snaps = list(
        db.collection("cases")
        .document(case_id)
        .collection("escalations")
        .where("status", "==", "pending")
        .order_by("escalatedAt", direction=firestore.Query.DESCENDING)
        .limit(1)
        .stream()
    )
    if not snaps:
        return None
    snap = snaps[0]
    return snap.id, snap.to_dict() or {}


# ─────────────────────────────────────────────────────────────────────────────
# Escalate Case
# ─────────────────────────────────────────────────────────────────────────────

def escalate_case(
    db: firestore.Client,
    case_id: str,
    actor_uid: str,
    actor_role: str,
    reason: str,
    notes: Optional[str],
) -> dict:
    """
    Escalate a case from "Pending Attorney Review" to "Pending Senior Review".
    Raises HTTPException on validation failure.
    """
    actor_role = normalize_role(actor_role)
    is_senior  = actor_role in SENIOR_ROLES

    case_ref  = db.collection("cases").document(case_id)
    case_snap = case_ref.get()
    if not case_snap.exists:
        raise HTTPException(status_code=404, detail="Case '{}' not found.".format(case_id))

    case_data       = case_snap.to_dict() or {}
    current_status  = case_data.get("status", "")
    assigned_attorney = (case_data.get("assignment") or {}).get("assignedAttorney")

    if current_status != REVIEW_STATUS:
        raise HTTPException(
            status_code=422,
            detail=(
                "Case '{}' cannot be escalated: status is '{}', expected '{}'.".format(
                    case_id, current_status, REVIEW_STATUS
                )
            ),
        )

    # junior_partner must be the assigned attorney to escalate
    if not is_senior and assigned_attorney != actor_uid:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are not the assigned attorney for case '{}'.".format(case_id),
        )

    # Belt-and-suspenders guard (model validator covers this too)
    if reason == "other" and not (notes or "").strip():
        raise HTTPException(
            status_code=422,
            detail="notes are required when reason is 'other'.",
        )

    actor_name     = _get_actor_name(db, actor_uid)
    senior_partners = _get_all_senior_partners(db)

    now            = datetime.now(tz=timezone.utc)
    escalation_id  = str(uuid.uuid4())
    timeline_id    = str(uuid.uuid4())
    event_id       = escalation_id  # reuse same ID for top-level metric doc

    batch = db.batch()

    # ── 1. Update case ─────────────────────────────────────────────────────
    batch.update(case_ref, {
        "status":    ESCALATED_STATUS,
        "updatedAt": now,
        "escalation.escalatedAt":        now,
        "escalation.escalatedBy":        actor_uid,
        "escalation.escalatedByName":    actor_name,
        "escalation.reason":             reason,
        "escalation.notes":              notes,
        "escalation.originalAttorneyId": actor_uid,
    })

    # ── 2. Escalation sub-document ─────────────────────────────────────────
    escalation_ref = case_ref.collection("escalations").document(escalation_id)
    batch.set(escalation_ref, {
        "escalationId":       escalation_id,
        "caseId":             case_id,
        "escalatedAt":        now,
        "escalatedBy":        actor_uid,
        "escalatedByName":    actor_name,
        "reason":             reason,
        "notes":              notes,
        "originalAttorneyId": actor_uid,
        "status":             "pending",
        "resolvedAt":         None,
        "resolvedBy":         None,
        "resolvedByName":     None,
        "decision":           None,
        "decisionNotes":      None,
    })

    # ── 3. Timeline event ──────────────────────────────────────────────────
    timeline_ref = case_ref.collection("timeline").document(timeline_id)
    batch.set(timeline_ref, {
        "eventId":         timeline_id,
        "caseId":          case_id,
        "eventType":       "Escalation",
        "description":     "Case escalated to senior review by {} — {}.".format(
            actor_name or actor_uid, REASON_LABELS.get(reason, reason)
        ),
        "performedBy":     actor_uid,
        "performedByName": actor_name,
        "timestamp":       now,
        "metadata": {
            "previousStatus": REVIEW_STATUS,
            "newStatus":      ESCALATED_STATUS,
            "reason":         reason,
            "notes":          notes,
            "escalationId":   escalation_id,
        },
    })

    # ── 4. Top-level metrics document ──────────────────────────────────────
    event_ref = db.collection("escalation_events").document(event_id)
    batch.set(event_ref, {
        "escalationId":  event_id,
        "caseId":        case_id,
        "reason":        reason,
        "escalatedAt":   now,
        "escalatedBy":   actor_uid,
        "resolvedAt":    None,
        "resolvedBy":    None,
        "decision":      None,
        "daysToResolve": None,
    })

    # ── 5. Notify all senior partners ──────────────────────────────────────
    for sp in senior_partners:
        notif_id  = str(uuid.uuid4())
        notif_ref = db.collection("notifications").document(notif_id)
        batch.set(notif_ref, {
            "notificationId": notif_id,
            "type":           "escalation_requested",
            "caseId":         case_id,
            "recipientId":    sp["uid"],
            "message":        (
                "Case {} has been escalated for senior review by {} — {}.".format(
                    case_id,
                    actor_name or actor_uid,
                    REASON_LABELS.get(reason, reason),
                )
            ),
            "createdAt":      now,
            "read":           False,
            "createdBy":      actor_uid,
            "createdByName":  actor_name,
            "metadata": {
                "reason":       reason,
                "escalationId": escalation_id,
            },
        })

    batch.commit()

    logger.info(
        "Case %s escalated by %s; reason=%s escalation_id=%s senior_partners_notified=%d",
        case_id, actor_uid, reason, escalation_id, len(senior_partners),
    )

    return {
        "case_id":        case_id,
        "status":         ESCALATED_STATUS,
        "escalated_at":   now,
        "escalation_id":  escalation_id,
        "notified_count": len(senior_partners),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Escalation Queue
# ─────────────────────────────────────────────────────────────────────────────

def get_escalation_queue(
    db: firestore.Client,
    user: dict,
    page: int,
    page_size: int,
) -> dict:
    """
    Return a paginated, prioritised escalation queue for senior partners.

    Sort order (Python-side — avoids composite indexes):
      1. VCF deadline proximity — soonest first; no deadline sorts last
      2. escalatedAt — oldest first (longest waiting)
      3. qual_score — highest first
    """
    docs = list(db.collection("cases").where("status", "==", ESCALATED_STATUS).stream())

    now   = datetime.now(tz=timezone.utc)
    items: list[dict] = []

    for doc in docs:
        data   = doc.to_dict() or {}
        lead   = data.get("leadData")    or {}
        qual   = data.get("qualification") or {}
        enroll = data.get("enrollment")  or {}
        esc    = data.get("escalation")  or {}

        vcf_deadline  = enroll.get("vcfRegDeadline")
        escalated_at  = esc.get("escalatedAt")

        if vcf_deadline is not None and hasattr(vcf_deadline, "tzinfo") and vcf_deadline.tzinfo is None:
            vcf_deadline = vcf_deadline.replace(tzinfo=timezone.utc)
        if escalated_at is not None and hasattr(escalated_at, "tzinfo") and escalated_at.tzinfo is None:
            escalated_at = escalated_at.replace(tzinfo=timezone.utc)

        days_until = None
        if vcf_deadline is not None:
            days_until = (vcf_deadline.date() - now.date()).days

        # Fetch the pending escalation sub-doc for the escalation_id
        resolved = _resolve_escalation_doc(db, doc.id)
        escalation_id = resolved[0] if resolved else esc.get("escalatedAt", "")

        items.append({
            "case_id":              doc.id,
            "first_name":           lead.get("firstName", ""),
            "last_name":            lead.get("lastName", ""),
            "case_type":            data.get("caseType"),
            "vcf_deadline":         vcf_deadline,
            "qual_score":           qual.get("medicalQualScore"),
            "days_until_deadline":  days_until,
            "escalation_id":        escalation_id if isinstance(escalation_id, str) else "",
            "escalation_reason":    esc.get("reason", ""),
            "escalated_at":         escalated_at,
            "escalated_by_name":    esc.get("escalatedByName"),
            "original_attorney_id": esc.get("originalAttorneyId"),
            "escalation_notes":     esc.get("notes"),
        })

    def _sort_key(c: dict):
        dl  = c["vcf_deadline"].timestamp() if c["vcf_deadline"] else float("inf")
        esc = c["escalated_at"].timestamp() if c["escalated_at"] else float("inf")
        qs  = -(c["qual_score"] or 0.0)
        return (dl, esc, qs)

    items.sort(key=_sort_key)

    total       = len(items)
    overdue     = sum(1 for c in items if c["days_until_deadline"] is not None and c["days_until_deadline"] < 0)
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
# Decide Escalation
# ─────────────────────────────────────────────────────────────────────────────

def decide_escalation(
    db: firestore.Client,
    case_id: str,
    actor_uid: str,
    actor_role: str,
    decision: str,
    notes: Optional[str],
) -> dict:
    """
    Senior partner resolves an escalated case.
    decision: "approve" | "reject" | "return_to_paralegal"
    Raises HTTPException on validation failure.
    """
    actor_role = normalize_role(actor_role)

    case_ref  = db.collection("cases").document(case_id)
    case_snap = case_ref.get()
    if not case_snap.exists:
        raise HTTPException(status_code=404, detail="Case '{}' not found.".format(case_id))

    case_data      = case_snap.to_dict() or {}
    current_status = case_data.get("status", "")

    if current_status != ESCALATED_STATUS:
        raise HTTPException(
            status_code=422,
            detail=(
                "Case '{}' cannot be decided: status is '{}', expected '{}'.".format(
                    case_id, current_status, ESCALATED_STATUS
                )
            ),
        )

    # Belt-and-suspenders (model validator covers this)
    if decision in ("reject", "return_to_paralegal") and not (notes or "").strip():
        raise HTTPException(
            status_code=422,
            detail="notes are required when decision is '{}' .".format(decision),
        )

    actor_name = _get_actor_name(db, actor_uid)
    now        = datetime.now(tz=timezone.utc)

    # Locate the pending escalation sub-doc
    resolved = _resolve_escalation_doc(db, case_id)
    escalation_id   = resolved[0] if resolved else None
    escalation_data = resolved[1] if resolved else {}
    original_attorney_id = escalation_data.get("originalAttorneyId") or \
                           (case_data.get("escalation") or {}).get("originalAttorneyId")
    assigned_paralegal   = (case_data.get("assignment") or {}).get("assignedParalegal")

    # ── APPROVE ───────────────────────────────────────────────────────────────
    if decision == "approve":
        # _approve_single expects "Pending Attorney Review" — temporarily satisfy
        # by temporarily patching for reuse. Instead, inline the approve logic
        # so we don't have to mutate Firestore mid-way. We call _approve_single
        # with a patched case status check override is not available, so we
        # reproduce the filing approval atomically here.
        result = _decide_approve(
            db, case_id, case_data, actor_uid, actor_name, actor_role, notes,
            escalation_id, original_attorney_id, now,
        )
        return result

    # ── REJECT / RETURN_TO_PARALEGAL ──────────────────────────────────────────
    if decision == "reject":
        new_status    = REVIEW_STATUS       # back to attorney queue
        notif_type    = "escalation_rejected"
        description   = "Escalation rejected by {} — case returned to attorney review.".format(
            actor_name or actor_uid
        )
        esc_status    = "rejected"
    else:  # return_to_paralegal
        new_status    = PARALEGAL_STATUS
        notif_type    = "escalation_returned"
        description   = "Escalation resolved by {} — case returned to paralegal.".format(
            actor_name or actor_uid
        )
        esc_status    = "returned"

    batch = db.batch()

    # Update case status
    case_update: dict = {
        "status":    new_status,
        "updatedAt": now,
        "escalation.resolvedAt": now,
        "escalation.resolvedBy": actor_uid,
        "escalation.decision":   decision,
    }
    batch.update(case_ref, case_update)

    # Resolve escalation sub-doc
    if escalation_id:
        esc_ref = case_ref.collection("escalations").document(escalation_id)
        batch.update(esc_ref, {
            "status":        esc_status,
            "resolvedAt":    now,
            "resolvedBy":    actor_uid,
            "resolvedByName": actor_name,
            "decision":      decision,
            "decisionNotes": notes,
        })
        # Update top-level metrics doc
        days_to_resolve = None
        esc_at = escalation_data.get("escalatedAt")
        if esc_at:
            if hasattr(esc_at, "tzinfo") and esc_at.tzinfo is None:
                esc_at = esc_at.replace(tzinfo=timezone.utc)
            days_to_resolve = (now - esc_at).days
        event_ref = db.collection("escalation_events").document(escalation_id)
        batch.update(event_ref, {
            "resolvedAt":    now,
            "resolvedBy":    actor_uid,
            "decision":      decision,
            "daysToResolve": days_to_resolve,
        })

    # Timeline event
    timeline_ref = case_ref.collection("timeline").document()
    batch.set(timeline_ref, {
        "eventId":         timeline_ref.id,
        "caseId":          case_id,
        "eventType":       "EscalationDecision",
        "description":     description,
        "performedBy":     actor_uid,
        "performedByName": actor_name,
        "timestamp":       now,
        "metadata": {
            "previousStatus": ESCALATED_STATUS,
            "newStatus":      new_status,
            "decision":       decision,
            "decisionNotes":  notes,
            "escalationId":   escalation_id,
        },
    })

    # Notify original junior_partner
    if original_attorney_id:
        notif_id  = str(uuid.uuid4())
        notif_ref = db.collection("notifications").document(notif_id)
        batch.set(notif_ref, {
            "notificationId": notif_id,
            "type":           notif_type,
            "caseId":         case_id,
            "recipientId":    original_attorney_id,
            "message":        (
                "Senior partner {} has {} case {}{}.".format(
                    actor_name or actor_uid,
                    "rejected the escalation for" if decision == "reject" else "returned",
                    case_id,
                    " — {}".format(notes) if notes else "",
                )
            ),
            "createdAt":  now,
            "read":       False,
            "createdBy":  actor_uid,
            "createdByName": actor_name,
        })

    # Also notify paralegal when returning to paralegal queue
    if decision == "return_to_paralegal" and assigned_paralegal:
        notif_id  = str(uuid.uuid4())
        notif_ref = db.collection("notifications").document(notif_id)
        batch.set(notif_ref, {
            "notificationId": notif_id,
            "type":           "escalation_returned",
            "caseId":         case_id,
            "recipientId":    assigned_paralegal,
            "message":        (
                "Case {} has been returned for additional paralegal work by {}{}.".format(
                    case_id,
                    actor_name or actor_uid,
                    " — {}".format(notes) if notes else "",
                )
            ),
            "createdAt":  now,
            "read":       False,
            "createdBy":  actor_uid,
            "createdByName": actor_name,
        })

    batch.commit()

    logger.info(
        "Escalation decided: case=%s decision=%s by=%s escalation_id=%s",
        case_id, decision, actor_uid, escalation_id,
    )

    return {
        "case_id":     case_id,
        "decision":    decision,
        "resolved_at": now,
        "resolved_by": actor_uid,
        "notes":       notes,
        "task_ids":    [],
        "new_status":  new_status,
    }


def _decide_approve(
    db: firestore.Client,
    case_id: str,
    case_data: dict,
    actor_uid: str,
    actor_name: Optional[str],
    actor_role: str,
    notes: Optional[str],
    escalation_id: Optional[str],
    original_attorney_id: Optional[str],
    now: datetime,
) -> dict:
    """
    Approve an escalated case for filing.
    Reproduces _approve_single logic but accepts ESCALATED_STATUS as source,
    then additionally resolves the escalation sub-doc and metrics doc, and
    notifies the original junior partner.
    """
    import uuid as _uuid
    from app.services.attorney_review_service import _FILING_TASKS

    case_ref = db.collection("cases").document(case_id)
    assign   = case_data.get("assignment") or {}
    enroll   = case_data.get("enrollment") or {}

    paralegal_uid = assign.get("assignedParalegal")
    vcf_deadline  = enroll.get("vcfRegDeadline")
    if vcf_deadline is not None and hasattr(vcf_deadline, "tzinfo") and vcf_deadline.tzinfo is None:
        vcf_deadline = vcf_deadline.replace(tzinfo=timezone.utc)

    task_ids: list[str] = []
    batch = db.batch()

    # ── Update case ──────────────────────────────────────────────────────
    case_update: dict = {
        "status":              APPROVED_STATUS,
        "approvedForFilingAt": now,
        "approvedForFilingBy": actor_uid,
        "updatedAt":           now,
        "escalation.resolvedAt": now,
        "escalation.resolvedBy": actor_uid,
        "escalation.decision":   "approve",
    }
    if notes:
        case_update["approvalNotes"] = notes
    batch.update(case_ref, case_update)

    # ── Filing-prep tasks (same as approve_for_filing) ───────────────────
    for task_template in _FILING_TASKS:
        task_id  = str(_uuid.uuid4())
        task_ref = case_ref.collection("tasks").document(task_id)
        task_doc: dict = {
            "taskId":    task_id,
            "caseId":    case_id,
            "type":      task_template["type"],
            "title":     task_template["title"],
            "assignedTo": paralegal_uid,
            "status":    "open",
            "priority":  task_template["priority"],
            "createdAt": now,
            "createdBy": actor_uid,
        }
        if task_template["title"] == "File with VCF program" and vcf_deadline is not None:
            task_doc["dueDate"] = vcf_deadline
        batch.set(task_ref, task_doc)
        task_ids.append(task_id)

    # ── Resolve escalation sub-doc ────────────────────────────────────────
    escalation_data: dict = {}
    if escalation_id:
        esc_ref = case_ref.collection("escalations").document(escalation_id)
        esc_snap = esc_ref.get()
        escalation_data = esc_snap.to_dict() or {} if esc_snap.exists else {}
        batch.update(esc_ref, {
            "status":        "approved",
            "resolvedAt":    now,
            "resolvedBy":    actor_uid,
            "resolvedByName": actor_name,
            "decision":      "approve",
            "decisionNotes": notes,
        })
        # Update top-level metrics doc
        days_to_resolve = None
        esc_at = escalation_data.get("escalatedAt")
        if esc_at:
            if hasattr(esc_at, "tzinfo") and esc_at.tzinfo is None:
                esc_at = esc_at.replace(tzinfo=timezone.utc)
            days_to_resolve = (now - esc_at).days
        event_ref = db.collection("escalation_events").document(escalation_id)
        batch.update(event_ref, {
            "resolvedAt":    now,
            "resolvedBy":    actor_uid,
            "decision":      "approve",
            "daysToResolve": days_to_resolve,
        })

    # ── Paralegal notification ────────────────────────────────────────────
    if paralegal_uid:
        notif_id  = str(_uuid.uuid4())
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

    # ── Junior partner notification ───────────────────────────────────────
    if original_attorney_id:
        notif_id  = str(_uuid.uuid4())
        notif_ref = db.collection("notifications").document(notif_id)
        batch.set(notif_ref, {
            "notificationId": notif_id,
            "type":           "escalation_approved",
            "caseId":         case_id,
            "recipientId":    original_attorney_id,
            "message":        "Senior partner {} approved case {} for filing.".format(
                actor_name or actor_uid, case_id
            ),
            "createdAt":  now,
            "read":       False,
            "createdBy":  actor_uid,
            "createdByName": actor_name,
        })

    # ── Timeline event ────────────────────────────────────────────────────
    timeline_ref = case_ref.collection("timeline").document()
    batch.set(timeline_ref, {
        "eventId":         timeline_ref.id,
        "caseId":          case_id,
        "eventType":       "EscalationDecision",
        "description":     "Escalated case approved for filing by {}.".format(actor_name or actor_uid),
        "performedBy":     actor_uid,
        "performedByName": actor_name,
        "timestamp":       now,
        "metadata": {
            "previousStatus": ESCALATED_STATUS,
            "newStatus":      APPROVED_STATUS,
            "decision":       "approve",
            "approvalNotes":  notes,
            "taskIds":        task_ids,
            "escalationId":   escalation_id,
        },
    })

    batch.commit()

    logger.info(
        "Escalated case %s approved for filing by %s; tasks=%s escalation_id=%s",
        case_id, actor_uid, task_ids, escalation_id,
    )

    return {
        "case_id":     case_id,
        "decision":    "approve",
        "resolved_at": now,
        "resolved_by": actor_uid,
        "notes":       notes,
        "task_ids":    task_ids,
        "new_status":  APPROVED_STATUS,
    }
