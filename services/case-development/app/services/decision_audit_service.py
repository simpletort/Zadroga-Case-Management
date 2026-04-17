"""
Decision Audit Query Service

Reads from the top-level `decision_audit` collection.  This service is
intentionally read-only: no .set(), .update(), or .delete() calls.

Query strategy (mirrors the existing codebase pattern):
  - Primary server-side filter: date range on `timestamp` field.
  - Secondary Python-side filters: caseId, performedBy, decisionType.
  - Sorting and pagination are Python-side (avoids composite index requirements).

Production note: Without a date-range filter the query becomes a full collection
scan.  Callers should always supply at least one of date_from / date_to / case_id.
"""

from __future__ import annotations

import logging
import math
from datetime import datetime, timezone
from typing import Optional

from google.cloud import firestore

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Internal helpers
# ─────────────────────────────────────────────────────────────────────────────

def _to_item(doc_data: dict) -> dict:
    """Normalise a Firestore document dict to a snake_case API shape."""
    return {
        "event_id":                    doc_data.get("eventId", ""),
        "case_id":                     doc_data.get("caseId", ""),
        "decision_type":               doc_data.get("decisionType", ""),
        "event_type":                  doc_data.get("eventType", ""),
        "performed_by":                doc_data.get("performedBy", ""),
        "performed_by_name":           doc_data.get("performedByName"),
        "performed_by_role":           doc_data.get("performedByRole", ""),
        "timestamp":                   doc_data.get("timestamp"),
        "previous_status":             doc_data.get("previousStatus", ""),
        "new_status":                  doc_data.get("newStatus", ""),
        "reason":                      doc_data.get("reason"),
        "notes":                       doc_data.get("notes"),
        "review_duration_seconds":     doc_data.get("reviewDurationSeconds"),
        "case_submitted_for_review_at": doc_data.get("caseSubmittedForReviewAt"),
        "related_doc_id":              doc_data.get("relatedDocId"),
        "created_at":                  doc_data.get("createdAt"),
    }


def _avg(values: list[int]) -> Optional[float]:
    """Return the average of a non-empty list, or None."""
    cleaned = [v for v in values if v is not None]
    return round(sum(cleaned) / len(cleaned), 2) if cleaned else None


def _build_query(
    db: firestore.Client,
    date_from: Optional[datetime],
    date_to: Optional[datetime],
) -> firestore.Query:
    """
    Build the base Firestore query with optional date-range filters.
    Both filters combined require only a single-field index on `timestamp`.
    """
    query = db.collection("decision_audit")
    if date_from is not None:
        if date_from.tzinfo is None:
            date_from = date_from.replace(tzinfo=timezone.utc)
        query = query.where("timestamp", ">=", date_from)
    if date_to is not None:
        if date_to.tzinfo is None:
            date_to = date_to.replace(tzinfo=timezone.utc)
        query = query.where("timestamp", "<=", date_to)
    return query


def _apply_python_filters(
    docs: list[dict],
    case_id: Optional[str],
    performed_by: Optional[str],
    decision_type: Optional[str],
) -> list[dict]:
    if case_id:
        docs = [d for d in docs if d.get("caseId") == case_id]
    if performed_by:
        docs = [d for d in docs if d.get("performedBy") == performed_by]
    if decision_type:
        docs = [d for d in docs if d.get("decisionType") == decision_type]
    return docs


# ─────────────────────────────────────────────────────────────────────────────
# Public functions
# ─────────────────────────────────────────────────────────────────────────────

def get_decisions(
    db: firestore.Client,
    case_id: Optional[str] = None,
    performed_by: Optional[str] = None,
    date_from: Optional[datetime] = None,
    date_to: Optional[datetime] = None,
    decision_type: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
) -> dict:
    """
    Return a paginated, filtered list of decision audit events.
    Sorted: timestamp DESC (newest first).
    """
    query = _build_query(db, date_from, date_to)

    # If case_id provided and no date range, use Firestore filter directly
    # (avoids full scan when caller knows the case).
    if case_id and date_from is None and date_to is None:
        query = query.where("caseId", "==", case_id)

    raw_docs = [doc.to_dict() or {} for doc in query.stream()]
    raw_docs = _apply_python_filters(raw_docs, case_id, performed_by, decision_type)

    # Sort newest-first
    raw_docs.sort(key=lambda d: (d.get("timestamp") or datetime.min), reverse=True)

    total = len(raw_docs)
    total_pages = math.ceil(total / page_size) if page_size else 1
    start = (page - 1) * page_size
    page_docs = raw_docs[start: start + page_size]

    items = [_to_item(d) for d in page_docs]

    return {
        "total_decisions": total,
        "page": {
            "items":       items,
            "total":       total,
            "page":        page,
            "page_size":   page_size,
            "total_pages": total_pages,
        },
    }


