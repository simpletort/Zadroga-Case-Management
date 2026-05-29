"""
auth/rbac.py — Role-Based Access Control
=========================================
Fully database-driven. No role IDs, permission strings, display names,
or descriptions are hardcoded in this file.

Everything is read from the `roles` collection in Firestore
(simpletort-dev database). Each role document has the shape:

  {
    roleId:       "admin_staff",          ← canonical key
    displayName:  "Admin Staff",
    description:  "Front-office staff …",
    permissions:  ["cases.read", "cases.write", …]
  }

Public API
──────────
  # Cache control
  refresh_rbac_cache()                    force-reload from Firestore

  # Discovery  (everything straight from the DB)
  get_all_roles()        → List[dict]     full role objects
  get_all_role_ids()     → List[str]      sorted role ID strings
  get_all_permissions()  → List[str]      sorted, deduplicated permission strings
  get_role_meta(role_id) → dict | None    displayName + description for one role

  # Permission checks
  has_permission(role, permission) → bool
  get_role_permissions(role)       → List[str]

  # Request guards  (return 403 Response or None)
  require_permission(user, permission, request?)
  require_any(user, *permissions, request?)

  # Resource access
  check_case_access(user, case_id, read_permission)

  # Audit
  log_role_change(changed_by, target_uid, old_role, new_role)
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Dict, List, Optional

from firebase_functions import https_fn
from middleware.http import db, json_err, write_audit_event
from config import Config

logger = logging.getLogger(__name__)


# ── Cache state ───────────────────────────────────────────────────────────────

# How long (seconds) before the cache is considered stale.
# Override via Config.RBAC_CACHE_TTL (e.g. in .env / app config).
_CACHE_TTL_SECONDS: int = getattr(Config, "RBAC_CACHE_TTL", 300)

_cache_lock = threading.Lock()
_cache_loaded_at: float = 0.0  # monotonic timestamp of last successful load

# Full role metadata keyed by role ID:
#   { "admin_staff": { "roleId": "admin_staff", "displayName": "…",
#                      "description": "…", "permissions": frozenset(…) } }
_roles_cache: Dict[str, dict] = {}


# ── Cache internals ───────────────────────────────────────────────────────────

def _cache_is_stale() -> bool:
    return (time.monotonic() - _cache_loaded_at) > _CACHE_TTL_SECONDS


def _load_roles_from_firestore() -> Dict[str, dict]:
    """
    Stream every document from the `roles` collection and return a dict of:
      { canonical_role_id → { roleId, displayName, description, permissions } }

    - canonical_role_id is the `roleId` field value; falls back to doc.id.
    - permissions is stored as a frozenset internally for O(1) lookup.
    - Both canonical_role_id and doc.id are indexed when they differ so that
      lookups work regardless of which key the caller uses.

    Raises on Firestore errors so _ensure_cache_fresh can decide what to do.
    """
    firestore = db()
    docs = firestore.collection("roles").stream()
    result: Dict[str, dict] = {}

    for doc in docs:
        data = doc.to_dict() or {}

        # ── Canonical role key ────────────────────────────────────────────────
        role_id_field = data.get("roleId", "").strip()
        if role_id_field and role_id_field != doc.id:
            logger.warning(
                "roles/%s: roleId field (%r) differs from document ID — "
                "using roleId field as canonical key; consider fixing Firestore.",
                doc.id, role_id_field,
            )
        canonical_key = role_id_field or doc.id

        # ── Permission set ────────────────────────────────────────────────────
        raw_perms = data.get("permissions", [])
        if not isinstance(raw_perms, list):
            logger.warning(
                "roles/%s: 'permissions' is not a list (%r) — treating as empty",
                doc.id, type(raw_perms),
            )
            raw_perms = []

        # ── Full role record ──────────────────────────────────────────────────
        role_record = {
            "roleId":      canonical_key,
            "displayName": data.get("displayName", canonical_key),
            "description": data.get("description", ""),
            "permissions": frozenset(str(p) for p in raw_perms if p),
        }

        result[canonical_key] = role_record
        if canonical_key != doc.id:
            result[doc.id] = role_record  # also reachable by raw doc ID

        logger.debug(
            "roles/%s loaded: displayName=%r, %d permissions",
            canonical_key,
            role_record["displayName"],
            len(role_record["permissions"]),
        )

    return result


def _ensure_cache_fresh() -> None:
    """
    Refresh _roles_cache from Firestore if the TTL has elapsed.
    Thread-safe via double-checked locking.
    On a mid-run refresh failure, stale data is served and an error is logged.
    On a first-load failure, the exception is re-raised (nothing to fall back on).
    """
    global _roles_cache, _cache_loaded_at

    if not _cache_is_stale():
        return  # fast-path — safe for concurrent reads in CPython

    with _cache_lock:
        if not _cache_is_stale():
            return  # another thread refreshed while we waited

        try:
            fresh = _load_roles_from_firestore()
            _roles_cache = fresh
            _cache_loaded_at = time.monotonic()
            logger.info(
                "RBAC cache refreshed: %d roles loaded from Firestore", len(fresh)
            )
        except Exception as exc:
            if _roles_cache:
                logger.error(
                    "RBAC cache refresh failed — serving stale data: %s", exc
                )
            else:
                logger.critical(
                    "RBAC initial load failed and cache is empty: %s", exc
                )
                raise


def _role_record(role_id: str) -> dict:
    """Return the cached record for *role_id*, or an empty shell if not found."""
    _ensure_cache_fresh()
    return _roles_cache.get(role_id, {
        "roleId": role_id,
        "displayName": role_id,
        "description": "",
        "permissions": frozenset(),
    })


# ── Public cache control ──────────────────────────────────────────────────────

def refresh_rbac_cache() -> None:
    """
    Force-expire and immediately reload the RBAC cache from Firestore.
    Call this after any admin write to a roles/* document so the change takes
    effect instantly rather than waiting for the TTL to expire.

    Example:
        from auth.rbac import refresh_rbac_cache
        refresh_rbac_cache()
    """
    global _cache_loaded_at
    with _cache_lock:
        _cache_loaded_at = 0.0  # mark stale
    _ensure_cache_fresh()
    logger.info("RBAC cache force-refreshed by explicit call.")


# ── Discovery helpers ─────────────────────────────────────────────────────────

def get_all_roles() -> List[dict]:
    """
    Return a list of every role currently in Firestore, each as a dict:
      { "roleId": str, "displayName": str, "description": str,
        "permissions": List[str] }

    permissions is returned as a sorted list for easy serialisation.
    Duplicate entries (doc.id aliases) are deduplicated by roleId.

    Example:
        [
          { "roleId": "admin_staff", "displayName": "Admin Staff",
            "description": "Front-office staff …",
            "permissions": ["cases.read", "cases.write", …] },
          …
        ]
    """
    _ensure_cache_fresh()
    seen: set = set()
    roles: List[dict] = []
    for record in _roles_cache.values():
        rid = record["roleId"]
        if rid in seen:
            continue
        seen.add(rid)
        roles.append({
            "roleId":      rid,
            "displayName": record["displayName"],
            "description": record["description"],
            "permissions": sorted(record["permissions"]),
        })
    return sorted(roles, key=lambda r: r["roleId"])


def get_all_role_ids() -> List[str]:
    """
    Return a sorted list of every role ID currently in Firestore.

    Example:
        ["admin_staff", "client", "junior_partner", "paralegal",
         "senior_partner", "system_admin"]
    """
    return [r["roleId"] for r in get_all_roles()]


def get_all_permissions() -> List[str]:
    """
    Return a sorted, deduplicated list of every permission string that appears
    in any role document in Firestore.

    Useful for admin UIs and validation logic that must not hardcode strings.

    Example:
        ["analytics.read", "cases.approve", "cases.delete", "cases.read", …]
    """
    _ensure_cache_fresh()
    all_perms: set = set()
    for record in _roles_cache.values():
        all_perms.update(record["permissions"])
    return sorted(all_perms)


def get_role_meta(role_id: str) -> Optional[dict]:
    """
    Return the metadata dict for a single role (without the permissions list),
    or None if the role does not exist in Firestore.

    Example:
        { "roleId": "paralegal", "displayName": "Paralegal",
          "description": "Handles document preparation …" }
    """
    _ensure_cache_fresh()
    record = _roles_cache.get(role_id)
    if record is None:
        return None
    return {
        "roleId":      record["roleId"],
        "displayName": record["displayName"],
        "description": record["description"],
    }


# ── Core lookup ───────────────────────────────────────────────────────────────

def has_permission(role: str, permission: str) -> bool:
    """
    Return True if *role* includes *permission*.
    Both are plain strings that must match values stored in Firestore.

    Example:
        has_permission("admin_staff", "cases.read")  →  True / False
    """
    return permission in _role_record(role)["permissions"]


def get_role_permissions(role: str) -> List[str]:
    """Return a sorted list of all permission strings held by *role*."""
    return sorted(_role_record(role)["permissions"])


# ── Guard helpers ─────────────────────────────────────────────────────────────

def require_permission(
    user: dict,
    permission: str,
    request: Optional[https_fn.Request] = None,
) -> Optional[https_fn.Response]:
    """
    Return a 403 Response if the user's role lacks *permission*,
    otherwise return None (caller may proceed).

    Usage:
        err = require_permission(user, "cases.read", request)
        if err:
            return err
    """
    role = user.get("role", "")
    if not has_permission(role, permission):
        write_audit_event(
            "permission_denied",
            uid=user.get("uid", "unknown"),
            role=role,
            required_permission=permission,
            path=getattr(request, "path", ""),
        )
        return json_err("Forbidden: insufficient permissions.", 403)
    return None


def require_any(
    user: dict,
    *permissions: str,
    request: Optional[https_fn.Request] = None,
) -> Optional[https_fn.Response]:
    """
    Return a 403 Response if the user's role lacks ALL of *permissions*
    (the user needs at least one to pass). Returns None if any match.

    Usage:
        err = require_any(user, "cases.approve", "cases.write", request=request)
        if err:
            return err
    """
    role = user.get("role", "")
    if not permissions or not any(has_permission(role, p) for p in permissions):
        write_audit_event(
            "permission_denied",
            uid=user.get("uid", "unknown"),
            role=role,
            required_permission=f"any_of:{list(permissions)}",
            path=getattr(request, "path", ""),
        )
        return json_err("Forbidden: insufficient permissions.", 403)
    return None


# ── Case access check ─────────────────────────────────────────────────────────

def check_case_access(user: dict, case_id: str, read_permission: str) -> bool:
    """
    Return True if *user* may access *case_id*.

    *read_permission* is the permission string that grants broad case-read
    access (e.g. "cases.read") — passed in by the caller so this function
    contains no hardcoded permission strings.

    Logic:
    - If the user's role has *read_permission* they can access any case.
    - Otherwise they can only access cases where case.client_uid == user.uid
      (i.e. their own cases).

    Usage:
        allowed = check_case_access(user, case_id, "cases.read")
    """
    if has_permission(user.get("role", ""), read_permission):
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








# """
# auth/rbac.py — Role-Based Access Control
# =========================================
# Permission strings aligned to the existing `roles` collection in Firestore
# (simpletort-dev database) which uses dot-notation e.g. "cases.read".

# Role documents in Firestore:
#   roles/admin_staff
#   roles/junior_partner
#   roles/paralegal
#   roles/senior_partner
#   roles/system_admin
# """

# from __future__ import annotations

# import logging
# from enum import Enum
# from typing import Set

# from firebase_functions import https_fn
# from middleware.http import db, json_err, write_audit_event
# from config import Config
# logger = logging.getLogger(__name__)

# # ── Roles ─────────────────────────────────────────────────────────────────────

# class Role(str, Enum):
#     ADMIN_STAFF    = "admin_staff"
#     PARALEGAL      = "paralegal"
#     JUNIOR_PARTNER = "junior_partner"
#     SENIOR_PARTNER = "senior_partner"
#     SYSTEM_ADMIN   = "system_admin"
#     CLIENT         = "client"


# # ── Permissions — dot-notation matching your Firestore roles collection ────────
# class Permission(str, Enum):
#     # Cases
#     CASES_READ          = "cases.read"
#     CASES_WRITE         = "cases.write"
#     CASES_STATUS_UPDATE = "cases.status.update"
#     CASES_APPROVE       = "cases.approve"
#     CASES_DELETE        = "cases.delete"

#     # Clients
#     CLIENTS_READ        = "clients.read"
#     CLIENTS_WRITE       = "clients.write"

#     # Documents
#     DOCUMENTS_READ      = "documents.read"
#     DOCUMENTS_UPLOAD    = "documents.upload"
#     DOCUMENTS_VERIFY    = "documents.verify"
#     DOCUMENTS_OVERRIDE  = "documents.override"

#     # Tasks
#     TASKS_READ          = "tasks.read"
#     TASKS_WRITE         = "tasks.write"
#     TASKS_COMPLETE      = "tasks.complete"
#     TASKS_ASSIGN        = "tasks.assign"   # paralegal+ — reassign any task
#     TASKS_SKIP          = "tasks.skip"     # junior_partner+ — skip a task with reason
#     TASKS_DELETE        = "tasks.delete"   # senior_partner+ — hard delete a task

#     # Communications
#     COMMUNICATIONS_READ  = "communications.read"
#     COMMUNICATIONS_WRITE = "communications.write"

#     # Timeline
#     TIMELINE_READ       = "timeline.read"

#     # Expenses & Disbursements
#     EXPENSES_READ       = "expenses.read"
#     EXPENSES_WRITE      = "expenses.write"
#     DISBURSEMENTS_READ  = "disbursements.read"
#     DISBURSEMENTS_WRITE = "disbursements.write"
#     DISBURSEMENTS_APPROVE = "disbursements.approve"

#     # Staff & Users
#     STAFF_READ          = "staff.read"
#     STAFF_WRITE         = "staff.write"
#     STAFF_MANAGE        = "staff.manage"

#     # Reports & Analytics
#     REPORTS_READ        = "reports.read"
#     ANALYTICS_READ      = "analytics.read"

#     # Settings & System
#     SETTINGS_READ       = "settings.read"
#     SETTINGS_WRITE      = "settings.write"
#     AUDIT_LOG_READ      = "auditLog.read"
#     SYSTEM_ADMIN        = "system.admin"

#     # Storage
#     STORAGE_SIGNED_URL      = "storage.signed_url"
#     STORAGE_METADATA_READ   = "storage.metadata.read"
#     STORAGE_LIFECYCLE_READ  = "storage.lifecycle.read"
#     STORAGE_LIFECYCLE_WRITE = "storage.lifecycle.write"
#     STORAGE_HOLD_WRITE      = "storage.hold.write"
#     STORAGE_UPLOAD_WRITE    = "storage.upload.write"
#     STORAGE_UPLOAD_READ     = "storage.upload.read"
#     STORAGE_DOCUMENTS_READ  = "storage.documents.read"
#     STORAGE_DOCUMENTS_WRITE = "storage.documents.write"

#     # Kept for internal API guards (not stored in Firestore roles)
#     MANAGE_USERS        = "staff.manage"
#     VIEW_AUDIT_LOG      = "auditLog.read"
#     VIEW_PHI            = "documents.verify"


# # ── Permission matrix (mirrors your Firestore roles collection) ───────────────
# ROLE_PERMISSIONS: dict[Role, Set[Permission]] = {

#     Role.CLIENT: {
#         Permission.CASES_READ,
#         Permission.DOCUMENTS_READ,
#         Permission.DOCUMENTS_UPLOAD,
#         Permission.COMMUNICATIONS_READ,
#         Permission.TIMELINE_READ,
#         Permission.STORAGE_SIGNED_URL,
#         Permission.STORAGE_METADATA_READ,
#         Permission.STORAGE_UPLOAD_WRITE,
#         Permission.STORAGE_UPLOAD_READ,
#         Permission.STORAGE_DOCUMENTS_READ,
#     },

#     Role.ADMIN_STAFF: {
#         Permission.CASES_READ,
#         Permission.CASES_WRITE,
#         Permission.CASES_STATUS_UPDATE,
#         Permission.CLIENTS_READ,
#         Permission.CLIENTS_WRITE,
#         Permission.DOCUMENTS_READ,
#         Permission.DOCUMENTS_UPLOAD,
#         Permission.TASKS_READ,
#         Permission.TASKS_WRITE,
#         Permission.TASKS_COMPLETE,
#         Permission.COMMUNICATIONS_READ,
#         Permission.COMMUNICATIONS_WRITE,
#         Permission.TIMELINE_READ,
#         Permission.EXPENSES_READ,
#         Permission.EXPENSES_WRITE,
#         Permission.DISBURSEMENTS_READ,
#         Permission.STAFF_READ,
#         Permission.MANAGE_USERS,        # allows user management API
#         Permission.STORAGE_SIGNED_URL,
#         Permission.STORAGE_METADATA_READ,
#         Permission.STORAGE_UPLOAD_WRITE,
#         Permission.STORAGE_UPLOAD_READ,
#         Permission.STORAGE_DOCUMENTS_READ,
#         Permission.STORAGE_DOCUMENTS_WRITE,
#     },

#     Role.PARALEGAL: {
#         Permission.CASES_READ,
#         Permission.CASES_WRITE,
#         Permission.CASES_STATUS_UPDATE,
#         Permission.CLIENTS_READ,
#         Permission.CLIENTS_WRITE,
#         Permission.DOCUMENTS_READ,
#         Permission.DOCUMENTS_UPLOAD,
#         Permission.DOCUMENTS_VERIFY,
#         Permission.TASKS_READ,
#         Permission.TASKS_WRITE,
#         Permission.TASKS_COMPLETE,
#         Permission.TASKS_ASSIGN,
#         Permission.COMMUNICATIONS_READ,
#         Permission.COMMUNICATIONS_WRITE,
#         Permission.TIMELINE_READ,
#         Permission.EXPENSES_READ,
#         Permission.EXPENSES_WRITE,
#         Permission.DISBURSEMENTS_READ,
#         Permission.STAFF_READ,
#         Permission.REPORTS_READ,
#         Permission.STORAGE_SIGNED_URL,
#         Permission.STORAGE_METADATA_READ,
#         Permission.STORAGE_UPLOAD_WRITE,
#         Permission.STORAGE_UPLOAD_READ,
#         Permission.STORAGE_DOCUMENTS_READ,
#         Permission.STORAGE_DOCUMENTS_WRITE,
#     },

#     Role.JUNIOR_PARTNER: {
#         Permission.CASES_READ,
#         Permission.CASES_WRITE,
#         Permission.CASES_STATUS_UPDATE,
#         Permission.CASES_APPROVE,
#         Permission.CLIENTS_READ,
#         Permission.CLIENTS_WRITE,
#         Permission.DOCUMENTS_READ,
#         Permission.DOCUMENTS_UPLOAD,
#         Permission.DOCUMENTS_VERIFY,
#         Permission.TASKS_READ,
#         Permission.TASKS_WRITE,
#         Permission.TASKS_COMPLETE,
#         Permission.TASKS_ASSIGN,
#         Permission.TASKS_SKIP,
#         Permission.COMMUNICATIONS_READ,
#         Permission.COMMUNICATIONS_WRITE,
#         Permission.TIMELINE_READ,
#         Permission.EXPENSES_READ,
#         Permission.EXPENSES_WRITE,
#         Permission.DISBURSEMENTS_READ,
#         Permission.DISBURSEMENTS_WRITE,
#         Permission.STAFF_READ,
#         Permission.REPORTS_READ,
#         Permission.ANALYTICS_READ,
#         Permission.SETTINGS_READ,
#         Permission.STORAGE_SIGNED_URL,
#         Permission.STORAGE_METADATA_READ,
#         Permission.STORAGE_UPLOAD_WRITE,
#         Permission.STORAGE_UPLOAD_READ,
#         Permission.STORAGE_DOCUMENTS_READ,
#         Permission.STORAGE_DOCUMENTS_WRITE,
#         Permission.STORAGE_LIFECYCLE_READ,
#         Permission.STORAGE_HOLD_WRITE,
#     },

#     Role.SENIOR_PARTNER: {p for p in Permission},  # all permissions

#     Role.SYSTEM_ADMIN: {p for p in Permission},     # all permissions
# }


# # ── Core lookup ───────────────────────────────────────────────────────────────
# def has_permission(role: str, permission: Permission) -> bool:
#     try:
#         r = Role(role)
#     except ValueError:
#         return False
#     return permission in ROLE_PERMISSIONS.get(r, set())


# def get_role_permissions(role: str) -> list[str]:
#     try:
#         r = Role(role)
#     except ValueError:
#         return []
#     return [p.value for p in ROLE_PERMISSIONS.get(r, set())]


# # ── Guard helpers ─────────────────────────────────────────────────────────────
# def require_permission(
#     user: dict,
#     permission: Permission,
#     request: https_fn.Request | None = None,
# ) -> https_fn.Response | None:
#     if not has_permission(user.get("role", ""), permission):
#         write_audit_event(
#             "permission_denied",
#             uid=user.get("uid", "unknown"),
#             role=user.get("role", "unknown"),
#             required_permission=str(permission),
#             path=getattr(request, "path", ""),
#         )
#         return json_err("Forbidden: insufficient permissions.", 403)
#     return None


# def require_any(
#     user: dict,
#     *permissions: Permission,
#     request: https_fn.Request | None = None,
# ) -> https_fn.Response | None:
#     if not permissions or not any(
#         has_permission(user.get("role", ""), p) for p in permissions
#     ):
#         write_audit_event(
#             "permission_denied",
#             uid=user.get("uid", "unknown"),
#             role=user.get("role", "unknown"),
#             required_permission=f"any_of:{[p.value for p in permissions]}",
#             path=getattr(request, "path", ""),
#         )
#         return json_err("Forbidden: insufficient permissions.", 403)
#     return None


# # ── Case access check ─────────────────────────────────────────────────────────
# def check_case_access(user: dict, case_id: str) -> bool:
#     if has_permission(user.get("role", ""), Permission.CASES_READ):
#         return True
#     doc = db().collection("cases").document(case_id).get()
#     if not doc.exists:
#         return False
#     return doc.to_dict().get("client_uid") == user.get("uid")


# # ── Audit helpers ─────────────────────────────────────────────────────────────
# def log_role_change(
#     changed_by: str, target_uid: str, old_role: str, new_role: str
# ) -> None:
#     write_audit_event(
#         "role_change",
#         changed_by=changed_by,
#         target_user=target_uid,
#         old_role=old_role,
#         new_role=new_role,
#     )
