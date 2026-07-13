"""
Case Search Service

Search strategy:
  1. Scope query to assigned paralegal at Firestore level (admin roles see all).
  2. Stream all docs and materialise extended case dict (includes email, phone,
     screening_result, assigned_attorney, created_at beyond the dashboard fields).
  3. Apply all filters in Python:
       - Full-text: substring match across client name, case ID, email, phone
       - Status, case type, assignee, attorney
       - VCF deadline range, created date range
       - Completeness and qual score ranges
       - Screening result
  4. Sort in Python (any column without extra Firestore indexes).
  5. Slice for the requested page (or return all rows for CSV export).

Filter Presets:
  Stored as sub-collection: staff/{uid}/searchPresets/{presetId}
"""

import csv
import io
import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from google.cloud import firestore

logger = logging.getLogger(__name__)

SORT_KEY_MAP = {
    "case_id":              lambda c: c["case_id"] or "",
    "client_name":          lambda c: (c["last_name"] or "") + (c["first_name"] or ""),
    "status":               lambda c: c["status"] or "",
    "case_type":            lambda c: c["case_type"] or "",
    "vcf_deadline":         lambda c: (
        c["vcf_deadline"].timestamp() if c["vcf_deadline"] else float("inf")
    ),
    "doc_completeness_pct": lambda c: c["doc_completeness_pct"] if c["doc_completeness_pct"] is not None else -1.0,
    "qual_score":           lambda c: c["qual_score"] if c["qual_score"] is not None else -1.0,
    "last_activity":        lambda c: (
        c["last_activity"].timestamp() if c["last_activity"] else 0.0
    ),
    "created_at":           lambda c: (
        c["created_at"].timestamp() if c["created_at"] else 0.0
    ),
}

_CASE_TYPE_MAP = {"wtc": "WTC", "vcf": "VCF"}

_CSV_FIELDS = [
    "case_id", "first_name", "last_name", "email", "phone",
    "status", "case_type", "screening_result",
    "qual_score", "doc_completeness_pct",
    "vcf_deadline", "created_at", "last_activity",
    "assigned_paralegal", "assigned_attorney",
]


# ── Helpers ───────────────────────────────────────────────────────────────────

def _normalize_dt(value) -> Optional[datetime]:
    """Ensure a Firestore Timestamp or naive datetime is timezone-aware UTC."""
    if value is None:
        return None
    if hasattr(value, "tzinfo") and value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _load_cases(
    db: firestore.Client,
) -> list[dict]:
    """Stream all cases from Firestore and materialise the extended case dict."""
    query = db.collection("cases")

    cases: list[dict] = []
    for doc in query.stream():
        data   = doc.to_dict() or {}
        assign = data.get("assignment") or {}

        vcf_details = data.get("vcfScreeningDetails") or {}
        score_raw   = vcf_details.get("score")
        qual_score  = float(score_raw) if score_raw is not None else None

        cases.append({
            "case_id":              doc.id,
            "first_name":           data.get("firstName") or "",
            "last_name":            data.get("lastName") or "",
            "email":                (data.get("email") or "").lower(),
            "phone":                data.get("phone") or "",
            "status":               data.get("status") or "",
            "case_type":            None,
            "vcf_deadline":         None,
            "doc_completeness_pct": None,
            "qual_score":           qual_score,
            "screening_result":     data.get("vcfEligibility"),
            "last_activity":        _normalize_dt(data.get("updatedAt")),
            "created_at":           _normalize_dt(data.get("createdAt")),
            "assigned_paralegal":   assign.get("assignedParalegal"),
            "assigned_attorney":    assign.get("assignedAttorney"),
            "is_flagged":           False,
        })

    return cases


