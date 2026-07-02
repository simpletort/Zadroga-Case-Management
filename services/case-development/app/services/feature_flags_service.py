import logging
from datetime import datetime, timezone

from google.cloud import firestore

logger = logging.getLogger(__name__)

_COLLECTION = "firmSettings"
_DOC_ID     = "feature_flags"

# Defaults applied when firmSettings/feature_flags has not been configured yet,
# or is missing a given key.
_DEFAULTS = {
    "require_ai_summary": True,
}


def _ref(db: firestore.Client):
    return db.collection(_COLLECTION).document(_DOC_ID)


def get_feature_flags(db: firestore.Client) -> dict:
    """Read firmSettings/feature_flags, falling back to defaults for missing keys."""
    snap = _ref(db).get()
    data = snap.to_dict() or {} if snap.exists else {}

    return {
        "require_ai_summary": bool(data.get("require_ai_summary", _DEFAULTS["require_ai_summary"])),
        "updated_at":         data.get("updatedAt"),
        "updated_by":         data.get("updatedBy"),
    }


def update_feature_flags(
    db:        firestore.Client,
    fields:    dict,
    actor_uid: str,
) -> dict:
    """Merge the given fields into firmSettings/feature_flags and return the resulting flags."""
    now = datetime.now(tz=timezone.utc)

    _ref(db).set({
        **fields,
        "updatedAt": now,
        "updatedBy": actor_uid,
    }, merge=True)

    logger.info("feature_flags updated: fields=%s by=%s", list(fields.keys()), actor_uid)

    current = get_feature_flags(db)
    current["updated_at"] = now
    current["updated_by"] = actor_uid
    return current
