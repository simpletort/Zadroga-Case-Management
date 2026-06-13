"""
api/roles.py — Role and permissions management endpoints
=========================================================
  list_permissions_fn            GET    /list_permissions_fn
  update_permissions_registry_fn PUT    /update_permissions_registry_fn
  seed_permissions_registry_fn   POST   /seed_permissions_registry_fn
  list_roles_fn                  GET    /list_roles_fn
  create_role_fn                 POST   /create_role_fn
  delete_role_fn                 DELETE /delete_role_fn?roleId=xxx

Role assignment (assigning a role to a user) is handled by the existing
PUT /updateUser endpoint in api/users.py — no separate function needed.

All role/permissions writes are restricted to system_admin (permission: system.admin).
Read endpoints require staff.manage.
"""

from __future__ import annotations

from firebase_functions import https_fn
from auth.rbac import (
    require_permission,
    get_all_roles,
    get_all_permissions,
    refresh_rbac_cache,
)
from middleware.http import (
    REGION,
    json_ok,
    json_err,
    handle_options,
    db,
    write_audit_event,
)
from middleware.jwt_middleware import require_auth

_REGISTRY_COLLECTION = "permissions_registry"
_REGISTRY_DOC        = "default"


def _load_registry() -> list[dict] | None:
    doc = db().collection(_REGISTRY_COLLECTION).document(_REGISTRY_DOC).get()
    if not doc.exists:
        return None
    return (doc.to_dict() or {}).get("permissions", [])


# ── GET /list_permissions_fn ──────────────────────────────────────────────────

@https_fn.on_request(region=REGION)
def list_permissions_fn(req: https_fn.Request) -> https_fn.Response:
    """
    Returns all permissions from the Firestore registry.
    Optional query params:
      ?search=<text>    case-insensitive substring on id / displayName / description
      ?category=<text>  exact match on category
    """
    early = handle_options(req)
    if early:
        return early

    user, err = require_auth(req)
    if err:
        return err
    guard = require_permission(user, "staff.manage", req)
    if guard:
        return guard

    permissions = _load_registry()
    if permissions is None:
        return json_err("Permissions registry has not been seeded.", 404)

    search   = (req.args.get("search") or "").strip().lower()
    category = (req.args.get("category") or "").strip()

    if category:
        permissions = [p for p in permissions if p.get("category", "") == category]

    if search:
        permissions = [
            p for p in permissions
            if search in (p.get("id") or "").lower()
            or search in (p.get("displayName") or "").lower()
            or search in (p.get("description") or "").lower()
        ]

    return json_ok({"permissions": permissions, "total": len(permissions)})


# ── PUT /update_permissions_registry_fn ──────────────────────────────────────

@https_fn.on_request(region=REGION)
def update_permissions_registry_fn(req: https_fn.Request) -> https_fn.Response:
    """Replace the entire permissions registry document. system_admin only."""
    early = handle_options(req)
    if early:
        return early

    if req.method != "PUT":
        return json_err("Method not allowed.", 405)

    user, err = require_auth(req)
    if err:
        return err
    guard = require_permission(user, "system.admin", req)
    if guard:
        return guard

    data = req.get_json(silent=True) or {}
    raw_permissions = data.get("permissions")
    if not isinstance(raw_permissions, list):
        return json_err("'permissions' must be an array.", 400)

    for i, p in enumerate(raw_permissions):
        if not isinstance(p, dict) or not p.get("id"):
            return json_err(f"permissions[{i}] must be an object with at least an 'id' field.", 400)

    db().collection(_REGISTRY_COLLECTION).document(_REGISTRY_DOC).set(
        {"permissions": raw_permissions}
    )

    write_audit_event(
        "permissions_registry_updated",
        uid=user.get("uid", "unknown"),
        permission_count=len(raw_permissions),
    )

    return json_ok({"updated": True, "total": len(raw_permissions)})


# ── GET /list_roles_fn ────────────────────────────────────────────────────────

# ── POST /seed_permissions_registry_fn ───────────────────────────────────────

@https_fn.on_request(region=REGION)
def seed_permissions_registry_fn(req: https_fn.Request) -> https_fn.Response:
    """
    Auto-populate the permissions registry from existing role documents.

    Reads all unique permission strings across every roles/* document via
    get_all_permissions(), then merges them into permissions_registry/default:
      - Permissions already in the registry keep their existing metadata
        (displayName, category, description).
      - Permissions not yet in the registry are added as { "id": perm_string }.

    This is a bootstrap/seed operation — run once after deploying, or again
    after creating new roles that introduce new permission strings.
    system_admin only.
    """
    early = handle_options(req)
    if early:
        return early

    if req.method != "POST":
        return json_err("Method not allowed.", 405)

    user, err = require_auth(req)
    if err:
        return err
    guard = require_permission(user, "system.admin", req)
    if guard:
        return guard

    # Collect all unique permission strings from roles collection
    role_permissions = get_all_permissions()
    if not role_permissions:
        return json_err("No permissions found in roles collection — ensure roles are seeded first.", 404)

    # Load existing registry to preserve metadata
    existing_doc = db().collection(_REGISTRY_COLLECTION).document(_REGISTRY_DOC).get()
    existing_map: dict[str, dict] = {}
    if existing_doc.exists:
        for entry in (existing_doc.to_dict() or {}).get("permissions", []):
            if entry.get("id"):
                existing_map[entry["id"]] = entry

    # Merge: keep existing metadata, add stub entries for new permissions
    added = []
    for perm in role_permissions:
        if perm not in existing_map:
            existing_map[perm] = {"id": perm}
            added.append(perm)

    merged = sorted(existing_map.values(), key=lambda p: p["id"])

    db().collection(_REGISTRY_COLLECTION).document(_REGISTRY_DOC).set(
        {"permissions": merged}
    )

    write_audit_event(
        "permissions_registry_seeded",
        uid=user.get("uid", "unknown"),
        total=len(merged),
        added=len(added),
        added_ids=added,
    )

    return json_ok({
        "seeded":  True,
        "total":   len(merged),
        "added":   len(added),
        "added_ids": added,
    })


