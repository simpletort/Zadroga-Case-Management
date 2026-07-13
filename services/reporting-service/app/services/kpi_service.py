import logging
from datetime import datetime, timezone
from typing import Optional, Tuple

from app.models.report import KPIMetric, KPIDashboardResponse
from app.services.aggregation_service import (
    get_cases_by_status,
    get_cases_created_in_period,
    get_cases_settled_in_period,
    get_leads_in_period,
    get_active_statuses,
)
from app.utils.firestore import get_firestore_client
from app.utils.date_helpers import now_utc

logger = logging.getLogger(__name__)


def _load_firm_config(doc_id: str) -> dict:
    """
    Load a ``firmSettings/{doc_id}`` document from Firestore.

    Returns an empty dict when the document is absent or Firestore is
    unreachable so callers always receive a safe fallback.
    """
    try:
        db = get_firestore_client()
        doc = db.collection("firmSettings").document(doc_id).get()
        return doc.to_dict() if doc.exists else {}
    except Exception as exc:
        logger.warning("Failed to load firmSettings/%s: %s", doc_id, exc)
        return {}

CACHE_DOC_ID = "kpi_dashboard"


def _trend(current: float, previous: float) -> Tuple[Optional[float], Optional[str]]:
    if previous == 0:
        return None, None
    pct = round(((current - previous) / previous) * 100, 1)
    direction = "up" if pct > 0 else ("down" if pct < 0 else "neutral")
    return pct, direction


def compute_kpi_dashboard(period_days: int = 30) -> KPIDashboardResponse:
    # Load firm config once — used for active statuses, score field, metric labels
    intake_config    = _load_firm_config("intake")
    reporting_config = _load_firm_config("reporting")

    # Score field name: firmSettings/intake.scoreFieldName (default: "caseScore")
    score_field = intake_config.get("scoreFieldName", "caseScore")

    # Metric label for avg score: firmSettings/reporting.metricLabels.avgScore
    metric_labels   = reporting_config.get("metricLabels", {})
    avg_score_label = metric_labels.get("avgScore", "Avg Medical Score")

    active_statuses = get_active_statuses()

    current_leads   = get_leads_in_period(period_days)
    current_settled = get_cases_settled_in_period(period_days)
    statuses        = get_cases_by_status()

    total_active = sum(
        s["count"] for s in statuses if s["status"] in active_statuses
    )

    prior_leads = get_leads_in_period(period_days * 2)
    prior_leads_count = max(0, len(prior_leads) - len(current_leads))
    prior_settled_count = 0

    total_leads = len(current_leads)
    qualified = sum(
        1 for c in current_leads
        if c.get("status") not in ("Does Not Qualify", "Withdrawn")
    )
    qualification_rate = round((qualified / total_leads * 100), 1) if total_leads else 0.0

    scored_cases = [
        c for c in current_leads
        if c.get(score_field) is not None
    ]
    avg_score = (
        round(sum(c[score_field] for c in scored_cases) / len(scored_cases), 1)
        if scored_cases else 0.0
    )

    intake_durations = []
    for c in current_leads:
        created = c.get("createdAt")
        paralegal_assigned = c.get("paralegalAssignedAt")
        if created and paralegal_assigned:
            intake_durations.append((paralegal_assigned - created).days)
    avg_intake_days = (
        round(sum(intake_durations) / len(intake_durations), 1)
        if intake_durations else None
    )

    lead_trend, lead_dir = _trend(total_leads, prior_leads_count)
    settled_trend, settled_dir = _trend(len(current_settled), prior_settled_count)

    metrics = [
        KPIMetric(
            label="New Leads",
            value=float(total_leads),
            unit="cases",
            trend=lead_trend,
            trend_direction=lead_dir,
        ),
        KPIMetric(
            label="Active Cases",
            value=float(total_active),
            unit="cases",
        ),
        KPIMetric(
            label="Cases Settled",
            value=float(len(current_settled)),
            unit="cases",
            trend=settled_trend,
            trend_direction=settled_dir,
        ),
        KPIMetric(
            label="Qualification Rate",
            value=qualification_rate,
            unit="%",
        ),
        KPIMetric(
            label=avg_score_label,
            value=avg_score,
            unit="score",
        ),
    ]

    if avg_intake_days is not None:
        metrics.append(KPIMetric(
            label="Avg Lead to Paralegal (days)",
            value=avg_intake_days,
            unit="days",
        ))

    response = KPIDashboardResponse(
        generated_at=now_utc(),
        period_days=period_days,
        metrics=metrics,
    )

    _write_to_analytics_cache(CACHE_DOC_ID, response.model_dump(mode="json"))
    return response


def _write_to_analytics_cache(doc_id: str, data: dict) -> None:
    try:
        db = get_firestore_client()
        db.collection("analyticsCache").document(doc_id).set({
            **data,
            "cachedAt": datetime.now(timezone.utc),
        })
    except Exception as e:
        logger.warning("Failed to write analyticsCache/%s: %s", doc_id, e)


def read_from_analytics_cache(doc_id: str) -> Optional[dict]:
    try:
        db = get_firestore_client()
        doc = db.collection("analyticsCache").document(doc_id).get()
        if doc.exists:
            return doc.to_dict()
    except Exception as e:
        logger.warning("Failed to read analyticsCache/%s: %s", doc_id, e)
    return None
