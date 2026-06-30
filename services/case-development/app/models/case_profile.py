from __future__ import annotations

from typing import Any

from pydantic import BaseModel, model_validator


# Fields the caller is NOT allowed to include in a PATCH body.
DISALLOWED_FIELDS: frozenset[str] = frozenset({"status", "case_id", "created_at"})

# Only these top-level case fields may be modified via PATCH /cases/{caseId}.
ALLOWED_FIELDS: frozenset[str] = frozenset(
    {"phone", "email", "address", "notes", "assigned_attorney"}
)


class CasePatchRequest(BaseModel):
    phone: str | None = None
    email: str | None = None
    address: str | None = None
    notes: str | None = None
    assigned_attorney: str | None = None

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