# ── GET /list_roles_fn ────────────────────────────────────────────────────────

@https_fn.on_request(region=REGION)
def list_roles_fn(req: https_fn.Request) -> https_fn.Response:
    """Return all roles from the Firestore roles collection. Requires staff.manage."""
    early = handle_options(req)
    if early:
        return early

    user, err = require_auth(req)
    if err:
        return err
    guard = require_permission(user, "staff.manage", req)
    if guard:
        return guard

    return json_ok({"roles": get_all_roles()})


# ── POST /create_role_fn ──────────────────────────────────────────────────────

@https_fn.on_request(region=REGION)
def create_role_fn(req: https_fn.Request) -> https_fn.Response:
    """
    Create a new role in Firestore.
    Body: { roleId, displayName, description?, permissions: [...] }
    All permission IDs must exist in the registry.
    system_admin only.
    """
    early = handle_options(req)
    if early:
        return early

    if req.method != "POST":
        return json_err("Method not allowed.", 405)

    user, err = require_auth(req)
    if err:
        return err
    guard = require_permission(user, "system.admin", req)
    if guard:
        return guard

    data = req.get_json(silent=True) or {}
    missing = [f for f in ["roleId", "displayName", "permissions"] if not data.get(f) and data.get(f) != []]
    if missing:
        return json_err(f"Missing required fields: {missing}", 400)

    role_id      = str(data["roleId"]).strip()
    display_name = str(data["displayName"]).strip()
    description  = str(data.get("description", "")).strip()
    permissions  = data["permissions"]

    if not role_id:
        return json_err("roleId cannot be empty.", 400)
    if not isinstance(permissions, list):
        return json_err("'permissions' must be an array.", 400)

    # Guard: role must not already exist
    existing = db().collection("roles").document(role_id).get()
    if existing.exists:
        return json_err(f"Role '{role_id}' already exists.", 409)

    # Guard: all permissions must be in the registry
    registry = _load_registry()
    if registry is None:
        return json_err("Permissions registry has not been seeded — cannot validate permissions.", 503)

    registry_ids = {p["id"] for p in registry if p.get("id")}
    unknown = [p for p in permissions if p not in registry_ids]
    if unknown:
        return json_err(f"Unknown permission(s) not in registry: {unknown}", 400)

    db().collection("roles").document(role_id).set({
        "roleId":      role_id,
        "displayName": display_name,
        "description": description,
        "permissions": sorted(set(permissions)),
    })

    refresh_rbac_cache()

    write_audit_event(
        "role_created",
        uid=user.get("uid", "unknown"),
        role_id=role_id,
        display_name=display_name,
        permission_count=len(permissions),
    )

    return json_ok({
        "created":    True,
        "roleId":     role_id,
        "displayName": display_name,
        "permissions": sorted(set(permissions)),
    }, 201)


# ── DELETE /delete_role_fn ────────────────────────────────────────────────────

@https_fn.on_request(region=REGION)
def delete_role_fn(req: https_fn.Request) -> https_fn.Response:
    """
    Hard-delete a role from Firestore.
    Blocked with 409 if any staff user is currently assigned this role.
    system_admin only.
    """
    early = handle_options(req)
    if early:
        return early

    if req.method != "DELETE":
        return json_err("Method not allowed.", 405)

    user, err = require_auth(req)
    if err:
        return err
    guard = require_permission(user, "system.admin", req)
    if guard:
        return guard

    role_id = (req.args.get("roleId") or "").strip()
    if not role_id:
        return json_err("roleId query param required.", 400)

    role_doc = db().collection("roles").document(role_id).get()
    if not role_doc.exists:
        return json_err(f"Role '{role_id}' not found.", 404)

    # Check no active staff user is assigned this role
    assigned = list(
        db().collection("staff").where("role", "==", role_id).limit(1).stream()
    )
    if assigned:
        # Count all assigned users for the error message (separate query — limit(1) was just for existence check)
        all_assigned = list(
            db().collection("staff").where("role", "==", role_id).stream()
        )
        return json_err(
            f"Cannot delete role '{role_id}': {len(all_assigned)} user(s) are still assigned to it.",
            409,
        )

    db().collection("roles").document(role_id).delete()
    refresh_rbac_cache()

    write_audit_event(
        "role_deleted",
        uid=user.get("uid", "unknown"),
        role_id=role_id,
    )

    return json_ok({"deleted": True, "roleId": role_id})