def _apply_filters(
    cases: list[dict],
    *,
    q: Optional[str],
    statuses: Optional[list[str]],
    resolved_type: Optional[str],
    effective_assignees: Optional[list[str]],
    effective_attorneys: Optional[list[str]],
    deadline_from: Optional[datetime],
    deadline_to: Optional[datetime],
    created_from: Optional[datetime],
    created_to: Optional[datetime],
    completeness_min: Optional[float],
    completeness_max: Optional[float],
    qual_min: Optional[float],
    qual_max: Optional[float],
    screening_result: Optional[str],
) -> list[dict]:
    """Apply all post-load filters in Python, including full-text search."""
    q_lower = q.lower().strip() if q else None

    def _passes(c: dict) -> bool:
        # Full-text search: substring match across name, case ID, email, phone
        if q_lower:
            haystack = " ".join([
                c["first_name"].lower(),
                c["last_name"].lower(),
                c["case_id"].lower(),
                c["email"],
                c["phone"],
            ])
            if q_lower not in haystack:
                return False

        if statuses and c["status"] not in statuses:
            return False
        if resolved_type and c["case_type"] != resolved_type:
            return False
        if effective_assignees and c["assigned_paralegal"] not in effective_assignees:
            return False
        if effective_attorneys and c["assigned_attorney"] not in effective_attorneys:
            return False

        if deadline_from and c["vcf_deadline"] and c["vcf_deadline"] < deadline_from:
            return False
        if deadline_to and c["vcf_deadline"] and c["vcf_deadline"] > deadline_to:
            return False

        if created_from and c["created_at"] and c["created_at"] < created_from:
            return False
        if created_to and c["created_at"] and c["created_at"] > created_to:
            return False

        if completeness_min is not None and c["doc_completeness_pct"] is not None:
            if c["doc_completeness_pct"] < completeness_min:
                return False
        if completeness_max is not None and c["doc_completeness_pct"] is not None:
            if c["doc_completeness_pct"] > completeness_max:
                return False

        if qual_min is not None and c["qual_score"] is not None:
            if c["qual_score"] < qual_min:
                return False
        if qual_max is not None and c["qual_score"] is not None:
            if c["qual_score"] > qual_max:
                return False

        if screening_result and c["screening_result"] != screening_result:
            return False

        return True

    return [c for c in cases if _passes(c)]


def _resolve_params(
    case_type: Optional[str],
    assignees: Optional[list[str]],
    attorney: Optional[list[str]],
) -> tuple[Optional[str], Optional[list[str]], Optional[list[str]]]:
    resolved_type       = _CASE_TYPE_MAP.get((case_type or "").lower())
    effective_assignees = assignees if assignees else None
    effective_attorneys = attorney if attorney else None
    return resolved_type, effective_assignees, effective_attorneys


# ── Public API ────────────────────────────────────────────────────────────────

