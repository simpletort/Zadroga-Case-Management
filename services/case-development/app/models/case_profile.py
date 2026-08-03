from __future__ import annotations

from datetime import date
from typing import Any

from pydantic import BaseModel, model_validator


# Fields the caller is NOT allowed to include in a PATCH body. Hardcoded and never
# configurable via firmSettings — see app/services/case_profile_fields_service.py,
# which can only toggle fields within FIELD_CATALOG below, never add to it.
DISALLOWED_FIELDS: frozenset[str] = frozenset({"status", "case_id", "created_at"})

# The fixed catalog of fields that CAN be made editable via PATCH /cases/{caseId}.
# firmSettings/case_profile_editable_fields (case_profile_fields_service.py) controls
# which subset is CURRENTLY enabled — it validates against this catalog and can never
# introduce a field outside it. Fields owned by other endpoints (assigned_paralegal,
# status, etc.) are absent from this catalog on purpose and so can never be enabled.
#
# firestore_path: dot-path on the cases document ("address" is expanded to per-subfield
#   dot-paths separately — see case_profile_service.py — so it has no single path here).
# phi: whether the field is claimant PHI, for the audit_logs.phiAccessed flag.
FIELD_CATALOG: dict[str, dict[str, Any]] = {
    "phone":               {"firestore_path": "phone",                        "phi": True},
    "email":               {"firestore_path": "email",                        "phi": True},
    "address":             {"firestore_path": None,                           "phi": True},
    "notes":               {"firestore_path": "notes",                        "phi": False},
    "assigned_attorney":   {"firestore_path": "assignment.assignedAttorney",  "phi": False},
    "first_name":          {"firestore_path": "firstName",                    "phi": True},
    "last_name":           {"firestore_path": "lastName",                     "phi": True},
    "date_of_birth":       {"firestore_path": "dateOfBirth",                  "phi": True},
    "exposure_location":   {"firestore_path": "exposureLocation",             "phi": True},
    "exposure_date_start": {"firestore_path": "exposureDateStart",            "phi": True},
    "exposure_date_end":   {"firestore_path": "exposureDateEnd",              "phi": True},
    "conditions":          {"firestore_path": "conditions",                   "phi": True},
    "prior_attorney":          {"firestore_path": "priorAttorney",            "phi": True},
    "questionnaire_complete":  {"firestore_path": "questionnaireComplete",    "phi": False},
}

# Only these top-level case fields may be modified via PATCH /cases/{caseId}.
ALLOWED_FIELDS: frozenset[str] = frozenset(FIELD_CATALOG.keys())


class AddressPatch(BaseModel):
    """Partial address update — only provided sub-fields are written."""
    street: str | None = None
    city: str | None = None
    state: str | None = None
    zip: str | None = None


class CasePatchRequest(BaseModel):
    phone: str | None = None
    email: str | None = None
    address: AddressPatch | None = None
    notes: str | None = None
    assigned_attorney: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    date_of_birth: date | None = None
    exposure_location: str | None = None
    exposure_date_start: date | None = None
    exposure_date_end: date | None = None
    conditions: list[str] | None = None
    prior_attorney: bool | None = None
    questionnaire_complete: bool | None = None

    model_config = {"extra": "allow"}

    @model_validator(mode="before")
    @classmethod
    def reject_disallowed_fields(cls, values: Any) -> Any:
        if not isinstance(values, dict):
            return values
        bad = DISALLOWED_FIELDS & values.keys()
        if bad:
            raise ValueError(
                "The following fields cannot be modified: {}".format(", ".join(sorted(bad)))
            )
        return values

    def changed_fields(self) -> dict[str, Any]:
        """Return only the explicitly-set allowed fields (excludes None-defaulted ones)."""
        set_fields = self.model_fields_set & ALLOWED_FIELDS
        return {k: getattr(self, k) for k in set_fields}


class CasePatchResponse(BaseModel):
    case_id: str
    updated_fields: list[str]
    audit_log_id: str
