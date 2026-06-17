from fastapi import APIRouter, Depends, Query
from typing import Dict
from app.models.report import (
    CasesByStatusResponse,
    CasesByStatusItem,
    FunnelResponse,
    FunnelStage,
    BottleneckResponse,
    Bottleneck,
)
from app.services.aggregation_service import (
    get_cases_by_status,
    get_bottleneck_cases,
    get_active_statuses,
)
from app.services.cache_service import get_cache, TTLCache
from app.utils.auth import require_min_role
from app.utils.date_helpers import now_utc
from collections import defaultdict
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/reports", tags=["Cases"])

FUNNEL_STAGES = [
    "New Lead",
    "Pending Client Info",
    "Pending Paralegal Review",
    "Pending Attorney Review",
    "Ready for Filing",
    "VCF - Submitted",
    "Awarded",
    "Settled",
]


@router.get("/cases-by-status", response_model=CasesByStatusResponse)
def cases_by_status(
    _user: dict = Depends(require_min_role("cases_by_status")),
    cache: TTLCache = Depends(get_cache),
):
    cached = cache.get("cases_by_status")
    if cached:
        return cached

    raw = get_cases_by_status()
    items = [CasesByStatusItem(**row) for row in raw]
    total_active = sum(
        item.count for item in items if item.status in get_active_statuses()
    )

    result = CasesByStatusResponse(
        generated_at=now_utc(),
        items=items,
        total_active=total_active,
    )
    cache.set("cases_by_status", result)
    return result


@router.get("/funnel", response_model=FunnelResponse)
def case_funnel(
    _user: dict = Depends(require_min_role("funnel")),
    cache: TTLCache = Depends(get_cache),
):
    cached = cache.get("funnel")
    if cached:
        return cached

    raw = get_cases_by_status()
    status_counts: Dict[str, int] = {row["status"]: row["count"] for row in raw}

    stages = []
    for i, stage in enumerate(FUNNEL_STAGES):
        count = status_counts.get(stage, 0)
        conversion_rate = None

        if i > 0:
            prev_count = status_counts.get(FUNNEL_STAGES[i - 1], 0)
            if prev_count > 0:
                conversion_rate = round((count / prev_count) * 100, 1)

        stages.append(FunnelStage(
            stage=stage,
            count=count,
            conversion_rate=conversion_rate,
        ))

    result = FunnelResponse(generated_at=now_utc(), stages=stages)
    cache.set("funnel", result)
    return result


@router.get("/bottlenecks", response_model=BottleneckResponse)
def bottleneck_analysis(
    threshold_days: int = Query(default=30, ge=7, le=180),
    _user: dict = Depends(require_min_role("bottlenecks")),
    cache: TTLCache = Depends(get_cache),
):
    cache_key = "bottlenecks_{}".format(threshold_days)
    cached = cache.get(cache_key)
    if cached:
        return cached

    raw_cases = get_bottleneck_cases(threshold_days=threshold_days)
    by_status: Dict[str, list] = defaultdict(list)

    for case in raw_cases:
        by_status[case["status"]].append(case)

    bottlenecks = []
    for status, cases in by_status.items():
        days_list = [c["days_stuck"] for c in cases]
        paralegal_ids = list({
            c["assignedParalegal"] for c in cases
            if c.get("assignedParalegal")
        })
        bottlenecks.append(Bottleneck(
            status=status,
            case_count=len(cases),
            avg_days_stuck=round(sum(days_list) / len(days_list), 1),
            oldest_case_days=float(max(days_list)),
            assigned_paralegal_ids=paralegal_ids,
        ))

    bottlenecks.sort(key=lambda b: b.avg_days_stuck, reverse=True)

    result = BottleneckResponse(
        generated_at=now_utc(),
        bottlenecks=bottlenecks,
        threshold_days=threshold_days,
    )
    cache.set(cache_key, result)
    return result
