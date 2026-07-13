# Endpoints defined in this module:
#   PATCH /api/v1/cases/{caseId}/status   — manually set case status to any value (min: cases.status.update)

from fastapi import APIRouter, Path, Request

from app.models.status_update import StatusUpdateRequest, StatusUpdateResponse
from app.services.status_update_service import update_case_status
from app.utils.firestore import get_firestore_client

router = APIRouter(prefix="/api/v1", tags=["Case Status"])


def _get_actor(request: Request) -> tuple[str, str]:
    user       = getattr(request.state, "user", None) or {}
    actor_uid  = user.get("uid", "system")
    actor_role = user.get("role", "admin_staff")
    return actor_uid, actor_role


@router.patch(
    "/cases/{caseId}/status",
    response_model=StatusUpdateResponse,
    summary="Manually update a case's status to any value",
)
def patch_case_status(
    body:   StatusUpdateRequest,
    request: Request,
    caseId: str = Path(..., description="Case ID (e.g. ZAD-2024-01-0001)"),
):
    db = get_firestore_client()
    actor_uid, _ = _get_actor(request)

    actor_snap = db.collection("staff").document(actor_uid).get()
    actor_name = (actor_snap.to_dict() or {}).get("displayName") if actor_snap.exists else None

    result = update_case_status(
        db=db,
        case_id=caseId,
        new_status=body.status,
        actor_uid=actor_uid,
        actor_name=actor_name,
        notes=body.notes,
    )
    return StatusUpdateResponse(**result)
