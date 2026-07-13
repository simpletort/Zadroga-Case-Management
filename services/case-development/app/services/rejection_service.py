"""
Rejection Service

Reject Case (atomic batch per case):
  1. Verify case is "Pending Attorney Review"
  2. Verify actor is the assigned attorney OR has senior_partner+ level
  3. Set case status → "Rejected"
  4. Record rejectedAt, rejectedBy, rejection.reason, rejection.notes
  5. Create rejection sub-doc in cases/{caseId}/rejections/
  6. Create paralegal notification in notifications/
  7. Append timeline event (audit trail)

Resubmit Case (atomic batch per case):
  1. Verify case is "Rejected"
  2. Verify actor is the assigned paralegal OR has admin_staff+ level
  3. Set case status → "Pending Paralegal Review"
  4. Record resubmittedAt, resubmittedBy (rejection.* fields preserved for history)
  5. Create attorney notification in notifications/
  6. Append timeline event (audit trail)
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
    DECISION_TYPE_REJECT_CASE,
)

logger = logging.getLogger(__name__)

REVIEW_STATUS    = "Pending Attorney Review"
REJECTED_STATUS  = "Rejected"
PARALEGAL_STATUS = "Pending Paralegal Review"

# Roles that bypass the "assigned attorney only" check when rejecting
SENIOR_ROLES = {"senior_partner", "system_admin"}

# Roles that bypass the "assigned paralegal only" check when resubmitting
ADMIN_ROLES = {"admin_staff", "junior_partner", "senior_partner", "system_admin"}

REJECTION_REASON_LABELS = {
    "insufficient_medical_evidence": "Insufficient Medical Evidence",
    "does_not_meet_vcf_criteria":    "Does Not Meet VCF Criteria",
    "incomplete_documentation":      "Incomplete Documentation",
    "client_unresponsive":           "Client Unresponsive",
    "other":                         "Other",
}


# ─────────────────────────────────────────────────────────────────────────────
# Internal helpers
# ─────────────────────────────────────────────────────────────────────────────

def _get_actor_name(db: firestore.Client, actor_uid: str) -> Optional[str]:
    snap = db.collection("staff").document(actor_uid).get()
    return (snap.to_dict() or {}).get("displayName") if snap.exists else None


# ─────────────────────────────────────────────────────────────────────────────
# Reject Case
# ─────────────────────────────────────────────────────────────────────────────

def reject_case(
    db: firestore.Client,
    case_id: str,
    actor_uid: str,
    actor_role: str,
    reason: str,
    notes: Optional[str],
) -> dict:
    """
    Reject a case from Pending Attorney Review.
    Raises HTTPException on validation failure.
    """
    actor_role = normalize_role(actor_role)
    is_senior  = actor_role in SENIOR_ROLES

    case_ref  = db.collection("cases").document(case_id)
    case_snap = case_ref.get()
    if not case_snap.exists:
        raise HTTPException(status_code=404, detail="Case '{}' not found.".format(case_id))

    case_data      = case_snap.to_dict() or {}
    current_status = case_data.get("status", "")

    if current_status != REVIEW_STATUS:
        raise HTTPException(
            status_code=422,
            detail=(
                "Case '{}' cannot be rejected: status is '{}', expected '{}'.".format(
                    case_id, current_status, REVIEW_STATUS
                )
            ),
        )

    assigned_attorney  = (case_data.get("assignment") or {}).get("assignedAttorney")
    assigned_paralegal = (case_data.get("assignment") or {}).get("assignedParalegal")

    if not is_senior and assigned_attorney != actor_uid:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are not the assigned attorney for case '{}'.".format(case_id),
        )

    # Belt-and-suspenders (model validator covers this, but protect direct calls)
    if reason == "other" and not (notes or "").strip():
        raise HTTPException(
            status_code=422,
            detail="notes are required when reason is 'other'.",
        )

    actor_name   = _get_actor_name(db, actor_uid)
    now          = datetime.now(tz=timezone.utc)
    rejection_id = str(uuid.uuid4())

    reason_label = REJECTION_REASON_LABELS.get(reason, reason)

    batch = db.batch()

    # ── Write 1: Update case document ────────────────────────────────────────
    batch.update(case_ref, {
        "status":                  REJECTED_STATUS,
        "updatedAt":               now,
        "lastStatusChangedAt":     now,
        "rejectedAt":              now,
        "rejectedBy":              actor_uid,
        "rejection.reason":        reason,
        "rejection.notes":         notes,
        "rejection.rejectionId":   rejection_id,
    })

    # ── Write 2: Rejection sub-document ──────────────────────────────────────
    rejection_ref = case_ref.collection("rejections").document(rejection_id)
    batch.set(rejection_ref, {
        "rejectionId":      rejection_id,
        "caseId":           case_id,
        "rejectedAt":       now,
        "rejectedBy":       actor_uid,
        "rejectedByName":   actor_name,
        "reason":           reason,
        "notes":            notes,
        "previousStatus":   REVIEW_STATUS,
        "resubmittedAt":    None,
        "resubmittedBy":    None,
    })

    # ── Write 3: Timeline event ───────────────────────────────────────────────
    timeline_ref = case_ref.collection("timeline").document()
    batch.set(timeline_ref, {
        "eventId":         timeline_ref.id,
        "caseId":          case_id,
        "eventType":       "CaseRejection",
        "description":     "Case rejected by {} — {}.".format(
            actor_name or actor_uid, reason_label
        ),
        "performedBy":     actor_uid,
        "performedByName": actor_name,
        "timestamp":       now,
        "metadata": {
            "previousStatus": REVIEW_STATUS,
            "newStatus":      REJECTED_STATUS,
            "reason":         reason,
            "notes":          notes,
            "rejectionId":    rejection_id,
        },
    })

    # ── Write 4: Notification to assigned paralegal ───────────────────────────
    notified_paralegal = False
    if assigned_paralegal:
        notif_id  = str(uuid.uuid4())
        notif_ref = db.collection("notifications").document(notif_id)
        message   = "Case {} has been rejected by {} — {}".format(
            case_id,
            actor_name or actor_uid,
            reason_label,
        )
        if notes:
            message += ": {}".format(notes)
        message += "."
        batch.set(notif_ref, {
            "notificationId":  notif_id,
            "type":            "case_rejected",
            "caseId":          case_id,
            "recipientId":     assigned_paralegal,
            "message":         message,
            "createdAt":       now,
            "read":            False,
            "createdBy":       actor_uid,
            "createdByName":   actor_name,
        })
        notified_paralegal = True

    # ── Write 5: Decision audit (immutable cross-case record) ─────────────────
    write_decision_audit_event(
        batch=batch,
        db=db,
        event_id=rejection_id,
        case_id=case_id,
        decision_type=DECISION_TYPE_REJECT_CASE,
        event_type="CaseRejection",
        performed_by=actor_uid,
        performed_by_name=actor_name,
        performed_by_role=actor_role,
        timestamp=now,
        previous_status=REVIEW_STATUS,
        new_status=REJECTED_STATUS,
        reason=reason,
        notes=notes,
        case_submitted_for_review_at=case_data.get("submittedForReviewAt"),
        related_doc_id=rejection_id,
    )

    batch.commit()

    logger.info(
        "Case rejected: case=%s reason=%s by=%s rejection_id=%s",
        case_id, reason, actor_uid, rejection_id,
    )

    return {
        "case_id":            case_id,
        "status":             REJECTED_STATUS,
        "rejected_at":        now,
        "rejection_id":       rejection_id,
        "notified_paralegal": notified_paralegal,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Resubmit Case
# ─────────────────────────────────────────────────────────────────────────────

def resubmit_case(
    db: firestore.Client,
    case_id: str,
    actor_uid: str,
    actor_role: str,
    notes: Optional[str],
) -> dict:
    """
    Resubmit a rejected case back to Pending Paralegal Review.
    Raises HTTPException on validation failure.
    """
    actor_role = normalize_role(actor_role)
    is_admin   = actor_role in ADMIN_ROLES

    case_ref  = db.collection("cases").document(case_id)
    case_snap = case_ref.get()
    if not case_snap.exists:
        raise HTTPException(status_code=404, detail="Case '{}' not found.".format(case_id))

    case_data      = case_snap.to_dict() or {}
    current_status = case_data.get("status", "")

    if current_status != REJECTED_STATUS:
        raise HTTPException(
            status_code=422,
            detail=(
                "Case '{}' cannot be resubmitted: status is '{}', expected '{}'.".format(
                    case_id, current_status, REJECTED_STATUS
                )
            ),
        )

    assigned_paralegal = (case_data.get("assignment") or {}).get("assignedParalegal")
    assigned_attorney  = (case_data.get("assignment") or {}).get("assignedAttorney")

    if not is_admin and assigned_paralegal != actor_uid:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are not the assigned paralegal for case '{}'.".format(case_id),
        )

    actor_name   = _get_actor_name(db, actor_uid)
    now          = datetime.now(tz=timezone.utc)
    rejection_id = (case_data.get("rejection") or {}).get("rejectionId")

    batch = db.batch()

    # ── Write 1: Update case document ────────────────────────────────────────
    # rejection.* fields intentionally preserved for history
    batch.update(case_ref, {
        "status":              PARALEGAL_STATUS,
        "updatedAt":           now,
        "lastStatusChangedAt": now,
        "resubmittedAt":       now,
        "resubmittedBy":       actor_uid,
    })

    # ── Write 2: Timeline event ───────────────────────────────────────────────
    timeline_ref = case_ref.collection("timeline").document()
    batch.set(timeline_ref, {
        "eventId":         timeline_ref.id,
        "caseId":          case_id,
        "eventType":       "CaseResubmission",
        "description":     "Case resubmitted by {} for additional paralegal review.".format(
            actor_name or actor_uid
        ),
        "performedBy":     actor_uid,
        "performedByName": actor_name,
        "timestamp":       now,
        "metadata": {
            "previousStatus": REJECTED_STATUS,
            "newStatus":      PARALEGAL_STATUS,
            "notes":          notes,
            "rejectionId":    rejection_id,
        },
    })

    # ── Write 3: Notification to assigned attorney ────────────────────────────
    notified_attorney = False
    if assigned_attorney:
        notif_id  = str(uuid.uuid4())
        notif_ref = db.collection("notifications").document(notif_id)
        message   = "Case {} has been resubmitted for review by {}".format(
            case_id, actor_name or actor_uid
        )
        if notes:
            message += ": {}".format(notes)
        message += "."
        batch.set(notif_ref, {
            "notificationId":  notif_id,
            "type":            "case_resubmitted",
            "caseId":          case_id,
            "recipientId":     assigned_attorney,
            "message":         message,
            "createdAt":       now,
            "read":            False,
            "createdBy":       actor_uid,
            "createdByName":   actor_name,
        })
        notified_attorney = True

    batch.commit()

    logger.info(
        "Case resubmitted: case=%s by=%s",
        case_id, actor_uid,
    )

    return {
        "case_id":           case_id,
        "status":            PARALEGAL_STATUS,
        "resubmitted_at":    now,
        "notified_attorney": notified_attorney,
    }
