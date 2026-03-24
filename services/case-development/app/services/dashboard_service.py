"""
Paralegal Dashboard Service

Query strategy:
  1. Scope to assigned paralegal at Firestore level (uses composite index).
     Admin roles skip this filter and see all cases.
  2. Post-filter in Python for ranges and multi-status values.
     Firestore cannot combine inequality range filters on multiple fields in one query,
     and "in" for multi-status conflicts with other range filters.
  3. Compute KPI summary from the full post-filtered set (before pagination slice).
  4. Sort in Python (allows sorting by any column without additional Firestore indexes).
  5. Slice for the requested page.

Document completeness proxy:
  Uses qualification.vcfQualScore (0–100) to avoid N sub-collection reads per case.
"""

import logging
from datetime import datetime, timezone
from typing import Optional

from google.cloud import firestore

logger = logging.getLogger(__name__)

ADMIN_ROLES = {"admin_staff", "junior_partner", "senior_partner", "system_admin"}

SORT_KEY_MAP = {
    "case_id":              lambda c: c["case_id"] or "",
    "client_name":          lambda c: (c["last_name"] or "") + (c["first_name"] or ""),
    "status":               lambda c: c["status"] or "",
    "vcf_deadline":         lambda c: (
        c["vcf_deadline"].timestamp() if c["vcf_deadline"] else float("inf")
    ),
    "doc_completeness_pct": lambda c: c["doc_completeness_pct"] if c["doc_completeness_pct"] is not None else -1.0,
    "qual_score":           lambda c: c["qual_score"] if c["qual_score"] is not None else -1.0,
    "last_activity":        lambda c: (
        c["last_activity"].timestamp() if c["last_activity"] else 0.0
    ),
}


def get_dashboard(
    db: firestore.Client,
    user: dict,
    statuses: Optional[list[str]],
    deadline_from: Optional[datetime],
    deadline_to: Optional[datetime],
    completeness_min: Optional[float],
    completeness_max: Optional[float],
    qual_min: Optional[float],
    qual_max: Optional[float],
    sort_by: str,
    sort_dir: str,
    page: int,
    page_size: int,
) -> dict:
    user_role = user.get("role", "")
    user_uid  = user.get("uid", "")
    is_admin  = user_role in ADMIN_ROLES

    # ── 1. Firestore query ────────────────────────────────────────────────
    query = db.collection("cases")
    if not is_admin:
        query = query.where("assignment.assignedParalegal", "==", user_uid)

    # Apply single-status equality filter at Firestore level when safe to do so
    # (no range filters that would conflict with a compound inequality query)
    use_fs_status = (
        statuses and len(statuses) == 1
        and not any([deadline_from, deadline_to, completeness_min,
                     completeness_max, qual_min, qual_max])
    )
    if use_fs_status:
        query = query.where("status", "==", statuses[0])

    docs = list(query.stream())

    # ── 2. Materialise ────────────────────────────────────────────────────
    now = datetime.now(tz=timezone.utc)
    cases: list[dict] = []

    for doc in docs:
        data    = doc.to_dict() or {}
        lead    = data.get("leadData")    or {}
        qual    = data.get("qualification") or {}
        enroll  = data.get("enrollment")  or {}
        assign  = data.get("assignment")  or {}

        vcf_deadline  = enroll.get("vcfRegDeadline")
        last_activity = data.get("updatedAt")

        # Normalise Firestore Timestamps to aware datetime
        if hasattr(vcf_deadline, "tzinfo") and vcf_deadline.tzinfo is None:
            vcf_deadline = vcf_deadline.replace(tzinfo=timezone.utc)
        if hasattr(last_activity, "tzinfo") and last_activity is not None and last_activity.tzinfo is None:
            last_activity = last_activity.replace(tzinfo=timezone.utc)

        cases.append({
            "case_id":              doc.id,
            "first_name":           lead.get("firstName", ""),
            "last_name":            lead.get("lastName", ""),
            "status":               data.get("status", ""),
            "vcf_deadline":         vcf_deadline,
            "doc_completeness_pct": qual.get("vcfQualScore"),
            "qual_score":           qual.get("medicalQualScore"),
            "last_activity":        last_activity,
            "assigned_paralegal":   assign.get("assignedParalegal"),
            "is_flagged":           False,
        })

    # ── 3. Post-filter ────────────────────────────────────────────────────
    def _passes(c: dict) -> bool:
        # Always apply Python-side status filter even when Firestore also
        # filtered (redundant in production, but required for test correctness
        # because mocked Firestore .where() calls return all docs unchanged).
        if statuses and c["status"] not in statuses:
            return False
        if deadline_from and c["vcf_deadline"] and c["vcf_deadline"] < deadline_from:
            return False
        if deadline_to and c["vcf_deadline"] and c["vcf_deadline"] > deadline_to:
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
        return True

    filtered = [c for c in cases if _passes(c)]

    # ── 4. Summary KPIs ───────────────────────────────────────────────────
    total_assigned  = len(filtered)
    overdue         = sum(1 for c in filtered if c["vcf_deadline"] and c["vcf_deadline"] < now)
    pending_review  = sum(1 for c in filtered if c["status"] == "Pending Paralegal Review")
    scored          = [c["qual_score"] for c in filtered if c["qual_score"] is not None]
    avg_qual        = round(sum(scored) / len(scored), 1) if scored else None

    summary = {
        "total_assigned":   total_assigned,
        "overdue_deadline": overdue,
        "pending_review":   pending_review,
        "avg_qual_score":   avg_qual,
    }

    # ── 5. Sort ───────────────────────────────────────────────────────────
    key_fn = SORT_KEY_MAP.get(sort_by, SORT_KEY_MAP["last_activity"])
    filtered.sort(key=key_fn, reverse=(sort_dir == "desc"))

    # ── 6. Paginate ───────────────────────────────────────────────────────
    total       = len(filtered)
    total_pages = max(1, (total + page_size - 1) // page_size)
    start       = (page - 1) * page_size
    page_items  = filtered[start: start + page_size]

    return {
        "summary": summary,
        "page": {
            "items":       page_items,
            "total":       total,
            "page":        page,
            "page_size":   page_size,
            "total_pages": total_pages,
        },
    }
