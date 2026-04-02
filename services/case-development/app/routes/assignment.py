# Endpoints defined in this module:
#   POST /api/v1/cases/{caseId}/assign          — manually assign / re-assign a case (min: admin_staff)
#   GET  /api/v1/cases/{caseId}/assignment      — get current assignment for a case (min: paralegal)
#   GET  /api/v1/staff/paralegals/workload      — view workload distribution across all paralegals (min: paralegal)

from fastapi import APIRouter, Depends, Path

from app.models.assignment import AssignRequest, AssignmentResponse, AssignmentInfo, WorkloadResponse, WorkloadEntry
from app.services.assignment_service import get_assignment_info, manual_assign, get_workload
from app.utils.auth import require_min_role
from app.utils.firestore import get_firestore_client

router = APIRouter(prefix="/api/v1", tags=["Assignment"])


@router.post(
    "/cases/{caseId}/assign",
    response_model=AssignmentResponse,
    summary="Manually assign or re-assign a case to a paralegal",
)
def override_assignment(
    body: AssignRequest,
    caseId: str = Path(..., description="Case ID (e.g. ZAD-2024-01-0001)"),
    user: dict = Depends(require_min_role("case_assign_override")),
):
    db     = get_firestore_client()
    result = manual_assign(
        db=db,
        case_id=caseId,
        new_paralegal_id=body.paralegal_id,
        actor_uid=user["uid"],
        reason=body.reason,
    )
    return AssignmentResponse(
        case_id=caseId,
        assignment=AssignmentInfo(
            assigned_paralegal=result["assigned_paralegal"],
            assigned_paralegal_name=result["assigned_paralegal_name"],
            assignment_date=result["assignment_date"],
        ),
        overridden_from=result.get("overridden_from"),
    )


@router.get(
    "/cases/{caseId}/assignment",
    response_model=AssignmentResponse,
    summary="Get the current assignment for a case",
)
def read_assignment(
    caseId: str = Path(..., description="Case ID (e.g. ZAD-2024-01-0001)"),
    _user: dict = Depends(require_min_role("case_assignment_read")),
):
    db     = get_firestore_client()
    result = get_assignment_info(db=db, case_id=caseId)
    return AssignmentResponse(
        case_id=caseId,
        assignment=AssignmentInfo(
            assigned_paralegal=result["assigned_paralegal"],
            assigned_paralegal_name=result["assigned_paralegal_name"],
            assignment_date=result["assignment_date"],
        ),
    )


@router.get(
    "/staff/paralegals/workload",
    response_model=WorkloadResponse,
    summary="View workload distribution across all paralegals",
)
def read_workload(
    _user: dict = Depends(require_min_role("workload_view")),
):
    db      = get_firestore_client()
    entries = get_workload(db=db)
    return WorkloadResponse(
        paralegals=[WorkloadEntry(**e) for e in entries]
    )