def search_cases(
    db: firestore.Client,
    q: Optional[str],
    statuses: Optional[list[str]],
    case_type: Optional[str],
    assignees: Optional[list[str]],
    attorney: Optional[list[str]],
    deadline_from: Optional[datetime],
    deadline_to: Optional[datetime],
    created_from: Optional[datetime],
    created_to: Optional[datetime],
    completeness_min: Optional[float],
    completeness_max: Optional[float],
    qual_min: Optional[float],
    qual_max: Optional[float],
    screening_result: Optional[str],
    sort_by: str,
    sort_dir: str,
    page: int,
    page_size: int,
) -> dict:
    resolved_type, effective_assignees, effective_attorneys = _resolve_params(
        case_type, assignees, attorney
    )

    cases    = _load_cases(db)
    filtered = _apply_filters(
        cases,
        q=q,
        statuses=statuses,
        resolved_type=resolved_type,
        effective_assignees=effective_assignees,
        effective_attorneys=effective_attorneys,
        deadline_from=deadline_from,
        deadline_to=deadline_to,
        created_from=created_from,
        created_to=created_to,
        completeness_min=completeness_min,
        completeness_max=completeness_max,
        qual_min=qual_min,
        qual_max=qual_max,
        screening_result=screening_result,
    )

    key_fn = SORT_KEY_MAP.get(sort_by, SORT_KEY_MAP["last_activity"])
    filtered.sort(key=key_fn, reverse=(sort_dir == "desc"))

    total       = len(filtered)
    total_pages = max(1, (total + page_size - 1) // page_size)
    start       = (page - 1) * page_size
    page_items  = filtered[start: start + page_size]

    return {
        "page": {
            "items":       page_items,
            "total":       total,
            "page":        page,
            "page_size":   page_size,
            "total_pages": total_pages,
        }
    }


def export_cases_csv(
    db: firestore.Client,
    q: Optional[str],
    statuses: Optional[list[str]],
    case_type: Optional[str],
    assignees: Optional[list[str]],
    attorney: Optional[list[str]],
    deadline_from: Optional[datetime],
    deadline_to: Optional[datetime],
    created_from: Optional[datetime],
    created_to: Optional[datetime],
    completeness_min: Optional[float],
    completeness_max: Optional[float],
    qual_min: Optional[float],
    qual_max: Optional[float],
    screening_result: Optional[str],
    sort_by: str,
    sort_dir: str,
) -> str:
    """Return all matching cases as a CSV string (no pagination)."""
    resolved_type, effective_assignees, effective_attorneys = _resolve_params(
        case_type, assignees, attorney
    )

    cases    = _load_cases(db)
    filtered = _apply_filters(
        cases,
        q=q,
        statuses=statuses,
        resolved_type=resolved_type,
        effective_assignees=effective_assignees,
        effective_attorneys=effective_attorneys,
        deadline_from=deadline_from,
        deadline_to=deadline_to,
        created_from=created_from,
        created_to=created_to,
        completeness_min=completeness_min,
        completeness_max=completeness_max,
        qual_min=qual_min,
        qual_max=qual_max,
        screening_result=screening_result,
    )

    key_fn = SORT_KEY_MAP.get(sort_by, SORT_KEY_MAP["last_activity"])
    filtered.sort(key=key_fn, reverse=(sort_dir == "desc"))

    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=_CSV_FIELDS, extrasaction="ignore")
    writer.writeheader()

    for case in filtered:
        row = dict(case)
        for dt_field in ("vcf_deadline", "created_at", "last_activity"):
            val = row.get(dt_field)
            row[dt_field] = val.isoformat() if val else ""
        writer.writerow(row)

    return output.getvalue()


# ── Filter Presets ────────────────────────────────────────────────────────────

def _preset_collection(db: firestore.Client, user_uid: str):
    return db.collection("staff").document(user_uid).collection("searchPresets")


def list_presets(db: firestore.Client, user_uid: str) -> list[dict]:
    docs = list(_preset_collection(db, user_uid).stream())
    presets = []
    for doc in docs:
        data = doc.to_dict() or {}
        data["preset_id"] = doc.id
        presets.append(data)
    presets.sort(key=lambda p: p.get("createdAt") or datetime.min.replace(tzinfo=timezone.utc))
    return presets


def save_preset(db: firestore.Client, user_uid: str, name: str, filters: dict) -> dict:
    now       = datetime.now(tz=timezone.utc)
    preset_id = str(uuid.uuid4())
    data = {
        "name":      name,
        "filters":   filters,
        "createdAt": now,
        "updatedAt": now,
    }
    _preset_collection(db, user_uid).document(preset_id).set(data)
    data["preset_id"] = preset_id
    return data


def update_preset(
    db: firestore.Client, user_uid: str, preset_id: str, name: str, filters: dict
) -> Optional[dict]:
    now = datetime.now(tz=timezone.utc)
    ref = _preset_collection(db, user_uid).document(preset_id)
    doc = ref.get()
    if not doc.exists:
        return None
    updates = {"name": name, "filters": filters, "updatedAt": now}
    ref.update(updates)
    data = doc.to_dict() or {}
    data.update(updates)
    data["preset_id"] = preset_id
    return data


def delete_preset(db: firestore.Client, user_uid: str, preset_id: str) -> bool:
    ref = _preset_collection(db, user_uid).document(preset_id)
    doc = ref.get()
    if not doc.exists:
        return False
    ref.delete()
    return True
