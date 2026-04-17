# Endpoints defined in this module:
#   POST /api/v1/cases/{caseId}/reject    — reject case from attorney review  (min: junior_partner)
#   POST /api/v1/cases/{caseId}/resubmit  — resubmit rejected case            (min: paralegal)

from fastapi import APIRouter, Depends, Path

from app.models.rejection import (
    RejectCaseRequest,
    RejectCaseResponse,
    ResubmitCaseRequest,
    ResubmitCaseResponse,
)
from app.services.rejection_service import reject_case, resubmit_case
from app.utils.auth import require_min_role
from app.utils.firestore import get_firestore_client
from app.utils.roles import normalize_role

router = APIRouter(prefix="/api/v1", tags=["Rejection"])


@router.post(
    "/cases/{caseId}/reject",
    response_model=RejectCaseResponse,
    summary=(
        "Reject a case from Pending Attorney Review — captures reason and notifies paralegal"
    ),
    status_code=200,
)
def post_reject_case(
    body: RejectCaseRequest,
    caseId: str = Path(..., description="Case ID (e.g. ZAD-2024-01-0001)"),
    user: dict = Depends(require_min_role("case_reject")),
):
    db     = get_firestore_client()
    result = reject_case(
        db=db,
        case_id=caseId,
        actor_uid=user["uid"],
        actor_role=normalize_role(user.get("role", "")),
        reason=body.reason,
        notes=body.notes,
    )
    return RejectCaseResponse(**result)


@router.post(
    "/cases/{caseId}/resubmit",
    response_model=ResubmitCaseResponse,
    summary="Resubmit a rejected case back to Pending Paralegal Review",
    status_code=200,
)
def post_resubmit_case(
    body: ResubmitCaseRequest,
    caseId: str = Path(..., description="Case ID (e.g. ZAD-2024-01-0001)"),
    user: dict = Depends(require_min_role("case_resubmit")),
):
    db     = get_firestore_client()
    result = resubmit_case(
        db=db,
        case_id=caseId,
        actor_uid=user["uid"],
        actor_role=normalize_role(user.get("role", "")),
        notes=body.notes,
    )
    return ResubmitCaseResponse(**result)
