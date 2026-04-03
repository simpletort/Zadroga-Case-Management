"""
auth/rbac.py — Role-Based Access Control
=========================================
Permission strings aligned to the existing `roles` collection in Firestore
(simpletort-dev database) which uses dot-notation e.g. "cases.read".

Role documents in Firestore:
  roles/admin_staff
  roles/junior_partner
  roles/paralegal
  roles/senior_partner
  roles/system_admin
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
    SYSTEM_ADMIN   = "system_admin"
    CLIENT         = "client"


# ── Permissions — dot-notation matching your Firestore roles collection ────────
class Permission(str, Enum):
    # Cases
    CASES_READ          = "cases.read"
    CASES_WRITE         = "cases.write"
    CASES_STATUS_UPDATE = "cases.status.update"
    CASES_APPROVE       = "cases.approve"
    CASES_DELETE        = "cases.delete"

    # Clients
    CLIENTS_READ        = "clients.read"
    CLIENTS_WRITE       = "clients.write"

    # Documents
    DOCUMENTS_READ      = "documents.read"
    DOCUMENTS_UPLOAD    = "documents.upload"
    DOCUMENTS_VERIFY    = "documents.verify"
    DOCUMENTS_OVERRIDE  = "documents.override"

    # Tasks
    TASKS_READ          = "tasks.read"
    TASKS_WRITE         = "tasks.write"
    TASKS_COMPLETE      = "tasks.complete"

    # Communications
    COMMUNICATIONS_READ  = "communications.read"
    COMMUNICATIONS_WRITE = "communications.write"

    # Timeline
    TIMELINE_READ       = "timeline.read"

    # Expenses & Disbursements
    EXPENSES_READ       = "expenses.read"
    EXPENSES_WRITE      = "expenses.write"
    DISBURSEMENTS_READ  = "disbursements.read"
    DISBURSEMENTS_WRITE = "disbursements.write"
    DISBURSEMENTS_APPROVE = "disbursements.approve"

    # Staff & Users
    STAFF_READ          = "staff.read"
    STAFF_WRITE         = "staff.write"
    STAFF_MANAGE        = "staff.manage"

    # Reports & Analytics
    REPORTS_READ        = "reports.read"
    ANALYTICS_READ      = "analytics.read"

    # Settings & System
    SETTINGS_READ       = "settings.read"
    SETTINGS_WRITE      = "settings.write"
    AUDIT_LOG_READ      = "auditLog.read"
    SYSTEM_ADMIN        = "system.admin"

    # Kept for internal API guards (not stored in Firestore roles)
    MANAGE_USERS        = "staff.manage"
    VIEW_AUDIT_LOG      = "auditLog.read"
    VIEW_PHI            = "documents.verify"


# ── Permission matrix (mirrors your Firestore roles collection) ───────────────
ROLE_PERMISSIONS: dict[Role, Set[Permission]] = {

    Role.CLIENT: {
        Permission.CASES_READ,
        Permission.DOCUMENTS_READ,
        Permission.DOCUMENTS_UPLOAD,
        Permission.COMMUNICATIONS_READ,
        Permission.TIMELINE_READ,
    },

    Role.ADMIN_STAFF: {
        Permission.CASES_READ,
        Permission.CASES_WRITE,
        Permission.CASES_STATUS_UPDATE,
        Permission.CLIENTS_READ,
        Permission.CLIENTS_WRITE,
        Permission.DOCUMENTS_READ,
        Permission.DOCUMENTS_UPLOAD,
        Permission.TASKS_READ,
        Permission.TASKS_WRITE,
        Permission.TASKS_COMPLETE,
        Permission.COMMUNICATIONS_READ,
        Permission.COMMUNICATIONS_WRITE,
        Permission.TIMELINE_READ,
        Permission.EXPENSES_READ,
        Permission.EXPENSES_WRITE,
        Permission.DISBURSEMENTS_READ,
        Permission.STAFF_READ,
        Permission.MANAGE_USERS,        # allows user management API
    },

    Role.PARALEGAL: {
        Permission.CASES_READ,
        Permission.CASES_WRITE,
        Permission.CASES_STATUS_UPDATE,
        Permission.CLIENTS_READ,
        Permission.CLIENTS_WRITE,
        Permission.DOCUMENTS_READ,
        Permission.DOCUMENTS_UPLOAD,
        Permission.DOCUMENTS_VERIFY,
        Permission.TASKS_READ,
        Permission.TASKS_WRITE,
        Permission.TASKS_COMPLETE,
        Permission.COMMUNICATIONS_READ,
        Permission.COMMUNICATIONS_WRITE,
        Permission.TIMELINE_READ,
        Permission.EXPENSES_READ,
        Permission.EXPENSES_WRITE,
        Permission.DISBURSEMENTS_READ,
        Permission.STAFF_READ,
        Permission.REPORTS_READ,
    },

    Role.JUNIOR_PARTNER: {
        Permission.CASES_READ,
        Permission.CASES_WRITE,
        Permission.CASES_STATUS_UPDATE,
        Permission.CASES_APPROVE,
        Permission.CLIENTS_READ,
        Permission.CLIENTS_WRITE,
        Permission.DOCUMENTS_READ,
        Permission.DOCUMENTS_UPLOAD,
        Permission.DOCUMENTS_VERIFY,
        Permission.TASKS_READ,
        Permission.TASKS_WRITE,
        Permission.TASKS_COMPLETE,
        Permission.COMMUNICATIONS_READ,
        Permission.COMMUNICATIONS_WRITE,
        Permission.TIMELINE_READ,
        Permission.EXPENSES_READ,
        Permission.EXPENSES_WRITE,
        Permission.DISBURSEMENTS_READ,
        Permission.DISBURSEMENTS_WRITE,
        Permission.STAFF_READ,
        Permission.REPORTS_READ,
        Permission.ANALYTICS_READ,
        Permission.SETTINGS_READ,
        # Permission.VIEW_AUDIT_LOG,
    },

    Role.SENIOR_PARTNER: {p for p in Permission},  # all permissions

    Role.SYSTEM_ADMIN: {p for p in Permission},     # all permissions
}


# ── Core lookup ───────────────────────────────────────────────────────────────
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


# ── Guard helpers ─────────────────────────────────────────────────────────────
def require_permission(
    user: dict,
    permission: Permission,
    request: https_fn.Request | None = None,
) -> https_fn.Response | None:
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
    if has_permission(user.get("role", ""), Permission.CASES_READ):
        return True
    doc = db().collection("cases").document(case_id).get()
    if not doc.exists:
        return False
    return doc.to_dict().get("client_uid") == user.get("uid")


# ── Audit helpers ─────────────────────────────────────────────────────────────
def log_role_change(
    changed_by: str, target_uid: str, old_role: str, new_role: str
) -> None:
    write_audit_event(
        "role_change",
        changed_by=changed_by,
        target_user=target_uid,
        old_role=old_role,
        new_role=new_role,
    )