def get_case_decisions(
    db: firestore.Client,
    case_id: str,
) -> dict:
    """
    Return all decision audit events for a single case, sorted chronologically
    (oldest-first — gives a natural timeline of the case history).
    """
    query = db.collection("decision_audit").where("caseId", "==", case_id)
    raw_docs = [doc.to_dict() or {} for doc in query.stream()]

    # Sort oldest-first for chronological case history
    raw_docs.sort(key=lambda d: (d.get("timestamp") or datetime.min))

    items = [_to_item(d) for d in raw_docs]

    return {
        "case_id":   case_id,
        "decisions": items,
        "total":     len(items),
    }


def get_decision_metrics(
    db: firestore.Client,
    date_from: Optional[datetime] = None,
    date_to: Optional[datetime] = None,
    performed_by: Optional[str] = None,
    decision_type: Optional[str] = None,
) -> dict:
    """
    Aggregate time-to-decision metrics over a date range.

    Returns:
      - total_decisions
      - by_decision_type: count per type
      - avg_review_duration_seconds: overall average (None if no duration data)
      - avg_review_duration_by_type: per-type averages
      - by_attorney: per-actor breakdown
    """
    query = _build_query(db, date_from, date_to)
    raw_docs = [doc.to_dict() or {} for doc in query.stream()]
    raw_docs = _apply_python_filters(raw_docs, None, performed_by, decision_type)

    # ── Aggregate ──────────────────────────────────────────────────────────────
    by_type: dict[str, list[dict]] = {}
    by_actor: dict[str, list[dict]] = {}

    for d in raw_docs:
        dt = d.get("decisionType", "unknown")
        by_type.setdefault(dt, []).append(d)

        actor = d.get("performedBy", "unknown")
        by_actor.setdefault(actor, []).append(d)

    by_decision_type_counts = {k: len(v) for k, v in by_type.items()}

    all_durations = [d.get("reviewDurationSeconds") for d in raw_docs]
    avg_overall = _avg(all_durations)

    avg_by_type: dict[str, Optional[float]] = {}
    for dt, docs in by_type.items():
        avg_by_type[dt] = _avg([d.get("reviewDurationSeconds") for d in docs])

    attorney_metrics = []
    for actor_uid, docs in by_actor.items():
        actor_name = next(
            (d.get("performedByName") for d in docs if d.get("performedByName")),
            None,
        )
        type_counts: dict[str, int] = {}
        for d in docs:
            dt = d.get("decisionType", "unknown")
            type_counts[dt] = type_counts.get(dt, 0) + 1

        attorney_metrics.append({
            "performed_by":                actor_uid,
            "performed_by_name":           actor_name,
            "decision_count":              len(docs),
            "avg_review_duration_seconds": _avg([d.get("reviewDurationSeconds") for d in docs]),
            "decisions_by_type":           type_counts,
        })

    # Sort by decision_count desc
    attorney_metrics.sort(key=lambda a: a["decision_count"], reverse=True)

    return {
        "total_decisions":              len(raw_docs),
        "by_decision_type":             by_decision_type_counts,
        "avg_review_duration_seconds":  avg_overall,
        "avg_review_duration_by_type":  avg_by_type,
        "by_attorney":                  attorney_metrics,
        "date_from":                    date_from,
        "date_to":                      date_to,
    }


def generate_compliance_report(
    db: firestore.Client,
    date_from: Optional[datetime] = None,
    date_to: Optional[datetime] = None,
    performed_by: Optional[str] = None,
    case_id: Optional[str] = None,
    decision_type: Optional[str] = None,
) -> dict:
    """
    Return a full (non-paginated) audit dump for compliance export.

    The response envelope includes `generated_at` and `filters_applied` so the
    export is self-describing — the consumer does not need to reconstruct context.
    Sorted: timestamp ASC (chronological, suitable for a compliance log).
    """
    now = datetime.now(tz=timezone.utc)

    query = _build_query(db, date_from, date_to)
    if case_id and date_from is None and date_to is None:
        query = query.where("caseId", "==", case_id)

    raw_docs = [doc.to_dict() or {} for doc in query.stream()]
    raw_docs = _apply_python_filters(raw_docs, case_id, performed_by, decision_type)

    # Chronological order for compliance logs
    raw_docs.sort(key=lambda d: (d.get("timestamp") or datetime.min))

    records = [_to_item(d) for d in raw_docs]

    filters_applied: dict = {}
    if date_from:
        filters_applied["date_from"] = date_from.isoformat()
    if date_to:
        filters_applied["date_to"] = date_to.isoformat()
    if performed_by:
        filters_applied["performed_by"] = performed_by
    if case_id:
        filters_applied["case_id"] = case_id
    if decision_type:
        filters_applied["decision_type"] = decision_type

    logger.info(
        "Compliance report generated: filters=%s records=%d",
        filters_applied, len(records),
    )

    return {
        "generated_at":    now,
        "filters_applied": filters_applied,
        "total_records":   len(records),
        "records":         records,
    }
