# Endpoints defined in this module:
#   GET  /api/v1/cases/{caseId}/communications   — paginated communication log for a case (min: paralegal)
#                                                  ?type=      call | email | letter | fax | in_person
#                                                  ?page=      page number (default: 1)
#                                                  ?page_size= items per page (default: 20, max: 100)
#   POST /api/v1/cases/{caseId}/communications   — log a new communication entry (min: paralegal)

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

_VALID_TYPES = {"call", "email", "letter", "fax", "in_person"}


@router.get(
    "/cases/{caseId}/communications",
    response_model=CommunicationListResponse,
    summary="List communication log entries for a case",
)
def get_communications(
    caseId: str = Path(..., description="Case ID (e.g. ZAD-2024-01-0001)"),
    comm_type: Optional[str] = Query(
        default=None,
        alias="type",
        pattern="^(call|email|letter|fax|in_person)$",
        description="Filter by communication type: call | email | letter | fax | in_person",
    ),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    _user: dict = Depends(require_min_role("comm_read")),
):
    db     = get_firestore_client()
    result = list_communications(
        db=db,
        case_id=caseId,
        comm_type=comm_type,
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
    summary="Log a new communication entry for a case",
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
        comm_type=body.type,
        direction=body.direction,
        subject=body.subject,
        notes=body.notes,
        contact_name=body.contact_name,
        contact_method=body.contact_method,
    )
    return CommunicationEntry(**result)
