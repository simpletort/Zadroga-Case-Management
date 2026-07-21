# Endpoints defined in this module:
#   GET   /api/v1/settings/case-profile-editable-fields   — list the field catalog and
#                                                            which fields are enabled
#                                                            (min: junior_partner — settings.read)
#   PATCH /api/v1/settings/case-profile-editable-fields   — set which catalog fields are
#                                                            enabled (min: senior_partner /
#                                                            system_admin — settings.write)
#
# Only toggles fields within the fixed catalog (app/models/case_profile.py:FIELD_CATALOG).
# Cannot add new field names, and can never enable status/case_id/created_at or fields
# owned by other endpoints (e.g. assigned_paralegal) — those aren't in the catalog.

from fastapi import APIRouter, Request

from app.models.case_profile_fields import (
    CaseProfileEditableFieldsResponse,
    EditableFieldDescriptor,
    UpdateCaseProfileEditableFieldsRequest,
)
from app.services.case_profile_fields_service import get_editable_fields, update_editable_fields
from app.utils.firestore import get_firestore_client

router = APIRouter(prefix="/api/v1", tags=["Case Profile Field Config"])


def _get_actor_uid(request: Request) -> str:
    user = getattr(request.state, "user", None) or {}
    return user.get("uid", "system")


@router.get(
    "/settings/case-profile-editable-fields",
    response_model=CaseProfileEditableFieldsResponse,
    summary="List the case-profile field catalog and which fields are currently editable",
)
def get_case_profile_editable_fields_route(request: Request):
    db     = get_firestore_client()
    result = get_editable_fields(db)
    return CaseProfileEditableFieldsResponse(
        fields=[EditableFieldDescriptor(**f) for f in result["fields"]],
        updated_at=result["updated_at"],
        updated_by=result["updated_by"],
    )


@router.patch(
    "/settings/case-profile-editable-fields",
    response_model=CaseProfileEditableFieldsResponse,
    summary="Set which case-profile fields are currently editable (admin only)",
)
def patch_case_profile_editable_fields_route(
    body: UpdateCaseProfileEditableFieldsRequest,
    request: Request,
):
    db        = get_firestore_client()
    actor_uid = _get_actor_uid(request)
    result    = update_editable_fields(
        db=db, enabled_fields=body.enabled_fields, actor_uid=actor_uid,
    )
    return CaseProfileEditableFieldsResponse(
        fields=[EditableFieldDescriptor(**f) for f in result["fields"]],
        updated_at=result["updated_at"],
        updated_by=result["updated_by"],
    )
