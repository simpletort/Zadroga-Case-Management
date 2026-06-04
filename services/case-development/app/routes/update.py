# Endpoints defined in this module:
#   GET    /api/v1/cases/{caseId}/updates                   — paginated update list (all roles)
#                                                              ?page=       page number (default: 1)
#                                                              ?page_size=  items per page (default: 20, max: 100)
#   POST   /api/v1/cases/{caseId}/updates                   — create a new update (all roles)
#   PATCH  /api/v1/cases/{caseId}/updates/{updateId}        — edit own update (author only)
#   DELETE /api/v1/cases/{caseId}/updates/{updateId}        — delete update (author, admin_staff, senior_partner)

from fastapi import APIRouter, Path, Query, Request

from app.models.update import (
    CaseUpdateListResponse,
    CaseUpdateResponse,
    CreateUpdateRequest,
    DeleteUpdateResponse,
    EditUpdateRequest,
)
from app.services.update_service import (
    create_update,
    delete_update,
    edit_update,
    list_updates,
)
from app.utils.firestore import get_firestore_client

router = APIRouter(prefix="/api/v1", tags=["Case Updates"])


def _get_actor(request: Request) -> tuple[str, str]:
    """Extract (uid, role) from request.state.user; fall back to system defaults in tests."""
    user      = getattr(request.state, "user", None) or {}
    actor_uid  = user.get("uid", "system")
    actor_role = user.get("role", "admin_staff")
    return actor_uid, actor_role


@router.get(
    "/cases/{caseId}/updates",
    response_model=CaseUpdateListResponse,
    summary="List case updates, newest first",
)
def get_updates(
    request: Request,
    caseId: str = Path(..., description="Case ID (e.g. ZAD-2024-01-0001)"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
):
    db     = get_firestore_client()
    result = list_updates(db=db, case_id=caseId, page=page, page_size=page_size)
    return CaseUpdateListResponse(
        items=[CaseUpdateResponse(**item) for item in result["items"]],
        total=result["total"],
        page=result["page"],
        page_size=result["page_size"],
        total_pages=result["total_pages"],
    )


@router.post(
    "/cases/{caseId}/updates",
    response_model=CaseUpdateResponse,
    status_code=201,
    summary="Post a new text update on a case",
)
def post_update(
    body: CreateUpdateRequest,
    request: Request,
    caseId: str = Path(..., description="Case ID (e.g. ZAD-2024-01-0001)"),
):
    db               = get_firestore_client()
    actor_uid, actor_role = _get_actor(request)
    result = create_update(
        db=db,
        case_id=caseId,
        actor_uid=actor_uid,
        actor_role=actor_role,
        text=body.text,
    )
    return CaseUpdateResponse(**result)


@router.patch(
    "/cases/{caseId}/updates/{updateId}",
    response_model=CaseUpdateResponse,
    summary="Edit an existing case update (author only)",
)
def patch_update(
    body: EditUpdateRequest,
    request: Request,
    caseId: str = Path(..., description="Case ID (e.g. ZAD-2024-01-0001)"),
    updateId: str = Path(..., description="Update document ID"),
):
    db               = get_firestore_client()
    actor_uid, _     = _get_actor(request)
    result = edit_update(
        db=db,
        case_id=caseId,
        update_id=updateId,
        actor_uid=actor_uid,
        new_text=body.text,
    )
    return CaseUpdateResponse(**result)


@router.delete(
    "/cases/{caseId}/updates/{updateId}",
    response_model=DeleteUpdateResponse,
    summary="Delete a case update (author, admin_staff, or senior_partner)",
)
def delete_update_route(
    request: Request,
    caseId: str = Path(..., description="Case ID (e.g. ZAD-2024-01-0001)"),
    updateId: str = Path(..., description="Update document ID"),
):
    db               = get_firestore_client()
    actor_uid, actor_role = _get_actor(request)
    result = delete_update(
        db=db,
        case_id=caseId,
        update_id=updateId,
        actor_uid=actor_uid,
        actor_role=actor_role,
    )
    return DeleteUpdateResponse(**result)
