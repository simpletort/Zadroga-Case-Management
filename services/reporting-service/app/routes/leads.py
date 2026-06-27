from fastapi import APIRouter, Depends
from app.models.report import LeadConversionResponse, LeadConversionAnalyticsResponse, MonthlyLeadVolumeItem, FunnelStageItem, CampaignItem
from app.services.aggregation_service import get_all_cases, get_lead_conversion_analytics, get_active_statuses
from app.services.cache_service import get_cache, TTLCache
from app.utils.auth import require_min_role
from app.utils.date_helpers import now_utc
from app.utils.firestore import get_firestore_client
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/reports", tags=["Leads"])


def _get_status_categories():
    try:
        db = get_firestore_client()
        doc = db.collection("firmSettings").document("case_statuses").get()
        statuses = (doc.to_dict() or {}).get("statuses", []) if doc.exists else []
        active = {s["value"] for s in statuses if s.get("category") == "active"}
        disqualified = {s["value"] for s in statuses if s.get("category") == "terminal"}
        closed = {s["value"] for s in statuses if s.get("category") == "closed"}
        if active:
            return active, disqualified, closed
    except Exception as exc:
        logger.warning("Failed to load status categories from firmSettings: %s", exc)
    # Fallback
    return (
        {"New Lead", "Pending Client Information", "Pending Paralegal Review",
         "Pending Attorney Review", "Pending Senior Review", "Approved for Filing",
         "VCF - Submitted", "Awarded", "On Hold"},
        {"Does Not Qualify", "Withdrawn", "Closed"},
        {"Settled", "Rejected"},
    )


@router.get("/lead-conversion", response_model=LeadConversionResponse)
def lead_conversion(
    _user: dict = Depends(require_min_role("lead_conversion")),
    cache: TTLCache = Depends(get_cache),
):
    cached = cache.get("lead_conversion_ytd")
    if cached:
        return cached

    leads = get_all_cases()
    total = len(leads)

    active_statuses, disqualified_statuses, closed_statuses = _get_status_categories()

    disqualified = sum(1 for c in leads if c.get("status") in disqualified_statuses)
    converted = sum(1 for c in leads if c.get("status") in active_statuses)
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


@router.get("/lead-conversion-analytics", response_model=LeadConversionAnalyticsResponse)
def lead_conversion_analytics(
    _user: dict = Depends(require_min_role("lead_conversion")),
    cache: TTLCache = Depends(get_cache),
):
    cached = cache.get("lead_conversion_analytics")
    if cached:
        return cached

    data = get_lead_conversion_analytics()
    result = LeadConversionAnalyticsResponse(
        generated_at=now_utc(),
        total_leads=data["total_leads"],
        converted=data["converted"],
        conversion_rate=data["conversion_rate"],
        best_channel=data["best_channel"],
        monthly_volume=[MonthlyLeadVolumeItem(**m) for m in data["monthly_volume"]],
        funnel=[FunnelStageItem(**f) for f in data["funnel"]],
        campaigns=[CampaignItem(**c) for c in data["campaigns"]],
    )
    cache.set("lead_conversion_analytics", result)
    return result
