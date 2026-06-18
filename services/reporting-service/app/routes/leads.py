from fastapi import APIRouter, Depends
from app.models.report import LeadConversionResponse
from app.services.aggregation_service import get_leads_ytd
from app.services.cache_service import get_cache, TTLCache
from app.utils.auth import require_min_role
from app.utils.date_helpers import now_utc
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/reports", tags=["Leads"])

DISQUALIFIED_STATUSES = {"Does Not Qualify", "Withdrawn"}
ACTIVE_OR_SETTLED = {
    "Pending Client Info",
    "Pending Paralegal Review",
    "Pending Attorney Review",
    "Ready for Filing",
    "VCF - Submitted",
    "Awarded",
    "Settled",
    "On Hold",
}


@router.get("/lead-conversion", response_model=LeadConversionResponse)
def lead_conversion(
    _user: dict = Depends(require_min_role("lead_conversion")),
    cache: TTLCache = Depends(get_cache),
):
    cached = cache.get("lead_conversion_ytd")
    if cached:
        return cached

    leads = get_leads_ytd()
    total = len(leads)

    disqualified = sum(1 for c in leads if c.get("status") in DISQUALIFIED_STATUSES)
    converted = sum(1 for c in leads if c.get("status") in ACTIVE_OR_SETTLED)
    qualified = total - disqualified

    qualification_rate = round((qualified / total * 100), 1) if total else 0.0
    conversion_rate = round((converted / total * 100), 1) if total else 0.0

    intake_durations = []
    for c in leads:
        created = c.get("createdAt")
        assigned = c.get("paralegalAssignedAt")
        if created and assigned:
            intake_durations.append((assigned - created).days)

    avg_days = (
        round(sum(intake_durations) / len(intake_durations), 1)
        if intake_durations else None
    )

    result = LeadConversionResponse(
        generated_at=now_utc(),
        period_days=365,
        total_leads=total,
        qualified=qualified,
        converted_to_active=converted,
        qualification_rate=qualification_rate,
        conversion_rate=conversion_rate,
        avg_days_lead_to_active=avg_days,
        disqualified=disqualified,
    )
    cache.set("lead_conversion_ytd", result)
    return result
