"""
Decision Audit Utility

Writes one AuditEvent document to TWO Firestore paths atomically in the same batch:
  audit_events/{eventId}               ← global log (all services, per Common Audit Log Schema)
  cases/{caseId}/audit_events/{eventId} ← denormalized for case-scoped queries

Both writes must be included in the caller's already-open WriteBatch BEFORE batch.commit().

Immutability contract:
  - This module only ever calls batch.set().
  - It never calls batch.update() or batch.delete() on audit_events documents.
  - Firestore Security Rules should enforce create-only access on this collection.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from google.cloud import firestore

logger = logging.getLogger(__name__)

# Canonical decisionType values — stored in metadata.decision_type for case-development events.
DECISION_TYPE_APPROVE_FOR_FILING  = "approve_for_filing"
DECISION_TYPE_ESCALATE            = "escalate"
DECISION_TYPE_ESCALATION_APPROVE  = "escalation_approve"
DECISION_TYPE_ESCALATION_REJECT   = "escalation_reject"
DECISION_TYPE_ESCALATION_RETURN   = "escalation_return"
DECISION_TYPE_REJECT_CASE         = "reject_case"

# Per Common Audit Log Schema §5 — service identifier for this microservice.
_SERVICE_NAME = "case-management"


def write_decision_audit_event(
    batch: firestore.WriteBatch,
    db: firestore.Client,
    event_id: str,
    case_id: str,
    decision_type: str,
    event_type: str,
    performed_by: str,
    performed_by_name: Optional[str],
    performed_by_role: str,
    timestamp: datetime,
    previous_status: str,
    new_status: str,
    reason: Optional[str] = None,
    notes: Optional[str] = None,
    case_submitted_for_review_at: Optional[datetime] = None,
    related_doc_id: Optional[str] = None,
) -> None:
    """
    Add two batch.set() writes for one audit event — global + case-scoped.

    Parameters
    ----------
    batch
        Open WriteBatch from the calling service. The caller is responsible
        for calling batch.commit() after all writes (including these) are added.
    db
        Firestore client.
    event_id
        UUID that identifies this audit record. Pass the same ID as the
        timeline event written in the same batch so both records are linked.
    case_submitted_for_review_at
        Proxy for "when the attorney's review period started":
          - approve_for_filing / escalate / reject_case:
              pass case_data.get("submittedForReviewAt")
          - escalation_approve / escalation_reject / escalation_return:
              pass (case_data.get("escalation") or {}).get("escalatedAt")
        When None, reviewDurationSeconds in metadata is also None.
    """
    review_duration_seconds: Optional[int] = None

    if case_submitted_for_review_at is not None:
        ts = case_submitted_for_review_at
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        delta_seconds = (timestamp - ts).total_seconds()
        review_duration_seconds = max(0, int(delta_seconds))

    doc = {
        # ── Common Audit Log Schema fields ────────────────────────────────────
        "id":            event_id,
        "timestamp":     timestamp,
        "actor_id":      performed_by,
        "actor_type":    "staff",
        "actor_role":    performed_by_role,
        "action":        "STATUS_CHANGED",
        "resource_type": "case",
        "resource_id":   case_id,
        "case_id":       case_id,
        "service":       _SERVICE_NAME,
        "outcome":       "success",
        "changes": {
            "status": {
                "before": previous_status,
                "after":  new_status,
            }
        },
        # ── Service-specific context (case-management) ────────────────────────
        "metadata": {
            "decision_type":               decision_type,
            "event_type":                  event_type,
            "performed_by_name":           performed_by_name,
            "reason":                      reason,
            "notes":                       notes,
            "review_duration_seconds":     review_duration_seconds,
            "case_submitted_for_review_at": case_submitted_for_review_at,
            "related_doc_id":              related_doc_id,
        },
    }

    # Write 1: global audit_events collection
    global_ref = db.collection("audit_events").document(event_id)
    batch.set(global_ref, doc)

    # Write 2: denormalized case-scoped sub-collection
    case_ref = (
        db.collection("cases")
        .document(case_id)
        .collection("audit_events")
        .document(event_id)
    )
    batch.set(case_ref, doc)

    logger.debug(
        "audit_events write queued: event_id=%s case=%s decision_type=%s actor=%s",
        event_id, case_id, decision_type, performed_by,
    )
