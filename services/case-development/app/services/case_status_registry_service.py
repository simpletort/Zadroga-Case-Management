import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException
from google.cloud import firestore

logger = logging.getLogger(__name__)

_COLLECTION = "firmSettings"
_DOC_ID     = "case_statuses"


def _ref(db: firestore.Client):
    return db.collection(_COLLECTION).document(_DOC_ID)


def _read(db: firestore.Client) -> tuple[list[dict], dict]:
    """Return (statuses_list, raw_doc_dict). Handles missing doc gracefully."""
    snap = _ref(db).get()
    if not snap.exists:
        return [], {}
    data = snap.to_dict() or {}
    return data.get("statuses", []), data


def get_statuses(db: firestore.Client) -> dict:
    statuses, data = _read(db)
    return {
        "statuses":   statuses,
        "updated_at": data.get("updatedAt"),
        "updated_by": data.get("updatedBy"),
    }


def create_status(
    db:        firestore.Client,
    entry:     dict,
    actor_uid: str,
) -> dict:
    statuses, _ = _read(db)

    if any(s["value"] == entry["value"] for s in statuses):
        raise HTTPException(
            status_code=409,
            detail="Status '{}' already exists.".format(entry["value"]),
        )

    statuses.append(entry)
    now = datetime.now(tz=timezone.utc)

    _ref(db).set({
        "statuses":  statuses,
        "updatedAt": now,
        "updatedBy": actor_uid,
    })

    logger.info("case_status created: value=%s by=%s", entry["value"], actor_uid)
    return {"statuses": statuses, "updated_at": now, "updated_by": actor_uid}


def update_status(
    db:        firestore.Client,
    value:     str,
    fields:    dict,
    actor_uid: str,
) -> dict:
    statuses, _ = _read(db)

    idx = next((i for i, s in enumerate(statuses) if s["value"] == value), None)
    if idx is None:
        raise HTTPException(
            status_code=404,
            detail="Status '{}' not found.".format(value),
        )

    statuses[idx] = {**statuses[idx], **fields}
    now = datetime.now(tz=timezone.utc)

    _ref(db).set({
        "statuses":  statuses,
        "updatedAt": now,
        "updatedBy": actor_uid,
    })

    logger.info("case_status updated: value=%s fields=%s by=%s", value, list(fields.keys()), actor_uid)
    return {"statuses": statuses, "updated_at": now, "updated_by": actor_uid}


def delete_status(
    db:        firestore.Client,
    value:     str,
    actor_uid: str,
) -> dict:
    statuses, _ = _read(db)

    if not any(s["value"] == value for s in statuses):
        raise HTTPException(
            status_code=404,
            detail="Status '{}' not found.".format(value),
        )

    statuses = [s for s in statuses if s["value"] != value]
    now = datetime.now(tz=timezone.utc)

    _ref(db).set({
        "statuses":  statuses,
        "updatedAt": now,
        "updatedBy": actor_uid,
    })

    logger.info("case_status deleted: value=%s by=%s", value, actor_uid)
    return {"statuses": statuses, "updated_at": now, "updated_by": actor_uid}
