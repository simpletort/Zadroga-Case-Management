"""
Communication Log Service

Firestore path: cases/{caseId}/communications/{commId}

GET strategy:
  1. Stream the full communications sub-collection ordered by createdAt desc.
  2. Apply optional type filter in Python (avoids extra composite indexes).
  3. Paginate in Python (consistent with dashboard pattern).

POST strategy:
  1. Verify the parent case exists (raises 404 if not).
  2. Resolve the actor's display name from the staff collection.
  3. Write the new communication document.
  4. Append a timeline event on the parent case.
"""

import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException, status
from google.cloud import firestore

logger = logging.getLogger(__name__)


def list_communications(
    db: firestore.Client,
    case_id: str,
    comm_type: Optional[str],
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

    # Stream sub-collection ordered newest first
    query = (
        case_ref.collection("communications")
        .order_by("createdAt", direction=firestore.Query.DESCENDING)
    )
    docs = list(query.stream())
    logger.info("Retrieved %d communications for case %s", len(docs), case_id)

    # Materialise and normalise timestamps
    entries: list[dict] = []
    for doc in docs:
        data = doc.to_dict() or {}
        created_at = data.get("createdAt")
        if hasattr(created_at, "tzinfo") and created_at is not None and created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)

        entries.append({
            "comm_id":        doc.id,
            "type":           data.get("type", ""),
            "direction":      data.get("direction", ""),
            "subject":        data.get("subject", ""),
            "notes":          data.get("notes"),
            "contact_name":   data.get("contactName"),
            "contact_method": data.get("contactMethod"),
            "created_by":     data.get("createdBy", ""),
            "created_by_name": data.get("createdByName"),
            "created_at":     created_at,
        })

    # Post-filter by type
    if comm_type:
        entries = [e for e in entries if e["type"] == comm_type]

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
    comm_type: str,
    direction: str,
    subject: str,
    notes: Optional[str],
    contact_name: Optional[str],
    contact_method: Optional[str],
) -> dict:
    case_ref = db.collection("cases").document(case_id)
    case_snap = case_ref.get()
    if not case_snap.exists:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Case '{case_id}' not found.",
        )

    # Resolve actor display name from staff collection
    staff_snap = db.collection("staff").document(actor_uid).get()
    actor_name = staff_snap.to_dict().get("displayName") if staff_snap.exists else None

    now     = datetime.now(tz=timezone.utc)
    comm_id = str(uuid.uuid4())

    comm_data = {
        "type":          comm_type,
        "direction":     direction,
        "subject":       subject,
        "notes":         notes,
        "contactName":   contact_name,
        "contactMethod": contact_method,
        "createdBy":     actor_uid,
        "createdByName": actor_name,
        "createdAt":     now,
    }

    # Write communication document and timeline event atomically
    comm_ref     = case_ref.collection("communications").document(comm_id)
    timeline_ref = case_ref.collection("timeline").document()

    batch = db.batch()
    batch.set(comm_ref, comm_data)
    batch.set(timeline_ref, {
        "eventType":   "Communication",
        "description": f"{direction.capitalize()} {comm_type} — {subject}",
        "performedBy": actor_uid,
        "performedByName": actor_name,
        "timestamp":   now,
    })
    batch.update(case_ref, {"updatedAt": now})
    batch.commit()

    logger.info("Communication %s logged on case %s by %s", comm_id, case_id, actor_uid)

    return {
        "comm_id":        comm_id,
        "type":           comm_type,
        "direction":      direction,
        "subject":        subject,
        "notes":          notes,
        "contact_name":   contact_name,
        "contact_method": contact_method,
        "created_by":     actor_uid,
        "created_by_name": actor_name,
        "created_at":     now,
    }
