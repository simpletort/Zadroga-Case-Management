# Endpoints defined in this module:
#   GET    /api/v1/cases/search              — advanced full-text search + filtering (min: paralegal)
#                                              ?q=                full-text query (name, case_id, email, phone)
#                                              ?statuses=         one or more status values (repeat param)
#                                              ?case_type=        all | wtc | vcf
#                                              ?assignees=        paralegal UID(s) — admin roles only
#                                              ?attorney=         attorney UID(s)  — admin roles only
#                                              ?deadline_from/to= VCF deadline range (ISO 8601)
#                                              ?created_from/to=  case created date range (ISO 8601)
#                                              ?completeness_min/max=  doc completeness % (0-100)
#                                              ?qual_min/max=     qual score range (0-100)
#                                              ?screening_result= pass | fail | pending
#                                              ?sort_by=          case_id | client_name | status | case_type |
#                                                                 vcf_deadline | doc_completeness_pct |
#                                                                 qual_score | last_activity | created_at
#                                              ?sort_dir=         asc | desc  (default: desc)
#                                              ?page=             page number (default: 1)
#                                              ?page_size=        items per page (default: 20, max: 100)
#
#   GET    /api/v1/cases/search/export       — export filtered results as CSV (no pagination)
#                                              same query params as /cases/search except page/page_size
#
#   GET    /api/v1/search/presets            — list saved filter presets for the current user
#   POST   /api/v1/search/presets            — save a new filter preset
#   PATCH  /api/v1/search/presets/{id}       — update a saved preset
#   DELETE /api/v1/search/presets/{id}       — delete a saved preset

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse

from app.models.search import (
    FilterPreset,
    FilterPresetFilters,
    FilterPresetListResponse,
    FilterPresetRequest,
    SearchCaseSummary,
    SearchPage,
    SearchResponse,
)
from app.services.search_service import (
    delete_preset,
    export_cases_csv,
    list_presets,
    save_preset,
    search_cases,
    update_preset,
)
from app.utils.firestore import get_firestore_client

router = APIRouter(prefix="/api/v1", tags=["Case Search"])


# ── Shared dependency: all search/export query parameters ─────────────────────

def _search_params(
    q: Optional[str] = Query(
        default=None,
        description="Full-text search: matches client name, case ID, email, or phone",
    ),
    statuses: Optional[list[str]] = Query(
        default=None,
        description="One or more status values (repeat param for multiple)",
    ),
    case_type: Optional[str] = Query(
        default=None,
        pattern="^(all|wtc|vcf)$",
        description="Case type: all | wtc | vcf",
    ),
    assignees: Optional[list[str]] = Query(
        default=None,
        description="Filter by paralegal UID(s) — admin roles only",
    ),
    attorney: Optional[list[str]] = Query(
        default=None,
        description="Filter by attorney UID(s) — admin roles only",
    ),
    deadline_from: Optional[datetime] = Query(
        default=None,
        description="VCF deadline on or after this date (ISO 8601)",
    ),
    deadline_to: Optional[datetime] = Query(
        default=None,
        description="VCF deadline on or before this date (ISO 8601)",
    ),
    created_from: Optional[datetime] = Query(
        default=None,
        description="Case created on or after this date (ISO 8601)",
    ),
    created_to: Optional[datetime] = Query(
        default=None,
        description="Case created on or before this date (ISO 8601)",
    ),
    completeness_min: Optional[float] = Query(default=None, ge=0, le=100),
    completeness_max: Optional[float] = Query(default=None, ge=0, le=100),
    qual_min: Optional[float] = Query(default=None, ge=0, le=100),
    qual_max: Optional[float] = Query(default=None, ge=0, le=100),
    screening_result: Optional[str] = Query(
        default=None,
        description="Screening result value (e.g. pass | fail | pending)",
    ),
    sort_by: str = Query(
        default="last_activity",
        description=(
            "Column to sort by: case_id | client_name | status | case_type | "
            "vcf_deadline | doc_completeness_pct | qual_score | last_activity | created_at"
        ),
    ),
    sort_dir: str = Query(default="desc", pattern="^(asc|desc)$"),
) -> dict:
    return {
        "q":                q,
        "statuses":         statuses,
        "case_type":        case_type,
        "assignees":        assignees,
        "attorney":         attorney,
        "deadline_from":    deadline_from,
        "deadline_to":      deadline_to,
        "created_from":     created_from,
        "created_to":       created_to,
        "completeness_min": completeness_min,
        "completeness_max": completeness_max,
        "qual_min":         qual_min,
        "qual_max":         qual_max,
        "screening_result": screening_result,
        "sort_by":          sort_by,
        "sort_dir":         sort_dir,
    }


