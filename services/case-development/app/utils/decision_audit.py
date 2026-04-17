"""
Decision Audit Utility

Provides write_decision_audit_event() — a helper that adds one batch.set() call
to the top-level `decision_audit` collection.  It must be invoked INSIDE an
already-open Firestore WriteBatch, before batch.commit(), so the audit record is
written atomically with the decision itself.

Immutability contract:
  - This module only ever calls batch.set().
  - It never calls batch.update() or batch.delete() on decision_audit documents.
  - Firestore Security Rules should enforce create-only access on this collection.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from google.cloud import firestore

logger = logging.getLogger(__name__)

# Canonical decisionType values — used as the discriminator for cross-case queries.
DECISION_TYPE_APPROVE_FOR_FILING  = "approve_for_filing"
DECISION_TYPE_ESCALATE            = "escalate"
DECISION_TYPE_ESCALATION_APPROVE  = "escalation_approve"
DECISION_TYPE_ESCALATION_REJECT   = "escalation_reject"
DECISION_TYPE_ESCALATION_RETURN   = "escalation_return"
DECISION_TYPE_REJECT_CASE         = "reject_case"

_SERVICE_NAME = "case-development"


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
    Add one batch.set() write to ``decision_audit/{event_id}``.

    Parameters
    ----------
    batch
        Open WriteBatch from the calling service.  The caller is responsible
        for calling batch.commit() after all writes (including this one) are
        added.
    db
        Firestore client.
    event_id
        UUID that identifies this audit record.  Pass the same ID as the
        timeline event written in the same batch so both records are linked.
    case_submitted_for_review_at
        Proxy for "when the attorney's review period started":
          - approve_for_filing / escalate / reject_case:
              pass case_data.get("submittedForReviewAt")
          - escalation_approve / escalation_reject / escalation_return:
              pass (case_data.get("escalation") or {}).get("escalatedAt")
        When None, reviewDurationSeconds is also None.
    """
    review_duration_seconds: Optional[int] = None

    if case_submitted_for_review_at is not None:
        ts = case_submitted_for_review_at
        # Firestore can return naive datetimes — normalise before arithmetic.
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        delta_seconds = (timestamp - ts).total_seconds()
        review_duration_seconds = max(0, int(delta_seconds))

    audit_ref = db.collection("decision_audit").document(event_id)
    batch.set(audit_ref, {
        "eventId":                  event_id,
        "caseId":                   case_id,
        "service":                  _SERVICE_NAME,
        "decisionType":             decision_type,
        "eventType":                event_type,
        "previousStatus":           previous_status,
        "newStatus":                new_status,
        "performedBy":              performed_by,
        "performedByName":          performed_by_name,
        "performedByRole":          performed_by_role,
        "timestamp":                timestamp,
        "caseSubmittedForReviewAt": case_submitted_for_review_at,
        "reviewDurationSeconds":    review_duration_seconds,
        "reason":                   reason,
        "notes":                    notes,
        "relatedDocId":             related_doc_id,
        "createdAt":                timestamp,   # immutability marker
    })

    logger.debug(
        "decision_audit write queued: event_id=%s case=%s type=%s by=%s",
        event_id, case_id, decision_type, performed_by,
    )
