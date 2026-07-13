"""
Timeline Service

Firestore path: cases/{caseId}/timeline/{eventId}

Firestore field mapping:
  eventType    → event_type
  description  → description
  performedBy  → performed_by
  timestamp    → timestamp

GET strategy:
  1. Verify the parent case exists (raises 404 if not).
  2. Stream the full timeline sub-collection with no server-side order_by to
     avoid silently dropping documents that lack a timestamp field.
  3. Sort by timestamp descending in Python.
  4. Apply optional event_type filter in Python.
  5. Paginate in Python.
"""

import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException, status
from google.cloud import firestore

logger = logging.getLogger(__name__)


def _normalise_ts(ts) -> Optional[datetime]:
    if ts is None:
        return None
    if hasattr(ts, "tzinfo") and ts.tzinfo is None:
        return ts.replace(tzinfo=timezone.utc)
    return ts


def list_timeline(
    db: firestore.Client,
    case_id: str,
    event_type: Optional[str],
    page: int,
    page_size: int,
) -> dict:
    case_ref = db.collection("cases").document(case_id)
    if not case_ref.get().exists:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Case '{case_id}' not found.",
        )

    docs = list(case_ref.collection("timeline").stream())
    logger.info("Retrieved %d timeline events for case %s", len(docs), case_id)

    events: list[dict] = []
    for doc in docs:
        data = doc.to_dict() or {}
        events.append({
            "event_id":    doc.id,
            "event_type":  data.get("eventType", ""),
            "description": data.get("description", ""),
            "performed_by": data.get("performedBy"),
            "timestamp":   _normalise_ts(data.get("timestamp")),
        })

    events.sort(
        key=lambda e: e["timestamp"].timestamp() if e["timestamp"] else 0.0,
        reverse=True,
    )

    if event_type:
        events = [e for e in events if e["event_type"] == event_type]

    total       = len(events)
    total_pages = max(1, (total + page_size - 1) // page_size)
    start       = (page - 1) * page_size
    page_items  = events[start: start + page_size]

    return {
        "items":       page_items,
        "total":       total,
        "page":        page,
        "page_size":   page_size,
        "total_pages": total_pages,
    }
