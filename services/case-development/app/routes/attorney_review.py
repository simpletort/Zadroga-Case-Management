# Endpoints defined in this module:
#   GET  /api/v1/attorney/review-queue             — paginated review queue (min: junior_partner)
#   POST /api/v1/cases/{caseId}/approve-for-filing — approve single case   (min: junior_partner)
#   POST /api/v1/cases/bulk-approve                — bulk approve cases    (min: junior_partner)

from fastapi import APIRouter, Path, Query

from app.models.attorney_review import (
    ApproveForFilingRequest,
    ApproveForFilingResponse,
    BulkApproveRequest,
    BulkApproveResponse,
    ReviewQueueItem,
    ReviewQueuePage,
    ReviewQueueResponse,
)
from app.services.attorney_review_service import (
    approve_for_filing,
    bulk_approve_for_filing,
    get_review_queue,
)
from app.utils.firestore import get_firestore_client

router = APIRouter(prefix="/api/v1", tags=["Attorney Review"])


@router.get(
    "/attorney/review-queue",
    response_model=ReviewQueueResponse,
    summary="Return the attorney's prioritised review queue (sorted by deadline, submission date, qual score)",
)
def get_attorney_review_queue(
    page: int = Query(default=1, ge=1, description="Page number"),
    page_size: int = Query(default=20, ge=1, le=100, description="Items per page"),
):
    db     = get_firestore_client()
    result = get_review_queue(db=db, page=page, page_size=page_size)

    page_data = result["page"]
    return ReviewQueueResponse(
        total_pending=result["total_pending"],
        overdue_count=result["overdue_count"],
        page=ReviewQueuePage(
            items=[ReviewQueueItem(**item) for item in page_data["items"]],
            total=page_data["total"],
            page=page_data["page"],
            page_size=page_data["page_size"],
            total_pages=page_data["total_pages"],
        ),
    )


@router.post(
    "/cases/{caseId}/approve-for-filing",
    response_model=ApproveForFilingResponse,
    summary="Approve a case for filing — creates filing-prep tasks and notifies the paralegal",
    status_code=200,
)
def post_approve_for_filing(
    body: ApproveForFilingRequest,
    caseId: str = Path(..., description="Case ID (e.g. ZAD-2024-01-0001)"),
):
    db     = get_firestore_client()
    result = approve_for_filing(
        db=db,
        case_id=caseId,
        actor_uid="system",
        actor_role="system_admin",
        notes=body.notes,
    )
    return ApproveForFilingResponse(**result)


@router.post(
    "/cases/bulk-approve",
    response_model=BulkApproveResponse,
    summary="Bulk approve multiple cases for filing — errors captured per case",
    status_code=200,
)
def post_bulk_approve(
    body: BulkApproveRequest,
):
    db     = get_firestore_client()
    result = bulk_approve_for_filing(
        db=db,
        case_ids=body.case_ids,
        actor_uid="system",
        actor_role="system_admin",
        notes=body.notes,
    )
    return BulkApproveResponse(**result)
