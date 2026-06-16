from app.utils.firestore import get_firestore_client
from app.utils.date_helpers import now_utc, days_ago, to_firestore_timestamp, parse_dt
from typing import List, Dict
import logging
from collections import defaultdict

logger = logging.getLogger(__name__)

# Maps internal Firestore status values to display names used across the UI.
STATUS_MAP = {
    "Qualified": "Pending Paralegal Review",
}

ALL_STATUSES = [
    "New Lead",
    "Pending Client Info",
    "Pending Paralegal Review",
    "Pending Attorney Review",
    "Ready for Filing",
    "VCF - Submitted",
    "Awarded",
    "Settled",
    "Does Not Qualify",
    "Withdrawn",
    "On Hold",
]

# Fallback used when firmSettings/pipeline is absent or has no activeStatuses field.
DEFAULT_ACTIVE_STATUSES = [
    "New Lead",
    "Pending Client Info",
    "Pending Paralegal Review",
    "Pending Attorney Review",
    "Ready for Filing",
    "VCF - Submitted",
    "Awarded",
    "On Hold",
]


def get_active_statuses(db=None) -> List[str]:
    """
    Load active case statuses from ``firmSettings/pipeline.activeStatuses[]``.

    Falls back to ``DEFAULT_ACTIVE_STATUSES`` when the document is absent,
    the field is missing, or Firestore is unreachable — so KPI queries always
    return a result even if the config document has not been seeded yet.
    """
    try:
        _db = db or get_firestore_client()
        doc = _db.collection("firmSettings").document("pipeline").get()
        if doc.exists:
            statuses = (doc.to_dict() or {}).get("activeStatuses")
            if statuses:
                return statuses
    except Exception as exc:
        logger.warning("Failed to load activeStatuses from firmSettings/pipeline: %s", exc)
    return DEFAULT_ACTIVE_STATUSES


def get_cases_by_status() -> List[dict]:
    db = get_firestore_client()
    docs = db.collection("cases").stream()
    status_buckets: Dict[str, list] = defaultdict(list)
    now = now_utc()

    for doc in docs:
        data = doc.to_dict()
        status = STATUS_MAP.get(data.get("status", "Unknown"), data.get("status", "Unknown"))
        last_status_change = parse_dt(data.get("lastStatusChangedAt"))
        created_at = parse_dt(data.get("createdAt"))

        ref = last_status_change or created_at
        if ref is not None:
            # Ensure both sides are naive UTC for subtraction safety
            ref_naive = ref.replace(tzinfo=None) if ref.tzinfo else ref
            now_naive = now.replace(tzinfo=None)
            days_in_status = (now_naive - ref_naive).days
        else:
            days_in_status = 0

        status_buckets[status].append(days_in_status)

    result = []
    for status in ALL_STATUSES:
        days_list = status_buckets.get(status, [])
        count = len(days_list)
        avg_days = round(sum(days_list) / count, 1) if count > 0 else None
        result.append({
            "status": status,
            "count": count,
            "avg_days_in_status": avg_days,
        })

    return result


def get_cases_created_in_period(days: int) -> List[dict]:
    db = get_firestore_client()
    cutoff = to_firestore_timestamp(days_ago(days))
    docs = (
        db.collection("cases")
        .where("createdAt", ">=", cutoff)
        .stream()
    )
    return [doc.to_dict() for doc in docs]


def get_cases_settled_in_period(days: int) -> List[dict]:
    db = get_firestore_client()
    cutoff = to_firestore_timestamp(days_ago(days))
    docs = (
        db.collection("cases")
        .where("status", "==", "Settled")
        .where("settledAt", ">=", cutoff)
        .stream()
    )
    return [doc.to_dict() for doc in docs]


def get_leads_in_period(days: int) -> List[dict]:
    return get_cases_created_in_period(days)


def get_total_awards_secured() -> float:
    """
    Sum ``gross_award`` across all Awarded/Settled cases.

    Each case's award amount lives in a Firestore subcollection written by
    settlement-financial (``cases/{caseId}/settlement/{calculation_id}``),
    not on the case document itself. That subcollection also holds sibling
    docs (``inputs``, ``disbursements``, ``expenses``, ``liens``, ``loans``,
    ``statement_*``) that are NOT calculation records — to avoid double
    counting, only the doc whose ID equals its own ``calculation_id`` field
    is treated as the canonical calculation result.

    Returns 0.0 (rather than raising) for any case/doc that is missing or
    malformed, so one bad record doesn't blank out the whole KPI.
    """
    db = get_firestore_client()
    total = 0.0

    for award_status in ("Awarded", "Settled"):
        cases = db.collection("cases").where("status", "==", award_status).stream()
        for case in cases:
            settlement_docs = case.reference.collection("settlement").stream()
            for doc in settlement_docs:
                data = doc.to_dict() or {}
                if data.get("calculation_id") != doc.id:
                    continue  # not the canonical calculation record
                try:
                    total += float(data.get("gross_award", 0))
                except (TypeError, ValueError):
                    logger.warning(
                        "Non-numeric gross_award on case %s settlement doc %s",
                        case.id, doc.id,
                    )

    return round(total, 2)


def get_bottleneck_cases(threshold_days: int = 30) -> List[dict]:
    db = get_firestore_client()
    now = now_utc()
    bottlenecks = []

    for status in get_active_statuses(db):
        docs = (
            db.collection("cases")
            .where("status", "==", status)
            .stream()
        )
        for doc in docs:
            data = doc.to_dict()
            last_change = data.get("lastStatusChangedAt") or data.get("createdAt")
            if not last_change:
                continue
            days_stuck = (now - last_change).days
            if days_stuck >= threshold_days:
                display_status = STATUS_MAP.get(data.get("status", ""), data.get("status", ""))
                bottlenecks.append({
                    **data,
                    "status": display_status,
                    "caseId": doc.id,
                    "days_stuck": days_stuck,
                })

    return bottlenecks


def get_staff_case_counts() -> Dict[str, dict]:
    db = get_firestore_client()
    cutoff = to_firestore_timestamp(days_ago(30))

    result: Dict[str, dict] = defaultdict(lambda: {
        "active_cases": 0,
        "cases_completed_period": 0,
        "overdue_tasks": 0,
    })

    for status in get_active_statuses(db):
        docs = db.collection("cases").where("status", "==", status).stream()
        for doc in docs:
            data = doc.to_dict()
            uid = data.get("assignedParalegal") or data.get("assignedAttorney")
            if uid:
                result[uid]["active_cases"] += 1

    settled_docs = (
        db.collection("cases")
        .where("status", "==", "Settled")
        .where("settledAt", ">=", cutoff)
        .stream()
    )
    for doc in settled_docs:
        data = doc.to_dict()
        uid = data.get("assignedParalegal") or data.get("assignedAttorney")
        if uid:
            result[uid]["cases_completed_period"] += 1

    return result


def get_overdue_tasks_per_user() -> Dict[str, int]:
    db = get_firestore_client()
    now_ts = to_firestore_timestamp(now_utc())
    counts: Dict[str, int] = defaultdict(int)

    overdue = (
        db.collection_group("tasks")
        .where("status", "in", ["pending", "in_progress", "overdue"])
        .where("dueAt", "<", now_ts)
        .stream()
    )
    for task in overdue:
        data = task.to_dict()
        uid = data.get("assignedTo")
        if uid and uid != "admin_staff_pool":
            counts[uid] += 1

    return counts
