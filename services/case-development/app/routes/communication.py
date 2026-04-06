# Endpoints defined in this module:
#   GET  /api/v1/cases/{caseId}/communications   — paginated communication log for a case (min: paralegal)
#                                                  ?channel=   Email | Call | Letter | Fax | In Person
#                                                  ?page=      page number (default: 1)
#                                                  ?page_size= items per page (default: 20, max: 100)
#   POST /api/v1/cases/{caseId}/communications   — log a new manual communication entry (min: paralegal)

from typing import Optional

from fastapi import APIRouter, Depends, Path, Query

from app.models.communication import (
    CommunicationEntry,
    CommunicationListResponse,
    CommunicationLogRequest,
)
from app.services.communication_service import create_communication, list_communications
from app.utils.auth import require_min_role
from app.utils.firestore import get_firestore_client

router = APIRouter(prefix="/api/v1", tags=["Communications"])


@router.get(
    "/cases/{caseId}/communications",
    response_model=CommunicationListResponse,
    summary="List communication log entries for a case",
)
def get_communications(
    caseId: str = Path(..., description="Case ID (e.g. ZAD-2024-01-0001)"),
    channel: Optional[str] = Query(
        default=None,
        pattern="^(Email|Call|Letter|Fax|In Person)$",
        description="Filter by channel: Email | Call | Letter | Fax | In Person",
    ),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    _user: dict = Depends(require_min_role("comm_read")),
):
    db     = get_firestore_client()
    result = list_communications(
        db=db,
        case_id=caseId,
        channel=channel,
        page=page,
        page_size=page_size,
    )
    return CommunicationListResponse(
        items=[CommunicationEntry(**item) for item in result["items"]],
        total=result["total"],
        page=result["page"],
        page_size=result["page_size"],
        total_pages=result["total_pages"],
    )


@router.post(
    "/cases/{caseId}/communications",
    response_model=CommunicationEntry,
    status_code=201,
    summary="Log a new manual communication entry for a case",
)
def post_communication(
    body: CommunicationLogRequest,
    caseId: str = Path(..., description="Case ID (e.g. ZAD-2024-01-0001)"),
    user: dict = Depends(require_min_role("comm_write")),
):
    db     = get_firestore_client()
    result = create_communication(
        db=db,
        case_id=caseId,
        actor_uid=user["uid"],
        channel=body.channel,
        direction=body.direction,
        subject=body.subject,
        body=body.body,
        from_address=body.from_address,
        to=body.to,
    )
    return CommunicationEntry(**result)
