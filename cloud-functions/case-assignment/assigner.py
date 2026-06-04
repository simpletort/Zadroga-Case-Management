"""
SimpleTort — Case Assignment Engine

Supports two assignment modes configured in firmSettings:
  - load_balancing  (default): assign to the active staff member with the lowest activeCaseCount
  - round_robin: rotate through active staff in stable createdAt order

Both modes:
  - Only consider staff where role == firmSettings/assignment_mode.assignToRole AND isActive == True
  - Respect maxCaseload: skip any staff member at or above their cap (if set)
  - Perform the final write (case update + activeCaseCount increment + timeline) in a
    single Firestore transaction to prevent double-assignment under concurrent events

firmSettings documents:
  assignment_mode          → { value: "load_balancing" | "round_robin", assignToRole: "paralegal" }
  assignment_rr_pointer    → { value: <int> }   (round-robin cursor)
"""

import logging
from datetime import datetime, timezone

from google.cloud import firestore

logger = logging.getLogger(__name__)

ASSIGNMENT_MODE_DOC  = "assignment_mode"
RR_POINTER_DOC       = "assignment_rr_pointer"

# Local role normalisation — mirrors services/case-development/app/utils/roles.py
# without creating a shared-package dependency in the Cloud Function.
_ROLE_DISPLAY_TO_CODE: dict[str, str] = {
    "Paralegal":      "paralegal",
    "Junior Partner": "junior_partner",
    "Senior Partner": "senior_partner",
    "System Admin":   "system_admin",
    "Admin Staff":    "admin_staff",
}

# Inverse map: code format → display format (used for dual-role queries)
_CODE_TO_ROLE_DISPLAY: dict[str, str] = {v: k for k, v in _ROLE_DISPLAY_TO_CODE.items()}


def _normalize_role(role: str) -> str:
    """Convert display-format role to code-format; pass-through if already code."""
    return _ROLE_DISPLAY_TO_CODE.get(role, role)


# ── Public API ─────────────────────────────────────────────────────────────

def assign_case(db: firestore.Client, case_id: str) -> str | None:
    """
    Select a staff member and atomically commit the assignment.
    Returns the assigned user's userId, or None if no one is available.
    """
    mode            = _get_setting(db, ASSIGNMENT_MODE_DOC, default="load_balancing")
    assignment_role = _get_assignment_role(db)
    paralegals      = _get_available_paralegals(db, assignment_role)

    if not paralegals:
        logger.warning("No active '%s' found in staff collection", assignment_role)
        return None

    if mode == "round_robin":
        selected = _round_robin_pick(db, paralegals)
    else:
        selected = _load_balance_pick(paralegals)

    if selected is None:
        logger.warning("All '%s' staff are at maximum caseload", assignment_role)
        return None

    _do_assign(db, case_id, selected, mode)
    return selected["userId"]


# ── Selection strategies ───────────────────────────────────────────────────

def _load_balance_pick(paralegals: list[dict]) -> dict | None:
    """
    Return the paralegal with the lowest activeCaseCount who is under their
    maxCaseload cap (if set). Returns None if all are at capacity.
    """
    eligible = [p for p in paralegals if _under_cap(p)]
    if not eligible:
        return None
    return min(eligible, key=lambda p: p.get("activeCaseCount") or 0)


def _round_robin_pick(db: firestore.Client, paralegals: list[dict]) -> dict | None:
    """
    Advance the round-robin pointer transactionally and return the selected
    paralegal, skipping those at their maxCaseload cap.
    If all eligible paralegals have been tried, return None.
    """
    # Stable ordering: sort by createdAt ascending so the same list is always
    # produced regardless of Firestore query ordering.
    ordered = sorted(paralegals, key=lambda p: p.get("createdAt") or 0)
    eligible = [p for p in ordered if _under_cap(p)]
    if not eligible:
        return None

    n = len(eligible)
    pointer_ref = db.collection("firmSettings").document(RR_POINTER_DOC)

    @firestore.transactional
    def _advance_pointer(transaction: firestore.Transaction) -> int:
        snap = pointer_ref.get(transaction=transaction)
        current = (snap.to_dict() or {}).get("value", 0) if snap.exists else 0
        next_val = current + 1
        transaction.set(pointer_ref, {"value": next_val}, merge=True)
        return current  # return the value BEFORE incrementing (0-indexed)

    transaction = db.transaction()
    index = _advance_pointer(transaction)
    return eligible[index % n]


# ── Atomic commit ──────────────────────────────────────────────────────────

