# Endpoints defined in this module:
#   POST /api/v1/cases/{caseId}/escalate            — escalate to senior review  (min: junior_partner)
#   GET  /api/v1/attorney/escalation-queue           — senior partner queue       (min: senior_partner)
#   POST /api/v1/cases/{caseId}/escalation-decision  — approve / reject / return  (min: senior_partner)

from fastapi import APIRouter, Depends, Path, Query

from app.models.escalation import (
    EscalateRequest,
    EscalateResponse,
    EscalationDecideRequest,
    EscalationDecideResponse,
    EscalationQueueItem,
    EscalationQueuePage,
    EscalationQueueResponse,
)
from app.services.escalation_service import (
    decide_escalation,
    escalate_case,
    get_escalation_queue,
)
from app.utils.auth import require_min_role
from app.utils.firestore import get_firestore_client
from app.utils.roles import normalize_role

router = APIRouter(prefix="/api/v1", tags=["Escalation"])


@router.post(
    "/cases/{caseId}/escalate",
    response_model=EscalateResponse,
    summary=(
        "Escalate a case to senior partner review — captures reason and original reviewer"
    ),
    status_code=200,
)
def post_escalate_case(
    body: EscalateRequest,
    caseId: str = Path(..., description="Case ID (e.g. ZAD-2024-01-0001)"),
    user: dict = Depends(require_min_role("case_escalate")),
):
    db     = get_firestore_client()
    result = escalate_case(
        db=db,
        case_id=caseId,
        actor_uid=user["uid"],
        actor_role=normalize_role(user.get("role", "")),
        reason=body.reason,
        notes=body.notes,
    )
    return EscalateResponse(**result)


@router.get(
    "/attorney/escalation-queue",
    response_model=EscalationQueueResponse,
    summary="Return the senior partner escalation queue (sorted by deadline, escalation date, qual score)",
)
def get_senior_escalation_queue(
    page: int = Query(default=1, ge=1, description="Page number"),
    page_size: int = Query(default=20, ge=1, le=100, description="Items per page"),
    user: dict = Depends(require_min_role("escalation_queue")),
):
    db     = get_firestore_client()
    result = get_escalation_queue(db=db, user=user, page=page, page_size=page_size)

    page_data = result["page"]
    return EscalationQueueResponse(
        total_pending=result["total_pending"],
        overdue_count=result["overdue_count"],
        page=EscalationQueuePage(
            items=[EscalationQueueItem(**item) for item in page_data["items"]],
            total=page_data["total"],
            page=page_data["page"],
            page_size=page_data["page_size"],
            total_pages=page_data["total_pages"],
        ),
    )


@router.post(
    "/cases/{caseId}/escalation-decision",
    response_model=EscalationDecideResponse,
    summary="Senior partner decision: approve, reject, or return case for additional work",
    status_code=200,
)
def post_escalation_decision(
    body: EscalationDecideRequest,
    caseId: str = Path(..., description="Case ID (e.g. ZAD-2024-01-0001)"),
    user: dict = Depends(require_min_role("escalation_decide")),
):
    db     = get_firestore_client()
    result = decide_escalation(
        db=db,
        case_id=caseId,
        actor_uid=user["uid"],
        actor_role=normalize_role(user.get("role", "")),
        decision=body.decision,
        notes=body.notes,
    )
    return EscalationDecideResponse(**result)
