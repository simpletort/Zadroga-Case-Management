from app.utils.firestore import get_firestore_client
from app.utils.date_helpers import now_utc, days_ago, to_firestore_timestamp, parse_dt, start_of_month, months_ago
from app.models.report import MonthlyRevenueItem
from typing import List, Dict
import logging
from collections import defaultdict
from dateutil.relativedelta import relativedelta

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


def get_leads_ytd() -> List[dict]:
    db = get_firestore_client()
    now = now_utc()
    ytd_start = to_firestore_timestamp(
        now.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
    )
    docs = db.collection("cases").where("createdAt", ">=", ytd_start).stream()
    return [doc.to_dict() for doc in docs]


def get_monthly_revenue(num_months: int = 12) -> List[MonthlyRevenueItem]:
    """
    Return per-calendar-month filings, awards, and gross award totals
    for the last ``num_months`` months (most recent last).

    ``filings``         — cases whose ``createdAt`` falls in that month.
    ``awards``          — cases whose ``status`` is Awarded or Settled AND
                          whose ``updatedAt`` falls in that month (proxy for
                          when the award was recorded; replace with a dedicated
                          ``awardedAt`` field if one is added to case docs).
    ``gross_award_total`` — sum of ``gross_award`` from the canonical settlement
                          subcollection doc (doc.id == data["calculation_id"])
                          for each awarded case in that month.

    ⚠️  AMBER zone — review this function before merging.  The aggregation
    makes N+1 Firestore reads (one subcollection read per awarded case in the
    window).  For small case volumes this is acceptable; revisit with a
    denormalised field on the case doc if query latency becomes a problem.
    """
    db = get_firestore_client()
    now = now_utc()

    # Build ordered list of (month_start, month_end, label) for the window.
    # month_start is inclusive, month_end is exclusive (== next month start).
    buckets = []
    for i in range(num_months - 1, -1, -1):
        month_start = start_of_month(now - relativedelta(months=i))
        month_end   = month_start + relativedelta(months=1)
        label       = month_start.strftime("%b %Y")   # e.g. "Jul 2025"
        buckets.append((month_start, month_end, label))

    window_start = to_firestore_timestamp(buckets[0][0])
    window_end   = to_firestore_timestamp(buckets[-1][1])

    # --- filings: cases created within the window ---
    filing_counts: Dict[str, int] = defaultdict(int)
    for doc in (
        db.collection("cases")
        .where("createdAt", ">=", window_start)
        .where("createdAt", "<",  window_end)
        .stream()
    ):
        data = doc.to_dict() or {}
        dt = parse_dt(data.get("createdAt"))
        if dt:
            label = start_of_month(dt).strftime("%b %Y")
            filing_counts[label] += 1

    # --- awards: Awarded/Settled cases whose updatedAt is in the window ---
    # Also collect gross_award_total per month from settlement subcollections.
    award_counts:  Dict[str, int]   = defaultdict(int)
    award_totals:  Dict[str, float] = defaultdict(float)

    for award_status in ("Awarded", "Settled"):
        for doc in (
            db.collection("cases")
            .where("status",    "==", award_status)
            .where("updatedAt", ">=", window_start)
            .where("updatedAt", "<",  window_end)
            .stream()
        ):
            data  = doc.to_dict() or {}
            dt    = parse_dt(data.get("updatedAt"))
            if not dt:
                continue
            label = start_of_month(dt).strftime("%b %Y")
            award_counts[label] += 1

            # Look up canonical settlement calculation doc for this case
            for sdoc in doc.reference.collection("settlement").stream():
                sdata = sdoc.to_dict() or {}
                if sdata.get("calculation_id") != sdoc.id:
                    continue   # skip sibling docs (inputs, expenses, liens …)
                try:
                    award_totals[label] += float(sdata.get("gross_award", 0))
                except (TypeError, ValueError):
                    logger.warning(
                        "Non-numeric gross_award on case %s settlement doc %s",
                        doc.id, sdoc.id,
                    )
                break  # only one canonical doc per case

    return [
        MonthlyRevenueItem(
            month=label,
            filings=filing_counts.get(label, 0),
            awards=award_counts.get(label, 0),
            gross_award_total=round(award_totals.get(label, 0.0), 2),
        )
        for _, _, label in buckets
    ]


