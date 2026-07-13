from fastapi import APIRouter, Depends
from app.models.report import ExpenseSummaryResponse, ExpenseCategoryItem
from app.services.aggregation_service import get_expense_summary
from app.services.cache_service import get_cache, TTLCache
from app.utils.auth import require_min_role
from app.utils.date_helpers import now_utc

router = APIRouter(prefix="/reports", tags=["Expenses"])


@router.get("/expense-summary", response_model=ExpenseSummaryResponse)
def expense_summary(
    _user: dict = Depends(require_min_role("dashboard")),
    cache: TTLCache = Depends(get_cache),
):
    cached = cache.get("expense_summary")
    if cached:
        return cached

    data = get_expense_summary()
    result = ExpenseSummaryResponse(
        generated_at=now_utc(),
        categories=[ExpenseCategoryItem(**c) for c in data["categories"]],
        total_expenses=data["total_expenses"],
    )
    cache.set("expense_summary", result)
    return result