def _do_assign(
    db: firestore.Client,
    case_id: str,
    paralegal: dict,
    mode: str,
) -> None:
    """
    Atomically update the case, increment the paralegal's activeCaseCount,
    and append a timeline event — all in a single Firestore transaction.
    """
    paralegal_id   = paralegal["userId"]
    display_name   = paralegal.get("displayName", paralegal_id)
    assigned_at    = datetime.now(tz=timezone.utc)

    case_ref       = db.collection("cases").document(case_id)
    staff_ref      = db.collection("staff").document(paralegal_id)
    timeline_ref   = db.collection("cases").document(case_id).collection("timeline").document()

    @firestore.transactional
    def _txn(transaction: firestore.Transaction) -> None:
        # Guard: re-read the case inside the transaction to prevent double-assignment
        case_snap = case_ref.get(transaction=transaction)
        case_data = case_snap.to_dict() or {}
        existing = (case_data.get("assignment") or {}).get("assignedParalegal", "")
        if existing:
            logger.info(
                "Race condition guard: caseId=%s already assigned to %s inside transaction",
                case_id, existing,
            )
            return

        staff_snap       = staff_ref.get(transaction=transaction)
        current_count    = (staff_snap.to_dict() or {}).get("activeCaseCount", 0) or 0

        transaction.update(case_ref, {
            "assignment.assignedParalegal": paralegal_id,
            "assignment.assignmentDate":   assigned_at,
        })
        transaction.update(staff_ref, {
            "activeCaseCount": current_count + 1,
        })
        transaction.set(timeline_ref, {
            "eventId":     timeline_ref.id,
            "caseId":      case_id,
            "timestamp":   firestore.SERVER_TIMESTAMP,
            "eventType":   "Assignment",
            "description": "Case assigned to {} via {}.".format(
                display_name, mode.replace("_", "-")
            ),
            "performedBy": "system",
            "metadata": {
                "assignedTo":      paralegal_id,
                "assignedName":    display_name,
                "mode":            mode,
                "activeCaseCount": current_count + 1,
            },
        })

    transaction = db.transaction()
    _txn(transaction)
    logger.info(
        "Assigned caseId=%s to paralegalId=%s (mode=%s)",
        case_id, paralegal_id, mode,
    )


# ── Firestore helpers ──────────────────────────────────────────────────────

def _get_available_paralegals(db: firestore.Client, role: str = "paralegal") -> list[dict]:
    """Query staff for active members with the given assignment role, returned as plain dicts.

    Dual-queries both code format (e.g. "paralegal") and display format (e.g. "Paralegal")
    to handle the mixed role values present in the DB during migration.
    Deduplication by document ID prevents double-counting.

    The role defaults to "paralegal" but is driven by firmSettings/assignment_mode.assignToRole
    so any staff role (admin_staff, junior_partner, etc.) can be the assignment target.
    """
    role_code    = _normalize_role(role)  # ensure code format regardless of input
    role_display = _CODE_TO_ROLE_DISPLAY.get(role_code, role_code)

    seen: set[str] = set()
    results: list[dict] = []

    # Query both code and display variants; set deduplicates when they are the same.
    for role_val in {role_code, role_display}:
        for doc in (
            db.collection("staff")
            .where("role", "==", role_val)
            .where("isActive", "==", True)
            .stream()
        ):
            if doc.id in seen:
                continue
            seen.add(doc.id)
            data = doc.to_dict()
            if data:
                results.append(data)

    return results


def _get_setting(db: firestore.Client, doc_id: str, default: str) -> str:
    """Read a single scalar string from the firmSettings collection."""
    try:
        snap = db.collection("firmSettings").document(doc_id).get()
        if snap.exists:
            return snap.to_dict().get("value", default)
    except Exception as exc:
        logger.warning("Could not read firmSettings/%s: %s; using default '%s'", doc_id, exc, default)
    return default


def _get_assignment_role(db: firestore.Client) -> str:
    """Read the assignment target role from firmSettings/assignment_mode.assignToRole.

    Defaults to "paralegal" when the field is absent, the document has not been
    seeded, or Firestore is unreachable — so assignment always has a safe fallback.
    """
    try:
        snap = db.collection("firmSettings").document(ASSIGNMENT_MODE_DOC).get()
        if snap.exists:
            return (snap.to_dict() or {}).get("assignToRole", "paralegal")
    except Exception as exc:
        logger.warning(
            "Could not read assignToRole from firmSettings/%s: %s; defaulting to 'paralegal'",
            ASSIGNMENT_MODE_DOC, exc,
        )
    return "paralegal"


def _under_cap(paralegal: dict) -> bool:
    """Return True if the paralegal has capacity for another case."""
    max_caseload = paralegal.get("maxCaseload")
    if max_caseload is None:
        return True  # no cap configured
    active = paralegal.get("activeCaseCount") or 0
    return active < max_caseload
