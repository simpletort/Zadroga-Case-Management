"""
Case Update Service

Firestore path: cases/{caseId}/updates/{updateId}

Field mapping (Firestore → Python):
  updateId      → update_id
  caseId        → case_id
  text          → text               (current / latest text)
  authorId      → author_id
  authorName    → author_name
  authorRole    → author_role
  createdAt     → created_at
  updatedAt     → updated_at
  isEdited      → is_edited
  originalText  → original_text      (set on first edit; immutable thereafter)
  editHistory   → edit_history       (array of {text, editedAt}; append-only)

GET strategy:
  Stream the full sub-collection with no server-side order_by (avoids excluding
  documents without the sorted field). Sort by createdAt descending in Python.
  Paginate in Python.

POST strategy:
  Verify case exists (404 otherwise). Look up staff/{uid}.displayName for
  author_name (fall back to uid if document is absent). Write update document
  and a CaseUpdate timeline event atomically via batch.

PATCH strategy:
  Verify case and update exist (404 otherwise). Check actor_uid == author_id
  (403 if not — no role-based override for edit). On first edit set originalText
  to the current text. Append {text, editedAt} to editHistory before replacing
  text. Commit atomically.

DELETE strategy:
  Verify case and update exist (404 otherwise). Check actor_uid == author_id OR
  actor_role in {admin_staff, senior_partner, system_admin} (403 otherwise).
  Hard-delete the document.
"""

import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException, status
from google.cloud import firestore

logger = logging.getLogger(__name__)

_DELETE_PRIVILEGED_ROLES = {"admin_staff", "senior_partner", "system_admin"}


def _normalise_ts(ts) -> Optional[datetime]:
    """Return an aware datetime from a Firestore Timestamp or datetime, or None."""
    if ts is None:
        return None
    if hasattr(ts, "tzinfo") and ts.tzinfo is None:
        return ts.replace(tzinfo=timezone.utc)
    return ts


def _materialise(doc) -> dict:
    data = doc.to_dict() or {}
    edit_history_raw = data.get("editHistory") or []
    edit_history = []
    for entry in edit_history_raw:
        edit_history.append({
            "text":      entry.get("text", ""),
            "edited_at": _normalise_ts(entry.get("editedAt")),
        })
    return {
        "update_id":    doc.id,
        "case_id":      data.get("caseId", ""),
        "text":         data.get("text", ""),
        "author_id":    data.get("authorId", ""),
        "author_name":  data.get("authorName", ""),
        "author_role":  data.get("authorRole", ""),
        "created_at":   _normalise_ts(data.get("createdAt")),
        "updated_at":   _normalise_ts(data.get("updatedAt")),
        "is_edited":    data.get("isEdited", False),
        "original_text": data.get("originalText"),
        "edit_history": edit_history,
    }


def _get_author_name(db: firestore.Client, uid: str) -> str:
    """Look up staff/{uid}.displayName; fall back to uid if document absent."""
    try:
        snap = db.collection("staff").document(uid).get()
        if snap.exists:
            return (snap.to_dict() or {}).get("displayName") or uid
    except Exception:
        pass
    return uid


# ---------------------------------------------------------------------------
# list
# ---------------------------------------------------------------------------

def list_updates(
    db: firestore.Client,
    case_id: str,
    page: int,
    page_size: int,
) -> dict:
    case_ref = db.collection("cases").document(case_id)
    if not case_ref.get().exists:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Case '{case_id}' not found.",
        )

    docs = list(case_ref.collection("updates").stream())
    logger.info("Retrieved %d updates for case %s", len(docs), case_id)

    entries = [_materialise(doc) for doc in docs]

    # Sort newest first in Python
    entries.sort(
        key=lambda e: e["created_at"].timestamp() if e["created_at"] else 0.0,
        reverse=True,
    )

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


# ---------------------------------------------------------------------------
# create
# ---------------------------------------------------------------------------

