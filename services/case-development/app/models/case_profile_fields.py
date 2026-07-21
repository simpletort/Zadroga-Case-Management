from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class EditableFieldDescriptor(BaseModel):
    field: str
    enabled: bool
    phi: bool


class CaseProfileEditableFieldsResponse(BaseModel):
    fields: list[EditableFieldDescriptor]
    updated_at: Optional[datetime] = None
    updated_by: Optional[str]      = None


class UpdateCaseProfileEditableFieldsRequest(BaseModel):
    """enabled_fields must be a subset of app.models.case_profile.ALLOWED_FIELDS —
    validated in the service layer against the fixed catalog, not here, so the
    error message can list the exact unknown field names."""
    enabled_fields: list[str]
