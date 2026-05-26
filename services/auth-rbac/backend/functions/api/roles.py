"""
api/roles.py — Role permission sync endpoint (System Admin only)
================================================================
POST /syncRoles  — writes every role's permission list from the
                   in-memory ROLE_PERMISSIONS dict to the Firestore
                   `roles` collection, keeping the shared AuthMiddleware
                   in sync with rbac.py.
"""

from __future__ import annotations

from firebase_functions import https_fn
from auth.rbac import Permission, ROLE_PERMISSIONS, require_permission
from middleware.http import REGION, json_ok, json_err, handle_options, db, write_audit_event, CORS_OPTIONS
from middleware.jwt_middleware import require_auth


@https_fn.on_request(region=REGION, cors=CORS_OPTIONS)
def sync_roles_fn(req: https_fn.Request) -> https_fn.Response:
    """
    Sync ROLE_PERMISSIONS from rbac.py → Firestore `roles` collection.

    Each document is written as:
      roles/{role_value}  →  { "permissions": ["cases.read", ...] }

    Restricted to system_admin only.
    """
    early = handle_options(req)
    if early:
        return early

    if req.method != "POST":
        return json_err("Method not allowed.", 405)

    user, err = require_auth(req)
    if err:
        return err
    guard = require_permission(user, Permission.SYSTEM_ADMIN, req)
    if guard:
        return guard

    firestore = db()
    updated: list[str] = []

    for role, perms in ROLE_PERMISSIONS.items():
        # Deduplicate — enum aliases (MANAGE_USERS etc.) share a value with
        # their canonical member, so the set already collapses them.
        perm_strings = sorted({p.value for p in perms})
        firestore.collection("roles").document(role.value).set(
            {"permissions": perm_strings}
        )
        updated.append(role.value)

    write_audit_event(
        "roles_synced",
        uid=user.get("uid", "unknown"),
        roles_updated=updated,
    )

    return json_ok({
        "synced": updated,
        "total_roles": len(updated),
    })
