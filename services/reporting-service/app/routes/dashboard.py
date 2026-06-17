from fastapi import APIRouter, Depends, Query
from app.models.report import KPIDashboardResponse, MonthlyRevenueResponse
from app.services.kpi_service import compute_kpi_dashboard
from app.services.aggregation_service import get_monthly_revenue
from app.services.cache_service import get_cache, TTLCache
from app.utils.auth import require_min_role
from app.utils.date_helpers import now_utc
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/reports", tags=["Dashboard"])


@router.get("/dashboard", response_model=KPIDashboardResponse)
def get_kpi_dashboard(
    period_days: int = Query(default=30, ge=7, le=365),
    _user: dict = Depends(require_min_role("dashboard")),
    cache: TTLCache = Depends(get_cache),
):
    cache_key = "kpi_dashboard_{}".format(period_days)
    cached = cache.get(cache_key)
    if cached:
        return cached

    result = compute_kpi_dashboard(period_days=period_days)
    cache.set(cache_key, result)
    return result


@router.get("/monthly-revenue", response_model=MonthlyRevenueResponse)
def get_monthly_revenue_endpoint(
    months: int = Query(default=12, ge=1, le=24),
    _user: dict = Depends(require_min_role("dashboard")),
    cache: TTLCache = Depends(get_cache),
):
    cache_key = "monthly_revenue_{}".format(months)
    cached = cache.get(cache_key)
    if cached:
        return cached

    result = MonthlyRevenueResponse(
        generated_at=now_utc(),
        months=get_monthly_revenue(num_months=months),
    )
    cache.set(cache_key, result)
    return result
