"""
Decision Audit Query Service

Reads from the global `audit_events` collection, always filtered to
service == "case-management" so cross-service writes are excluded.

This service is intentionally read-only: no .set(), .update(), or .delete() calls.

Query strategy:
  - Primary server-side filter: service == "case-management" (always applied).
  - Secondary server-side filter: date range on `timestamp` when provided.
  - Tertiary Python-side filters: case_id, actor_id, decision_type.
  - Sorting and pagination are Python-side (avoids composite index requirements).

For single-case queries, prefer the case-scoped sub-collection
(cases/{caseId}/audit_events) to avoid a full collection scan.
"""

from __future__ import annotations

import logging
import math
from datetime import datetime, timezone
from typing import Optional

from google.cloud import firestore

logger = logging.getLogger(__name__)

_SERVICE_FILTER = "case-management"


# ─────────────────────────────────────────────────────────────────────────────
# Internal helpers
# ─────────────────────────────────────────────────────────────────────────────

def _to_item(doc_data: dict) -> dict:
    """Normalise an audit_events document to the snake_case API shape."""
    meta = doc_data.get("metadata") or {}
    changes = doc_data.get("changes") or {}
    status_change = changes.get("status") or {}

    return {
        "event_id":                    doc_data.get("id", ""),
        "case_id":                     doc_data.get("case_id", ""),
        "decision_type":               meta.get("decision_type", ""),
        "event_type":                  meta.get("event_type", ""),
        "performed_by":                doc_data.get("actor_id", ""),
        "performed_by_name":           meta.get("performed_by_name"),
        "performed_by_role":           doc_data.get("actor_role", ""),
        "timestamp":                   doc_data.get("timestamp"),
        "previous_status":             status_change.get("before", ""),
        "new_status":                  status_change.get("after", ""),
        "reason":                      meta.get("reason"),
        "notes":                       meta.get("notes"),
        "review_duration_seconds":     meta.get("review_duration_seconds"),
        "case_submitted_for_review_at": meta.get("case_submitted_for_review_at"),
        "related_doc_id":              meta.get("related_doc_id"),
        "created_at":                  doc_data.get("timestamp"),
    }


def _avg(values: list) -> Optional[float]:
    cleaned = [v for v in values if v is not None]
    return round(sum(cleaned) / len(cleaned), 2) if cleaned else None


def _build_base_query(
    db: firestore.Client,
    date_from: Optional[datetime],
    date_to: Optional[datetime],
) -> firestore.Query:
    """
    Base query: always scoped to case-management, optionally date-ranged.
    Both filters on different fields require only simple single-field indexes.
    """
    query = db.collection("audit_events").where("service", "==", _SERVICE_FILTER)
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
        docs = [d for d in docs if d.get("case_id") == case_id]
    if performed_by:
        docs = [d for d in docs if d.get("actor_id") == performed_by]
    if decision_type:
        docs = [
            d for d in docs
            if (d.get("metadata") or {}).get("decision_type") == decision_type
        ]
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
    Return a paginated, filtered list of case-management audit events.
    Sorted: timestamp DESC (newest first).
    """
    query = _build_base_query(db, date_from, date_to)

    # When only case_id is provided (no date range), use the case-scoped
    # sub-collection to avoid a full audit_events scan.
    if case_id and date_from is None and date_to is None and performed_by is None and decision_type is None:
        query = (
            db.collection("cases")
            .document(case_id)
            .collection("audit_events")
        )

    raw_docs = [doc.to_dict() or {} for doc in query.stream()]
    raw_docs = _apply_python_filters(raw_docs, case_id, performed_by, decision_type)

    raw_docs.sort(key=lambda d: (d.get("timestamp") or datetime.min), reverse=True)

    total = len(raw_docs)
    total_pages = math.ceil(total / page_size) if page_size else 1
    start = (page - 1) * page_size
    page_docs = raw_docs[start: start + page_size]

    return {
        "total_decisions": total,
        "page": {
            "items":       [_to_item(d) for d in page_docs],
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
    Return all audit events for a single case using the case-scoped sub-collection.
    Sorted chronologically (oldest-first — natural case timeline).
    """
    query = (
        db.collection("cases")
        .document(case_id)
        .collection("audit_events")
    )
    raw_docs = [doc.to_dict() or {} for doc in query.stream()]
    raw_docs.sort(key=lambda d: (d.get("timestamp") or datetime.min))

    return {
        "case_id":   case_id,
        "decisions": [_to_item(d) for d in raw_docs],
        "total":     len(raw_docs),
    }


def get_decision_metrics(
    db: firestore.Client,
    date_from: Optional[datetime] = None,
    date_to: Optional[datetime] = None,
    performed_by: Optional[str] = None,
    decision_type: Optional[str] = None,
) -> dict:
    """Aggregate time-to-decision metrics over a date range."""
    query = _build_base_query(db, date_from, date_to)
    raw_docs = [doc.to_dict() or {} for doc in query.stream()]
    raw_docs = _apply_python_filters(raw_docs, None, performed_by, decision_type)

    by_type: dict[str, list[dict]] = {}
    by_actor: dict[str, list[dict]] = {}

    for d in raw_docs:
        dt = (d.get("metadata") or {}).get("decision_type", "unknown")
        by_type.setdefault(dt, []).append(d)

        actor = d.get("actor_id", "unknown")
        by_actor.setdefault(actor, []).append(d)

    by_decision_type_counts = {k: len(v) for k, v in by_type.items()}

    def _duration(d: dict) -> Optional[int]:
        return (d.get("metadata") or {}).get("review_duration_seconds")

    all_durations = [_duration(d) for d in raw_docs]
    avg_overall = _avg(all_durations)

    avg_by_type: dict[str, Optional[float]] = {
        dt: _avg([_duration(d) for d in docs])
        for dt, docs in by_type.items()
    }

    attorney_metrics = []
    for actor_uid, docs in by_actor.items():
        actor_name = next(
            ((d.get("metadata") or {}).get("performed_by_name") for d in docs
             if (d.get("metadata") or {}).get("performed_by_name")),
            None,
        )
        type_counts: dict[str, int] = {}
        for d in docs:
            dt = (d.get("metadata") or {}).get("decision_type", "unknown")
            type_counts[dt] = type_counts.get(dt, 0) + 1

        attorney_metrics.append({
            "performed_by":                actor_uid,
            "performed_by_name":           actor_name,
            "decision_count":              len(docs),
            "avg_review_duration_seconds": _avg([_duration(d) for d in docs]),
            "decisions_by_type":           type_counts,
        })

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
    Full non-paginated audit dump for compliance export.
    Sorted: timestamp ASC (chronological, suitable for a compliance log).
    """
    now = datetime.now(tz=timezone.utc)

    if case_id and date_from is None and date_to is None:
        query = (
            db.collection("cases")
            .document(case_id)
            .collection("audit_events")
        )
    else:
        query = _build_base_query(db, date_from, date_to)

    raw_docs = [doc.to_dict() or {} for doc in query.stream()]
    raw_docs = _apply_python_filters(raw_docs, case_id, performed_by, decision_type)
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