# ── Search ────────────────────────────────────────────────────────────────────

@router.get(
    "/cases/search",
    response_model=SearchResponse,
    summary="Advanced full-text search and filtering across all cases",
)
def case_search(
    params: dict = Depends(_search_params),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
):
    db     = get_firestore_client()
    result = search_cases(db=db, page=page, page_size=page_size, **params)
    raw    = result["page"]
    return SearchResponse(
        page=SearchPage(
            items=[SearchCaseSummary(**item) for item in raw["items"]],
            total=raw["total"],
            page=raw["page"],
            page_size=raw["page_size"],
            total_pages=raw["total_pages"],
        )
    )


# ── CSV Export ────────────────────────────────────────────────────────────────

@router.get(
    "/cases/search/export",
    summary="Export filtered cases to CSV",
    responses={200: {"content": {"text/csv": {}}, "description": "CSV file download"}},
)
def case_search_export(
    params: dict = Depends(_search_params),
):
    db          = get_firestore_client()
    csv_content = export_cases_csv(db=db, **params)
    return StreamingResponse(
        iter([csv_content]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=cases_export.csv"},
    )


# ── Filter Presets ────────────────────────────────────────────────────────────

@router.get(
    "/search/presets",
    response_model=FilterPresetListResponse,
    summary="List saved filter presets for the current user",
)
def get_presets():
    db  = get_firestore_client()
    raw = list_presets(db, "system")
    presets = []
    for p in raw:
        presets.append(FilterPreset(
            preset_id=p["preset_id"],
            name=p["name"],
            filters=FilterPresetFilters(**p.get("filters", {})),
            created_at=p.get("createdAt") or datetime.now(),
            updated_at=p.get("updatedAt") or datetime.now(),
        ))
    return FilterPresetListResponse(presets=presets)


@router.post(
    "/search/presets",
    response_model=FilterPreset,
    status_code=status.HTTP_201_CREATED,
    summary="Save a new filter preset",
)
def create_preset(
    body: FilterPresetRequest,
):
    db = get_firestore_client()
    p  = save_preset(
        db, "system", body.name,
        body.filters.model_dump(exclude_none=True)
    )
    return FilterPreset(
        preset_id=p["preset_id"],
        name=p["name"],
        filters=FilterPresetFilters(**p.get("filters", {})),
        created_at=p["createdAt"],
        updated_at=p["updatedAt"],
    )


@router.patch(
    "/search/presets/{preset_id}",
    response_model=FilterPreset,
    summary="Update a saved filter preset",
)
def patch_preset(
    preset_id: str,
    body: FilterPresetRequest,
):
    db = get_firestore_client()
    p  = update_preset(
        db, "system", preset_id,
        body.name,
        body.filters.model_dump(exclude_none=True),
    )
    if p is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Preset not found.",
        )
    return FilterPreset(
        preset_id=p["preset_id"],
        name=p["name"],
        filters=FilterPresetFilters(**p.get("filters", {})),
        created_at=p.get("createdAt") or datetime.now(),
        updated_at=p["updatedAt"],
    )


@router.delete(
    "/search/presets/{preset_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a saved filter preset",
)
def remove_preset(
    preset_id: str,
):
    db    = get_firestore_client()
    found = delete_preset(db, "system", preset_id)
    if not found:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Preset not found.",
        )
