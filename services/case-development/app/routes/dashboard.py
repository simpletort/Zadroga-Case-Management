from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Query

from app.models.dashboard import DashboardResponse, DashboardSummary, DashboardPage, CaseSummary
from app.services.dashboard_service import get_dashboard
from app.utils.auth import require_min_role
from app.utils.firestore import get_firestore_client

router = APIRouter(prefix="/api/v1", tags=["Paralegal Dashboard"])


@router.get(
    "/dashboard/cases",
    response_model=DashboardResponse,
    summary="Paginated, filterable case list for the Paralegal Dashboard",
)
def paralegal_dashboard(
    statuses: Optional[list[str]] = Query(
        default=None,
        description="One or more status values (repeat param for multiple)",
    ),
    deadline_from: Optional[datetime] = Query(
        default=None,
        description="Filter: VCF deadline on or after this date (ISO 8601)",
    ),
    deadline_to: Optional[datetime] = Query(
        default=None,
        description="Filter: VCF deadline on or before this date (ISO 8601)",
    ),
    completeness_min: Optional[float] = Query(default=None, ge=0, le=100),
    completeness_max: Optional[float] = Query(default=None, ge=0, le=100),
    qual_min: Optional[float] = Query(default=None, ge=0, le=100),
    qual_max: Optional[float] = Query(default=None, ge=0, le=100),
    sort_by: str = Query(
        default="last_activity",
        description="Column to sort by: case_id | client_name | status | vcf_deadline | doc_completeness_pct | qual_score | last_activity",
    ),
    sort_dir: str = Query(default="desc", pattern="^(asc|desc)$"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    user: dict = Depends(require_min_role("dashboard_view")),
):
    db = get_firestore_client()
    result = get_dashboard(
        db=db,
        user=user,
        statuses=statuses,
        deadline_from=deadline_from,
        deadline_to=deadline_to,
        completeness_min=completeness_min,
        completeness_max=completeness_max,
        qual_min=qual_min,
        qual_max=qual_max,
        sort_by=sort_by,
        sort_dir=sort_dir,
        page=page,
        page_size=page_size,
    )

    raw = result["page"]
    return DashboardResponse(
        summary=DashboardSummary(**result["summary"]),
        page=DashboardPage(
            items=[CaseSummary(**item) for item in raw["items"]],
            total=raw["total"],
            page=raw["page"],
            page_size=raw["page_size"],
            total_pages=raw["total_pages"],
        ),
    )
