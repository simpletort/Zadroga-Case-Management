# Endpoints defined in this module:
#   GET    /api/v1/settings/case-statuses           — list all statuses (min: cases.read)
#   POST   /api/v1/settings/case-statuses           — create a new status (min: cases.status.update)
#   PATCH  /api/v1/settings/case-statuses/{value}   — edit a status by value (min: cases.status.update)
#   DELETE /api/v1/settings/case-statuses/{value}   — delete a status by value (min: cases.status.update)
#
# {value} in path must be URL-encoded (e.g. "New Lead" → "New%20Lead").

from fastapi import APIRouter, Path, Request

from app.models.case_status_registry import (
    CaseStatusEntry,
    CaseStatusRegistryResponse,
    CreateCaseStatusRequest,
    UpdateCaseStatusRequest,
)
from app.services.case_status_registry_service import (
    create_status,
    delete_status,
    get_statuses,
    update_status,
)
from app.utils.firestore import get_firestore_client

router = APIRouter(prefix="/api/v1", tags=["Case Status Registry"])


def _get_actor(request: Request) -> tuple[str, str]:
    user       = getattr(request.state, "user", None) or {}
    actor_uid  = user.get("uid", "system")
    actor_role = user.get("role", "admin_staff")
    return actor_uid, actor_role


def _resolve_actor_name(db, actor_uid: str):
    snap = db.collection("staff").document(actor_uid).get()
    return (snap.to_dict() or {}).get("displayName") if snap.exists else None


@router.get(
    "/settings/case-statuses",
    response_model=CaseStatusRegistryResponse,
    summary="List all available case statuses",
)
def list_case_statuses(request: Request):
    db     = get_firestore_client()
    result = get_statuses(db)
    return CaseStatusRegistryResponse(
        statuses=[CaseStatusEntry(**s) for s in result["statuses"]],
        updated_at=result["updated_at"],
        updated_by=result["updated_by"],
    )


@router.post(
    "/settings/case-statuses",
    response_model=CaseStatusRegistryResponse,
    status_code=201,
    summary="Create a new case status",
)
def create_case_status(body: CreateCaseStatusRequest, request: Request):
    db = get_firestore_client()
    actor_uid, _ = _get_actor(request)
    result = create_status(db=db, entry=body.model_dump(), actor_uid=actor_uid)
    return CaseStatusRegistryResponse(
        statuses=[CaseStatusEntry(**s) for s in result["statuses"]],
        updated_at=result["updated_at"],
        updated_by=result["updated_by"],
    )


@router.patch(
    "/settings/case-statuses/{value}",
    response_model=CaseStatusRegistryResponse,
    summary="Edit a case status by its value",
)
def update_case_status(
    body:    UpdateCaseStatusRequest,
    request: Request,
    value:   str = Path(..., description="Status value to edit (URL-encoded)"),
):
    db = get_firestore_client()
    actor_uid, _ = _get_actor(request)
    fields = {k: v for k, v in body.model_dump().items() if v is not None}
    result = update_status(db=db, value=value, fields=fields, actor_uid=actor_uid)
    return CaseStatusRegistryResponse(
        statuses=[CaseStatusEntry(**s) for s in result["statuses"]],
        updated_at=result["updated_at"],
        updated_by=result["updated_by"],
    )


@router.delete(
    "/settings/case-statuses/{value}",
    response_model=CaseStatusRegistryResponse,
    summary="Delete a case status by its value",
)
def delete_case_status(
    request: Request,
    value:   str = Path(..., description="Status value to delete (URL-encoded)"),
):
    db = get_firestore_client()
    actor_uid, _ = _get_actor(request)
    result = delete_status(db=db, value=value, actor_uid=actor_uid)
    return CaseStatusRegistryResponse(
        statuses=[CaseStatusEntry(**s) for s in result["statuses"]],
        updated_at=result["updated_at"],
        updated_by=result["updated_by"],
    )
