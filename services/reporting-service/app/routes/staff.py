from fastapi import APIRouter, Depends, Query
from typing import Dict
from app.models.report import StaffPerformanceResponse, StaffPerformanceItem
from app.services.aggregation_service import get_staff_case_counts, get_overdue_tasks_per_user
from app.services.cache_service import get_cache, TTLCache
from app.utils.auth import require_min_role
from app.utils.firestore import get_firestore_client
from app.utils.date_helpers import now_utc
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/reports", tags=["Staff"])


def _get_user_profiles() -> Dict[str, dict]:
    db = get_firestore_client()
    users = db.collection("users").stream()
    return {doc.id: doc.to_dict() for doc in users}


@router.get("/staff-performance", response_model=StaffPerformanceResponse)
def staff_performance(
    period_days: int = Query(default=30, ge=7, le=90),
    _user: dict = Depends(require_min_role("staff_performance")),
    cache: TTLCache = Depends(get_cache),
):
    cache_key = "staff_performance_{}".format(period_days)
    cached = cache.get(cache_key)
    if cached:
        return cached

    case_counts = get_staff_case_counts()
    overdue_counts = get_overdue_tasks_per_user()
    profiles = _get_user_profiles()

    staff_items = []
    for user_id, counts in case_counts.items():
        profile = profiles.get(user_id, {})
        display_name = (
            profile.get("displayName")
            or counts.get("display_name")
            or user_id
        )
        staff_items.append(StaffPerformanceItem(
            user_id=user_id,
            display_name=display_name,
            role=profile.get("role", "unknown"),
            active_cases=counts["active_cases"],
            cases_completed_period=counts["cases_completed_period"],
            cases_handled_ytd=counts.get("cases_handled_ytd", 0),
            avg_days_to_close=counts.get("avg_days_to_close"),
            performance_rating=counts.get("performance_rating"),
            overdue_tasks=overdue_counts.get(user_id, 0),
        ))

    staff_items.sort(key=lambda s: s.active_cases, reverse=True)

    result = StaffPerformanceResponse(
        generated_at=now_utc(),
        period_days=period_days,
        staff=staff_items,
    )
    cache.set(cache_key, result)
    return result
