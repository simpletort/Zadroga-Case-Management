"""
deadline_service.py — VCF filing deadline calculation and status classification.

Rule: VCF Filing Deadline = Date of Condition Certification + 2 years.

Deadline status:
  active      > 90 days remaining
  warning_90  61-90 days remaining
  warning_60  31-60 days remaining
  warning_30  1-30 days remaining
  expired     deadline has passed
  not_set     no certification date available
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from dateutil.relativedelta import relativedelta
from google.cloud import firestore

from models.vcf_models import DeadlineStatus
from services.timeline_service import write_deadline_event

logger = logging.getLogger(__name__)

VCF_DEADLINE_YEARS = 2


def calculate_vcf_deadline(certification_date: date | datetime | str) -> date:
    """
    Calculate VCF filing deadline: certificationDate + 2 years.
    Uses relativedelta to handle leap years correctly.
    """
    if isinstance(certification_date, str):
        certification_date = date.fromisoformat(certification_date)
    elif isinstance(certification_date, datetime):
        certification_date = certification_date.date()

    return certification_date + relativedelta(years=VCF_DEADLINE_YEARS)


def get_deadline_status(deadline: date | None, today: date | None = None) -> DeadlineStatus:
    """Classify deadline status based on days remaining."""
    if deadline is None:
        return DeadlineStatus.NOT_SET

    today = today or date.today()
    days_remaining = (deadline - today).days

    if days_remaining < 0:
        return DeadlineStatus.EXPIRED
    elif days_remaining <= 30:
        return DeadlineStatus.WARNING_30
    elif days_remaining <= 60:
        return DeadlineStatus.WARNING_60
    elif days_remaining <= 90:
        return DeadlineStatus.WARNING_90
    else:
        return DeadlineStatus.ACTIVE


def days_until_deadline(deadline: date | None, today: date | None = None) -> int | None:
    """Return integer days until deadline, or None if not set."""
    if deadline is None:
        return None
    today = today or date.today()
    return (deadline - today).days


def update_case_deadline(
    db,
    case_id: str,
    certification_date_str: str | None,
    write_timeline: bool = True,
) -> dict:
    """
    Calculate and persist VCF filing deadline on a case document.

    Returns a dict with deadline info (or explains why deadline was not set).
    Return key is 'filing_deadline' (matches what registration_workflow.py reads).
    """
    today = date.today()

    if not certification_date_str:
        logger.info("update_case_deadline caseId=%s: no certification date — skipping", case_id)
        return {
            "deadline_set": False,
            "reason": "no_certification_date",
            "filing_deadline": None,
            "deadline_status": DeadlineStatus.NOT_SET.value,
        }

    try:
        cert_date = date.fromisoformat(certification_date_str[:10])
    except (ValueError, TypeError) as exc:
        logger.warning(
            "update_case_deadline caseId=%s invalid certDate=%s err=%s",
            case_id, certification_date_str, exc,
        )
        return {
            "deadline_set": False,
            "reason": "invalid_certification_date",
            "filing_deadline": None,
            "deadline_status": DeadlineStatus.NOT_SET.value,
        }

    deadline = calculate_vcf_deadline(cert_date)
    status = get_deadline_status(deadline, today)
    days_rem = days_until_deadline(deadline, today)

    update_data = {
        "enrollment.filingDeadline": deadline.isoformat(),
        "enrollment.vcfFilingDeadline": deadline.isoformat(),   # legacy field kept for dashboard queries
        "enrollment.deadlineStatus": status.value,
        "enrollment.daysUntilDeadline": days_rem,
        "enrollment.deadlineCalculatedAt": firestore.SERVER_TIMESTAMP,
    }

    db.collection("cases").document(case_id).update(update_data)

    logger.info(
        "vcf_deadline_updated caseId=%s deadline=%s status=%s daysRemaining=%s",
        case_id, deadline.isoformat(), status.value, days_rem,
    )

    if write_timeline:
        try:
            write_deadline_event(
                db=db,
                case_id=case_id,
                deadline_date=deadline.isoformat(),
                days_remaining=days_rem if days_rem is not None else 0,
                event_subtype="DeadlineCalculated",
            )
        except Exception as exc:
            logger.warning("Failed to write deadline timeline event caseId=%s: %s", case_id, exc)

    return {
        "deadline_set": True,
        "filing_deadline": deadline.isoformat(),       # key registration_workflow.py reads
        "vcf_filing_deadline": deadline.isoformat(),   # alias for backward compat
        "deadline_status": status.value,
        "days_remaining": days_rem,
        "certification_date": cert_date.isoformat(),
        "expired": status == DeadlineStatus.EXPIRED,
    }


def scan_approaching_deadlines(
    db: firestore.Client,
    alert_thresholds: list[int] | None = None,
    today: date | None = None,
) -> list[dict]:
    """
    Scan all active cases for approaching VCF deadlines.
    Returns list of cases needing alerts at the given thresholds.
    Called by the daily Cloud Scheduler job (sync Cloud Function context).
    """
    alert_thresholds = alert_thresholds or [90, 60, 30]
    today = today or date.today()
    results = []

    excluded_statuses = {"Closed", "Settled", "Does Not Qualify", "Rejected"}

    try:
        cases = (
            db.collection("cases")
            .where("enrollment.vcfFilingDeadline", "!=", None)
            .stream()
        )

        for case_doc in cases:
            data = case_doc.to_dict() or {}
            case_id = case_doc.id

            case_status = data.get("status", "")
            if case_status in excluded_statuses:
                continue

            enrollment = data.get("enrollment", {})
            deadline_str = enrollment.get("vcfFilingDeadline")
            if not deadline_str:
                continue

            try:
                deadline = date.fromisoformat(deadline_str[:10])
            except (ValueError, TypeError):
                continue

            days_rem = (deadline - today).days
            deadline_status = get_deadline_status(deadline, today)

            last_alert = enrollment.get("lastAlertMilestone")
            for threshold in sorted(alert_thresholds, reverse=True):
                if days_rem <= threshold:
                    if last_alert is None or last_alert > threshold:
                        results.append({
                            "case_id": case_id,
                            "deadline": deadline.isoformat(),
                            "days_remaining": days_rem,
                            "deadline_status": deadline_status.value,
                            "alert_threshold": threshold,
                            "assigned_paralegal": (
                                data.get("assignment", {}).get("assignedParalegal")
                            ),
                            "supervising_attorney": (
                                data.get("assignment", {}).get("supervisingAttorney")
                            ),
                            "vcf_registration_status": (
                                enrollment.get("vcfRegistrationStatus", "Not Registered")
                            ),
                            "last_alert_milestone": last_alert,
                        })
                    break

    except Exception as exc:
        logger.error("scan_approaching_deadlines failed: %s", exc)

    logger.info(
        "deadline_scan_complete today=%s cases_needing_alert=%d thresholds=%s",
        today.isoformat(), len(results), alert_thresholds,
    )
    return results