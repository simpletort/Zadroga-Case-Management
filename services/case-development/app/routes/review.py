# Endpoints defined in this module:
#   GET  /api/v1/cases/{caseId}/review-preflight    — check submission readiness (min: paralegal)
#   POST /api/v1/cases/{caseId}/submit-for-review   — submit case for attorney review (min: paralegal)

from fastapi import APIRouter, Depends, Path

from app.models.review import PreflightCheck, PreflightResponse, SubmitForReviewResponse
from app.services.review_service import run_preflight, submit_for_review
from app.utils.auth import require_min_role
from app.utils.firestore import get_firestore_client

router = APIRouter(prefix="/api/v1", tags=["Review"])


@router.get(
    "/cases/{caseId}/review-preflight",
    response_model=PreflightResponse,
    summary="Check whether a case is ready to be submitted for attorney review",
)
def get_review_preflight(
    caseId: str = Path(..., description="Case ID (e.g. ZAD-2024-01-0001)"),
    _user: dict = Depends(require_min_role("review_preflight")),
):
    db     = get_firestore_client()
    result = run_preflight(db=db, case_id=caseId)
    return PreflightResponse(
        case_id=caseId,
        all_passed=result["all_passed"],
        checks=[PreflightCheck(**c) for c in result["checks"]],
    )


@router.post(
    "/cases/{caseId}/submit-for-review",
    response_model=SubmitForReviewResponse,
    summary="Submit a case for attorney review (blocked if pre-flight checks fail)",
    status_code=200,
)
def post_submit_for_review(
    caseId: str = Path(..., description="Case ID (e.g. ZAD-2024-01-0001)"),
    user: dict = Depends(require_min_role("review_submit")),
):
    db     = get_firestore_client()
    result = submit_for_review(db=db, case_id=caseId, actor_uid=user["uid"])
    return SubmitForReviewResponse(**result)
