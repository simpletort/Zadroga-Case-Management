"""
Communication Log Service

Firestore path: cases/{caseId}/communications/{commId}

Firestore field mapping:
  channel          → channel          (Email | Call | Letter | Fax | In Person)
  direction        → direction         (Inbound | Outbound)
  subject          → subject
  body             → body
  from             → from_address      ("from" is a Python keyword)
  to               → to
  deliveryStatus   → delivery_status
  isAutomated      → is_automated
  loggedBy         → logged_by
  templateId       → template_id
  externalMessageId→ external_message_id
  sentAt           → sent_at           (primary timestamp)

GET strategy:
  1. Stream the full communications sub-collection with no server-side order_by.
     Firestore silently excludes documents that lack the ordered field, so sorting
     is done in Python after materialisation instead.
  2. Sort by sentAt descending in Python (missing sentAt sorts to bottom).
  3. Apply optional channel filter in Python (avoids extra composite indexes).
  4. Paginate in Python (consistent with dashboard pattern).

POST strategy:
  1. Verify the parent case exists (raises 404 if not).
  2. Write the new communication document matching the existing schema.
  3. Append a timeline event on the parent case.
"""

import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException, status
from google.cloud import firestore

logger = logging.getLogger(__name__)


def _normalise_ts(ts) -> Optional[datetime]:
    """Return an aware datetime from a Firestore Timestamp or datetime, or None."""
    if ts is None:
        return None
    if hasattr(ts, "tzinfo") and ts.tzinfo is None:
        return ts.replace(tzinfo=timezone.utc)
    return ts


def list_communications(
    db: firestore.Client,
    case_id: str,
    channel: Optional[str],
    page: int,
    page_size: int,
) -> dict:
    # Verify case exists
    case_ref = db.collection("cases").document(case_id)
    if not case_ref.get().exists:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Case '{case_id}' not found.",
        )

    # Stream the full sub-collection — no server-side order_by so documents
    # without a sentAt field are not silently excluded by Firestore
    docs = list(case_ref.collection("communications").stream())
    logger.info("Retrieved %d communications for case %s", len(docs), case_id)

    # Materialise and normalise
    entries: list[dict] = []
    for doc in docs:
        data = doc.to_dict() or {}
        entries.append({
            "comm_id":              doc.id,
            "channel":              data.get("channel", ""),
            "direction":            data.get("direction", ""),
            "subject":              data.get("subject", ""),
            "body":                 data.get("body"),
            "from_address":         data.get("from"),
            "to":                   data.get("to"),
            "delivery_status":      data.get("deliveryStatus"),
            "is_automated":         data.get("isAutomated", False),
            "logged_by":            data.get("loggedBy"),
            "template_id":          data.get("templateId"),
            "external_message_id":  data.get("externalMessageId"),
            "sent_at":              _normalise_ts(data.get("sentAt")),
        })

    # Sort newest first in Python
    entries.sort(
        key=lambda e: e["sent_at"].timestamp() if e["sent_at"] else 0.0,
        reverse=True,
    )

    # Post-filter by channel
    if channel:
        entries = [e for e in entries if e["channel"] == channel]

    # Paginate
    total       = len(entries)
    total_pages = max(1, (total + page_size - 1) // page_size)
    start       = (page - 1) * page_size
    page_items  = entries[start: start + page_size]

    return {
        "items":       page_items,
        "total":       total,
        "page":        page,
        "page_size":   page_size,
        "total_pages": total_pages,
    }


def create_communication(
    db: firestore.Client,
    case_id: str,
    actor_uid: str,
    channel: str,
    direction: str,
    subject: str,
    body: Optional[str],
    from_address: Optional[str],
    to: Optional[str],
) -> dict:
    case_ref  = db.collection("cases").document(case_id)
    case_snap = case_ref.get()
    if not case_snap.exists:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Case '{case_id}' not found.",
        )

    now     = datetime.now(tz=timezone.utc)
    comm_id = str(uuid.uuid4())

    comm_data = {
        "commId":      comm_id,
        "caseId":      case_id,
        "channel":     channel,
        "direction":   direction,
        "subject":     subject,
        "body":        body,
        "from":        from_address,
        "to":          to,
        "deliveryStatus":      "Sent",
        "isAutomated":         False,
        "loggedBy":            actor_uid,
        "templateId":          "",
        "externalMessageId":   "",
        "sentAt":              now,
    }

    # Write communication document and timeline event atomically
    comm_ref     = case_ref.collection("communications").document(comm_id)
    timeline_ref = case_ref.collection("timeline").document()

    batch = db.batch()
    batch.set(comm_ref, comm_data)
    batch.set(timeline_ref, {
        "eventType":   "Communication",
        "description": f"{direction} {channel} — {subject}",
        "performedBy": actor_uid,
        "timestamp":   now,
    })
    batch.update(case_ref, {"updatedAt": now})
    batch.commit()

    logger.info("Communication %s logged on case %s by %s", comm_id, case_id, actor_uid)

    return {
        "comm_id":             comm_id,
        "channel":             channel,
        "direction":           direction,
        "subject":             subject,
        "body":                body,
        "from_address":        from_address,
        "to":                  to,
        "delivery_status":     "Sent",
        "is_automated":        False,
        "logged_by":           actor_uid,
        "template_id":         None,
        "external_message_id": None,
        "sent_at":             now,
    }
