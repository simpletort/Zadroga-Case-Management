# Endpoints defined in this module:
#   PATCH /api/v1/cases/{caseId} — update editable case fields (min: paralegal)
#
# Editable fields: phone, email, address, notes, assigned_attorney, first_name, last_name,
#   date_of_birth, exposure_location, exposure_date_start, exposure_date_end, conditions,
#   prior_attorney — see app/models/case_profile.py:ALLOWED_FIELDS.
#
# Disallowed fields (status, case_id, created_at) are rejected with 400 at the
# model-validation layer before the service is called.
# Paralegal role guard: may only edit cases where assignment.assignedParalegal == their uid.

from fastapi import APIRouter, HTTPException, Path, Request, status

from app.models.case_profile import CasePatchRequest, CasePatchResponse, DISALLOWED_FIELDS
from app.services.case_profile_service import patch_case
from app.utils.firestore import get_firestore_client

router = APIRouter(prefix="/api/v1", tags=["Case Profile"])


@router.patch(
    "/cases/{caseId}",
    response_model=CasePatchResponse,
    summary=(
        "Update editable case fields — phone, email, address, notes, assigned_attorney, "
        "first_name, last_name, date_of_birth, exposure_location, exposure_date_start, "
        "exposure_date_end, conditions, prior_attorney"
    ),
    status_code=200,
)
def patch_case_profile(
    body: CasePatchRequest,
    request: Request,
    caseId: str = Path(..., description="Case ID (e.g. ZAD-2024-01-0001)"),
):
    # Pydantic already rejects disallowed fields (status, case_id, created_at) with a
    # ValidationError that FastAPI converts to 422. We re-raise as 400 here to match
    # the spec — but in practice the model_validator raises before we reach this code.
    # (Kept as defence-in-depth in case the model is bypassed in tests via model_construct.)
    extra = DISALLOWED_FIELDS & (body.model_extra or {}).keys()
    if extra:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The following fields cannot be modified: {}".format(", ".join(sorted(extra))),
        )

    changed = body.changed_fields()
    if not changed:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Request body must include at least one editable field.",
        )

    user       = getattr(request.state, "user", None) or {}
    actor_uid  = user.get("uid", "system")
    actor_role = user.get("role", "paralegal")

    db     = get_firestore_client()
    result = patch_case(
        db=db,
        case_id=caseId,
        changed=changed,
        actor_uid=actor_uid,
        actor_role=actor_role,
    )
    return CasePatchResponse(**result)
