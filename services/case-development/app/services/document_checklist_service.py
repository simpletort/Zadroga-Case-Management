import logging

from google.cloud import firestore

logger = logging.getLogger(__name__)

_COLLECTION = "firmSettings"
_DOC_ID     = "document_checklists"

# Defaults applied when firmSettings/document_checklists has not been configured
# yet, or is missing the "default" key.
_DEFAULTS = {
    "default": ["medical-records", "proof-of-presence", "id-documents"],
}


def _ref(db: firestore.Client):
    return db.collection(_COLLECTION).document(_DOC_ID)


def get_required_document_categories(db: firestore.Client, case_type: str | None) -> list[str]:
    """
    Resolve the required document categories for a case.

    Resolution order: case_type override -> default.
    Reads firmSettings/document_checklists fresh on every call (no caching).
    """
    snap = _ref(db).get()
    data = snap.to_dict() or {} if snap.exists else {}

    default = data.get("default") or _DEFAULTS["default"]
    overrides = data.get("overrides") or {}

    if case_type and case_type in overrides:
        return overrides[case_type]
    return default
