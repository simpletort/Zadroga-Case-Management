"""
Case Profile Editable-Fields Config Service  [AMBER ZONE — developer must review and edit meaningfully]

Controls which fields in the case-profile-patch catalog
(app/models/case_profile.py:FIELD_CATALOG) are currently enabled for
PATCH /api/v1/cases/{caseId}.

Safety invariant: this can only toggle fields already present in FIELD_CATALOG.
It can never introduce a new field name, and can never enable status/case_id/
created_at (hardcoded DISALLOWED_FIELDS) or fields owned by other endpoints
(e.g. assigned_paralegal, which belongs to POST /cases/{caseId}/assign) —
those simply aren't in the catalog, so there is nothing to enable.

Firestore path: firmSettings/case_profile_editable_fields
  { enabledFields: [...], updatedAt, updatedBy }

Default when the doc is missing or has no enabledFields key: every catalog field
is enabled. This makes the feature opt-in-to-restrict, matching pre-config
behaviour, rather than opt-in-to-unlock (which would silently disable every
field on a fresh deploy until an admin configures the doc).
"""

import logging
from datetime import datetime, timezone

from fastapi import HTTPException, status
from google.cloud import firestore

from app.models.case_profile import ALLOWED_FIELDS, FIELD_CATALOG

logger = logging.getLogger(__name__)

_COLLECTION = "firmSettings"
_DOC_ID     = "case_profile_editable_fields"


def _ref(db: firestore.Client):
    return db.collection(_COLLECTION).document(_DOC_ID)


def get_editable_fields(db: firestore.Client) -> dict:
    """Read firmSettings/case_profile_editable_fields, describing every catalog
    field and whether it's currently enabled."""
    snap = _ref(db).get()
    data = snap.to_dict() or {} if snap.exists else {}

    enabled_raw = data.get("enabledFields")
    enabled = set(enabled_raw) if enabled_raw is not None else set(ALLOWED_FIELDS)
    # Defence in depth: a stale or hand-edited Firestore doc can never enable a
    # field outside the fixed catalog, even if it lists one.
    enabled &= ALLOWED_FIELDS

    return {
        "fields": [
            {
                "field":   field,
                "enabled": field in enabled,
                "phi":     FIELD_CATALOG[field]["phi"],
            }
            for field in sorted(ALLOWED_FIELDS)
        ],
        "updated_at": data.get("updatedAt"),
        "updated_by": data.get("updatedBy"),
    }


def get_enabled_field_set(db: firestore.Client) -> frozenset[str]:
    """Fast path for patch_case — just the currently-enabled field names."""
    result = get_editable_fields(db)
    return frozenset(f["field"] for f in result["fields"] if f["enabled"])


def update_editable_fields(
    db: firestore.Client,
    enabled_fields: list[str],
    actor_uid: str,
) -> dict:
    """Replace the enabled-field set. Rejects any field outside FIELD_CATALOG."""
    unknown = set(enabled_fields) - ALLOWED_FIELDS
    if unknown:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unknown field(s), not in the editable-field catalog: {}".format(
                ", ".join(sorted(unknown))
            ),
        )

    now = datetime.now(tz=timezone.utc)
    _ref(db).set({
        "enabledFields": sorted(set(enabled_fields)),
        "updatedAt":     now,
        "updatedBy":     actor_uid,
    }, merge=True)

    logger.info(
        "case_profile_editable_fields updated: enabled=%s by=%s",
        sorted(set(enabled_fields)), actor_uid,
    )

    return get_editable_fields(db)
