# Endpoints defined in this module:
#   GET /api/v1/cases/{caseId}/timeline  — paginated timeline events for a case (min: paralegal)
#                                          ?event_type=  filter by event type (e.g. Communication, StatusChange)
#                                          ?page=        page number (default: 1)
#                                          ?page_size=   items per page (default: 20, max: 100)

from typing import Optional

from fastapi import APIRouter, Path, Query

from app.models.timeline import TimelineEvent, TimelineListResponse
from app.services.timeline_service import list_timeline
from app.utils.firestore import get_firestore_client

router = APIRouter(prefix="/api/v1", tags=["Timeline"])


@router.get(
    "/cases/{caseId}/timeline",
    response_model=TimelineListResponse,
    summary="List timeline events for a case, newest first",
)
def get_timeline(
    caseId: str = Path(..., description="Case ID (e.g. ZAD-2024-01-0001)"),
    event_type: Optional[str] = Query(
        default=None,
        description="Filter by event type (e.g. Communication, StatusChange, Assignment)",
    ),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
):
    db     = get_firestore_client()
    result = list_timeline(
        db=db,
        case_id=caseId,
        event_type=event_type,
        page=page,
        page_size=page_size,
    )
    return TimelineListResponse(
        items=[TimelineEvent(**item) for item in result["items"]],
        total=result["total"],
        page=result["page"],
        page_size=result["page_size"],
        total_pages=result["total_pages"],
    )