def get_ytd_expenses() -> float:
    """
    Sum case expenses for the current calendar year.

    Expenses are stored as an ``items`` array on the document at
    ``cases/{caseId}/settlement/expenses``.  Each item has ``amount``
    (float) and ``addedAt`` (Firestore Timestamp).  We iterate all
    cases, fetch each settlement/expenses doc, and sum items whose
    ``addedAt`` falls on or after Jan 1 of this year.
    """
    db = get_firestore_client()
    now = now_utc()
    ytd_start = now.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
    ytd_start_naive = ytd_start.replace(tzinfo=None)
    total = 0.0

    try:
        for case_doc in db.collection("cases").stream():
            exp_ref = (
                case_doc.reference
                .collection("settlement")
                .document("expenses")
            )
            exp_doc = exp_ref.get()
            if not exp_doc.exists:
                continue
            items = (exp_doc.to_dict() or {}).get("items", [])
            for item in items:
                added_at = parse_dt(item.get("addedAt"))
                if added_at is None:
                    continue
                added_naive = added_at.replace(tzinfo=None) if added_at.tzinfo else added_at
                if added_naive < ytd_start_naive:
                    continue
                try:
                    total += float(item.get("amount", 0))
                except (TypeError, ValueError):
                    logger.warning("Non-numeric amount in settlement/expenses for case %s", case_doc.id)
    except Exception as exc:
        logger.warning("get_ytd_expenses failed: %s", exc)

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


def _performance_rating(avg_days: float) -> float:
    """Linear scale: <=30 days → 5.0, >=180 days → 1.0."""
    if avg_days <= 30:
        return 5.0
    if avg_days >= 180:
        return 1.0
    return round(5.0 - (avg_days - 30) * (4.0 / 150), 1)


def get_staff_case_counts() -> Dict[str, dict]:
    db = get_firestore_client()
    now = now_utc()
    cutoff_30d = to_firestore_timestamp(days_ago(30))
    ytd_start = to_firestore_timestamp(now.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0))

    result: Dict[str, dict] = defaultdict(lambda: {
        "active_cases": 0,
        "cases_completed_period": 0,
        "cases_handled_ytd": 0,
        "days_to_close_list": [],
        "display_name": None,
    })

    for status in get_active_statuses(db):
        docs = db.collection("cases").where("status", "==", status).stream()
        for doc in docs:
            data = doc.to_dict()
            assignment = data.get("assignment", {})
            uid = assignment.get("assignedParalegal") or assignment.get("assignedAttorney")
            if uid:
                result[uid]["active_cases"] += 1
                if not result[uid]["display_name"]:
                    result[uid]["display_name"] = (
                        assignment.get("assignedParalegalName")
                        or assignment.get("assignedAttorneyName")
                    )

    # Last-30-day settled cases (cases_completed_period)
    for doc in (
        db.collection("cases")
        .where("status", "==", "Settled")
        .where("settledAt", ">=", cutoff_30d)
        .stream()
    ):
        data = doc.to_dict()
        assignment = data.get("assignment", {})
        uid = assignment.get("assignedParalegal") or assignment.get("assignedAttorney")
        if uid:
            result[uid]["cases_completed_period"] += 1
            if not result[uid]["display_name"]:
                result[uid]["display_name"] = (
                    assignment.get("assignedParalegalName")
                    or assignment.get("assignedAttorneyName")
                )

    # YTD settled cases — also compute avg_days_to_close
    for doc in (
        db.collection("cases")
        .where("status", "==", "Settled")
        .where("settledAt", ">=", ytd_start)
        .stream()
    ):
        data = doc.to_dict()
        assignment = data.get("assignment", {})
        uid = assignment.get("assignedParalegal") or assignment.get("assignedAttorney")
        if not uid:
            continue
        result[uid]["cases_handled_ytd"] += 1
        if not result[uid]["display_name"]:
            result[uid]["display_name"] = (
                assignment.get("assignedParalegalName")
                or assignment.get("assignedAttorneyName")
            )
        settled_at = parse_dt(data.get("settledAt"))
        created_at = parse_dt(data.get("createdAt"))
        if settled_at and created_at:
            s = settled_at.replace(tzinfo=None) if settled_at.tzinfo else settled_at
            c = created_at.replace(tzinfo=None) if created_at.tzinfo else created_at
            result[uid]["days_to_close_list"].append((s - c).days)

    # Resolve avg_days_to_close and performance_rating
    for uid, data in result.items():
        days_list = data.pop("days_to_close_list", [])
        if days_list:
            avg = round(sum(days_list) / len(days_list), 1)
            data["avg_days_to_close"] = avg
            data["performance_rating"] = _performance_rating(avg)
        else:
            data["avg_days_to_close"] = None
            data["performance_rating"] = None

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
