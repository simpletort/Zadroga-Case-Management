from app.utils.firestore import get_firestore_client
from app.utils.date_helpers import now_utc, days_ago, to_firestore_timestamp
from typing import List, Dict
import logging
from collections import defaultdict

logger = logging.getLogger(__name__)

ALL_STATUSES = [
    "New Lead",
    "Pending Client Information",
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

ACTIVE_STATUSES = [
    "New Lead",
    "Pending Client Information",
    "Pending Paralegal Review",
    "Pending Attorney Review",
    "Ready for Filing",
    "VCF - Submitted",
    "Awarded",
    "On Hold",
]


def get_cases_by_status() -> List[dict]:
    db = get_firestore_client()
    docs = db.collection("cases").stream()
    status_buckets: Dict[str, list] = defaultdict(list)
    now = now_utc()

    for doc in docs:
        data = doc.to_dict()
        status = data.get("status", "Unknown")
        last_status_change = data.get("lastStatusChangedAt")

        if last_status_change:
            days_in_status = (now - last_status_change).days
        else:
            created_at = data.get("createdAt")
            days_in_status = (now - created_at).days if created_at else 0

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


def get_bottleneck_cases(threshold_days: int = 30) -> List[dict]:
    db = get_firestore_client()
    now = now_utc()
    bottlenecks = []

    for status in ACTIVE_STATUSES:
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
                bottlenecks.append({
                    **data,
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

    for status in ACTIVE_STATUSES:
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
        .where("status", "==", "Open")
        .where("dueAt", "<", now_ts)
        .stream()
    )
    for task in overdue:
        data = task.to_dict()
        uid = data.get("assignedTo")
        if uid and uid != "admin_staff_pool":
            counts[uid] += 1

    return counts
