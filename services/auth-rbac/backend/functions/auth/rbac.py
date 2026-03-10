"""
auth/rbac.py — Role-Based Access Control
=========================================
Defines the role/permission enum types and the canonical permission matrix.
Guards (require_permission, require_any) are used by every API handler.

Changes from original:
  F-04 — MANAGE_USERS added to ADMIN_STAFF permission set.
  Refactor — audit writes now use write_audit_event() from middleware/http.py
             instead of inline db().collection("audit_log").add({}) blocks.
             db() shortcut replaces fs_admin.client() for case access check.
"""

from __future__ import annotations

import logging
from enum import Enum
from typing import Set

from firebase_functions import https_fn

from middleware.http import db, json_err, write_audit_event

logger = logging.getLogger(__name__)


# ── Roles ─────────────────────────────────────────────────────────────────────
class Role(str, Enum):
    ADMIN_STAFF    = "admin_staff"
    PARALEGAL      = "paralegal"
    JUNIOR_PARTNER = "junior_partner"
    SENIOR_PARTNER = "senior_partner"
    CLIENT         = "client"


# ── Permissions ───────────────────────────────────────────────────────────────
class Permission(str, Enum):
    VIEW_ALL_CASES     = "view_all_cases"
    VIEW_OWN_CASE      = "view_own_case"
    MANAGE_TASKS       = "manage_tasks"
    LOG_COMMUNICATIONS = "log_communications"
    REQUEST_DOCUMENTS  = "request_documents"
    UPLOAD_DOCUMENTS   = "upload_documents"
    VIEW_DOCUMENTS     = "view_documents"
    VIEW_OWN_DOCUMENTS = "view_own_documents"
    ADD_NOTES          = "add_notes"
    VIEW_NOTES         = "view_notes"
    SUBMIT_FOR_REVIEW  = "submit_for_review"
    APPROVE_REJECT     = "approve_reject_cases"
    ESCALATE           = "escalate_cases"
    VIEW_PHI           = "view_phi"
    MANAGE_USERS       = "manage_users"
    ASSIGN_ROLES       = "assign_roles"
    VIEW_REPORTS       = "view_reports"
    VIEW_AUDIT_LOG     = "view_audit_log"
    SYSTEM_ADMIN       = "system_admin"


# ── Permission matrix ─────────────────────────────────────────────────────────
ROLE_PERMISSIONS: dict[Role, Set[Permission]] = {
    Role.CLIENT: {
        Permission.VIEW_OWN_CASE,
        Permission.VIEW_OWN_DOCUMENTS,
        Permission.UPLOAD_DOCUMENTS,
    },
    Role.ADMIN_STAFF: {
        Permission.VIEW_ALL_CASES,
        Permission.MANAGE_TASKS,
        Permission.LOG_COMMUNICATIONS,
        Permission.VIEW_DOCUMENTS,
        Permission.VIEW_NOTES,
        Permission.MANAGE_USERS,    # F-04 fix: admin_staff must reach user-management APIs
    },
    Role.PARALEGAL: {
        Permission.VIEW_ALL_CASES,
        Permission.MANAGE_TASKS,
        Permission.LOG_COMMUNICATIONS,
        Permission.VIEW_DOCUMENTS,
        Permission.VIEW_NOTES,
        Permission.REQUEST_DOCUMENTS,
        Permission.UPLOAD_DOCUMENTS,
        Permission.ADD_NOTES,
        Permission.SUBMIT_FOR_REVIEW,
    },
    Role.JUNIOR_PARTNER: {
        Permission.VIEW_ALL_CASES,
        Permission.MANAGE_TASKS,
        Permission.LOG_COMMUNICATIONS,
        Permission.VIEW_DOCUMENTS,
        Permission.VIEW_NOTES,
        Permission.REQUEST_DOCUMENTS,
        Permission.UPLOAD_DOCUMENTS,
        Permission.ADD_NOTES,
        Permission.SUBMIT_FOR_REVIEW,
        Permission.APPROVE_REJECT,
        Permission.ESCALATE,
        Permission.VIEW_PHI,
    },
    Role.SENIOR_PARTNER: {p for p in Permission},  # all permissions
}


# ── Core lookup functions ─────────────────────────────────────────────────────
def has_permission(role: str, permission: Permission) -> bool:
    try:
        r = Role(role)
    except ValueError:
        return False
    return permission in ROLE_PERMISSIONS.get(r, set())


def get_role_permissions(role: str) -> list[str]:
    try:
        r = Role(role)
    except ValueError:
        return []
    return [p.value for p in ROLE_PERMISSIONS.get(r, set())]


# ── Guard helpers — used inside every Cloud Function handler ──────────────────
def require_permission(
    user: dict,
    permission: Permission,
    request: https_fn.Request | None = None,
) -> https_fn.Response | None:
    """
    Return a 403 Response if the user lacks the given permission, else None.

    Usage:
        guard = require_permission(user, Permission.MANAGE_USERS, req)
        if guard: return guard
    """
    if not has_permission(user.get("role", ""), permission):
        write_audit_event(
            "permission_denied",
            uid=user.get("uid", "unknown"),
            role=user.get("role", "unknown"),
            required_permission=str(permission),
            path=getattr(request, "path", ""),
        )
        return json_err("Forbidden: insufficient permissions.", 403)
    return None


def require_any(
    user: dict,
    *permissions: Permission,
    request: https_fn.Request | None = None,
) -> https_fn.Response | None:
    """Return 403 unless the user has at least one of the given permissions."""
    if not permissions or not any(
        has_permission(user.get("role", ""), p) for p in permissions
    ):
        write_audit_event(
            "permission_denied",
            uid=user.get("uid", "unknown"),
            role=user.get("role", "unknown"),
            required_permission=f"any_of:{[p.value for p in permissions]}",
            path=getattr(request, "path", ""),
        )
        return json_err("Forbidden: insufficient permissions.", 403)
    return None


# ── Case access check ─────────────────────────────────────────────────────────
def check_case_access(user: dict, case_id: str) -> bool:
    """Return True if the user is allowed to view the given case."""
    if has_permission(user.get("role", ""), Permission.VIEW_ALL_CASES):
        return True
    doc = db().collection("cases").document(case_id).get()
    if not doc.exists:
        return False
    return doc.to_dict().get("client_uid") == user.get("uid")


# ── Audit helpers ─────────────────────────────────────────────────────────────
def log_role_change(
    changed_by: str, target_uid: str, old_role: str, new_role: str
) -> None:
    """Write a role_change event to the audit log."""
    write_audit_event(
        "role_change",
        changed_by=changed_by,
        target_user=target_uid,
        old_role=old_role,
        new_role=new_role,
    )