def create_update(
    db: firestore.Client,
    case_id: str,
    actor_uid: str,
    actor_role: str,
    text: str,
) -> dict:
    case_ref  = db.collection("cases").document(case_id)
    case_snap = case_ref.get()
    if not case_snap.exists:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Case '{case_id}' not found.",
        )

    author_name = _get_author_name(db, actor_uid)
    now         = datetime.now(tz=timezone.utc)
    update_id   = str(uuid.uuid4())

    doc_data = {
        "updateId":    update_id,
        "caseId":      case_id,
        "text":        text,
        "authorId":    actor_uid,
        "authorName":  author_name,
        "authorRole":  actor_role,
        "createdAt":   now,
        "updatedAt":   now,
        "isEdited":    False,
        "originalText": None,
        "editHistory": [],
    }

    update_ref   = case_ref.collection("updates").document(update_id)
    timeline_ref = case_ref.collection("timeline").document()

    batch = db.batch()
    batch.set(update_ref, doc_data)
    batch.set(timeline_ref, {
        "eventType":   "CaseUpdate",
        "description": "Case update posted",
        "performedBy": actor_uid,
        "timestamp":   now,
    })
    batch.update(case_ref, {"updatedAt": now})
    batch.commit()

    logger.info("Update %s created on case %s by %s", update_id, case_id, actor_uid)

    return {
        "update_id":    update_id,
        "case_id":      case_id,
        "text":         text,
        "author_id":    actor_uid,
        "author_name":  author_name,
        "author_role":  actor_role,
        "created_at":   now,
        "updated_at":   now,
        "is_edited":    False,
        "original_text": None,
        "edit_history": [],
    }


# ---------------------------------------------------------------------------
# edit
# ---------------------------------------------------------------------------

def edit_update(
    db: firestore.Client,
    case_id: str,
    update_id: str,
    actor_uid: str,
    new_text: str,
) -> dict:
    case_ref = db.collection("cases").document(case_id)
    if not case_ref.get().exists:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Case '{case_id}' not found.",
        )

    update_ref  = case_ref.collection("updates").document(update_id)
    update_snap = update_ref.get()
    if not update_snap.exists:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Update '{update_id}' not found.",
        )

    data      = update_snap.to_dict() or {}
    author_id = data.get("authorId", "")

    if actor_uid != author_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the author can edit this update.",
        )

    now          = datetime.now(tz=timezone.utc)
    current_text = data.get("text", "")
    is_edited    = data.get("isEdited", False)

    # Build the edit history entry for the version being replaced
    new_history_entry = {"text": current_text, "editedAt": now}

    existing_history = data.get("editHistory") or []

    if not is_edited:
        # First edit: set originalText to the creation-time text
        original_text = current_text
    else:
        original_text = data.get("originalText")

    batch_update_fields = {
        "text":        new_text,
        "updatedAt":   now,
        "isEdited":    True,
        "originalText": original_text,
        "editHistory": existing_history + [new_history_entry],
    }

    batch = db.batch()
    batch.update(update_ref, batch_update_fields)
    batch.commit()

    logger.info("Update %s edited on case %s by %s", update_id, case_id, actor_uid)

    edit_history_out = [
        {"text": e.get("text", ""), "edited_at": _normalise_ts(e.get("editedAt"))}
        for e in existing_history + [new_history_entry]
    ]

    return {
        "update_id":    update_id,
        "case_id":      case_id,
        "text":         new_text,
        "author_id":    author_id,
        "author_name":  data.get("authorName", ""),
        "author_role":  data.get("authorRole", ""),
        "created_at":   _normalise_ts(data.get("createdAt")),
        "updated_at":   now,
        "is_edited":    True,
        "original_text": original_text,
        "edit_history": edit_history_out,
    }


# ---------------------------------------------------------------------------
# delete
# ---------------------------------------------------------------------------

def delete_update(
    db: firestore.Client,
    case_id: str,
    update_id: str,
    actor_uid: str,
    actor_role: str,
) -> dict:
    case_ref = db.collection("cases").document(case_id)
    if not case_ref.get().exists:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Case '{case_id}' not found.",
        )

    update_ref  = case_ref.collection("updates").document(update_id)
    update_snap = update_ref.get()
    if not update_snap.exists:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Update '{update_id}' not found.",
        )

    author_id = (update_snap.to_dict() or {}).get("authorId", "")
    is_author  = actor_uid == author_id
    is_privileged = actor_role in _DELETE_PRIVILEGED_ROLES

    if not is_author and not is_privileged:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the author, admin staff, or senior partners can delete this update.",
        )

    update_ref.delete()
    logger.info("Update %s deleted from case %s by %s", update_id, case_id, actor_uid)

    return {"update_id": update_id, "deleted": True}
