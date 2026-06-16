"""
app/routes/roles.py — Role and permissions management endpoints
===============================================================
  GET    /api/v1/roles                 — list roles (staff.manage)
  POST   /api/v1/roles                 — create role (system.admin)
  PUT    /api/v1/roles/{roleId}        — update role (system.admin)
  DELETE /api/v1/roles/{roleId}        — delete role (system.admin)
  GET    /api/v1/permissions           — list permissions (staff.manage)
  PUT    /api/v1/permissions           — replace registry (system.admin)
  POST   /api/v1/permissions/seed      — seed registry from roles (system.admin)
"""

from __future__ import annotations

import logging
from typing import List

from fastapi import APIRouter, HTTPException, Query, Request

from app.models.roles import (
    CreateRoleRequest,
    UpdatePermissionsRegistryRequest,
    UpdateRoleRequest,
)
from app.services.rbac_service import (
    get_all_permissions,
    get_all_roles,
    refresh_rbac_cache,
    write_audit_event,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["roles"])

_REGISTRY_COLLECTION = "permissions_registry"
_REGISTRY_DOC        = "default"


def _get_db():
    from app.utils.firestore import get_firestore_client
    return get_firestore_client()


def _load_registry() -> list | None:
    doc = _get_db().collection(_REGISTRY_COLLECTION).document(_REGISTRY_DOC).get()
    if not doc.exists:
        return None
    return (doc.to_dict() or {}).get("permissions", [])


# ── Roles ─────────────────────────────────────────────────────────────────────

@router.get("/api/v1/roles")
def list_roles(request: Request):
    return {"roles": get_all_roles()}


@router.post("/api/v1/roles", status_code=201)
def create_role(body: CreateRoleRequest, request: Request):
    user    = request.state.user
    role_id = body.roleId.strip()
    if not role_id:
        raise HTTPException(status_code=400, detail="roleId cannot be empty.")
    if not isinstance(body.permissions, list):
        raise HTTPException(status_code=400, detail="'permissions' must be an array.")

    existing = _get_db().collection("roles").document(role_id).get()
    if existing.exists:
        raise HTTPException(status_code=409, detail=f"Role '{role_id}' already exists.")

    registry = _load_registry()
    if registry is None:
        raise HTTPException(status_code=503, detail="Permissions registry has not been seeded — cannot validate permissions.")

    registry_ids = {p["id"] for p in registry if p.get("id")}
    unknown = [p for p in body.permissions if p not in registry_ids]
    if unknown:
        raise HTTPException(status_code=400, detail=f"Unknown permission(s) not in registry: {unknown}")

    _get_db().collection("roles").document(role_id).set({
        "roleId":      role_id,
        "displayName": body.displayName.strip(),
        "description": (body.description or "").strip(),
        "permissions": sorted(set(body.permissions)),
    })
    refresh_rbac_cache()
    write_audit_event(
        "role_created",
        uid=user.get("uid", "unknown"),
        role_id=role_id,
        display_name=body.displayName,
        permission_count=len(body.permissions),
    )
    return {
        "created":     True,
        "roleId":      role_id,
        "displayName": body.displayName.strip(),
        "permissions": sorted(set(body.permissions)),
    }


@router.put("/api/v1/roles/{roleId}")
def update_role(roleId: str, body: UpdateRoleRequest, request: Request):
    user = request.state.user

    role_doc = _get_db().collection("roles").document(roleId).get()
    if not role_doc.exists:
        raise HTTPException(status_code=404, detail=f"Role '{roleId}' not found.")

    updates: dict = {}
    if body.displayName is not None:
        updates["displayName"] = body.displayName.strip()
    if body.description is not None:
        updates["description"] = body.description.strip()
    if body.permissions is not None:
        if not isinstance(body.permissions, list):
            raise HTTPException(status_code=400, detail="'permissions' must be an array.")
        registry = _load_registry()
        if registry is None:
            raise HTTPException(status_code=503, detail="Permissions registry has not been seeded.")
        registry_ids = {p["id"] for p in registry if p.get("id")}
        unknown = [p for p in body.permissions if p not in registry_ids]
        if unknown:
            raise HTTPException(status_code=400, detail=f"Unknown permission(s): {unknown}")
        updates["permissions"] = sorted(set(body.permissions))

    if not updates:
        raise HTTPException(status_code=400, detail="No updatable fields provided (displayName, description, permissions).")

    _get_db().collection("roles").document(roleId).update(updates)
    refresh_rbac_cache()
    write_audit_event(
        "role_updated",
        uid=user.get("uid", "unknown"),
        role_id=roleId,
        updated_fields=list(updates.keys()),
    )
    return {"updated": True, "roleId": roleId, "updated_fields": list(updates.keys())}


@router.delete("/api/v1/roles/{roleId}")
def delete_role(roleId: str, request: Request):
    user = request.state.user

    role_doc = _get_db().collection("roles").document(roleId).get()
    if not role_doc.exists:
        raise HTTPException(status_code=404, detail=f"Role '{roleId}' not found.")

    assigned = list(_get_db().collection("staff").where("role", "==", roleId).limit(1).stream())
    if assigned:
        all_assigned = list(_get_db().collection("staff").where("role", "==", roleId).stream())
        raise HTTPException(
            status_code=409,
            detail=f"Cannot delete role '{roleId}': {len(all_assigned)} user(s) are still assigned to it.",
        )

    _get_db().collection("roles").document(roleId).delete()
    refresh_rbac_cache()
    write_audit_event("role_deleted", uid=user.get("uid", "unknown"), role_id=roleId)
    return {"deleted": True, "roleId": roleId}


# ── Permissions ───────────────────────────────────────────────────────────────

@router.get("/api/v1/permissions")
def list_permissions(
    request: Request,
    search: str = Query(default=None),
    category: str = Query(default=None),
):
    permissions = _load_registry()
    if permissions is None:
        raise HTTPException(status_code=404, detail="Permissions registry has not been seeded.")

    if category:
        permissions = [p for p in permissions if p.get("category", "") == category]
    if search:
        s = search.strip().lower()
        permissions = [
            p for p in permissions
            if s in (p.get("id") or "").lower()
            or s in (p.get("displayName") or "").lower()
            or s in (p.get("description") or "").lower()
        ]

    return {"permissions": permissions, "total": len(permissions)}


@router.put("/api/v1/permissions")
def update_permissions_registry(body: UpdatePermissionsRegistryRequest, request: Request):
    user = request.state.user
    for i, p in enumerate(body.permissions):
        if not isinstance(p, dict) or not p.get("id"):
            raise HTTPException(status_code=400, detail=f"permissions[{i}] must be an object with at least an 'id' field.")

    _get_db().collection(_REGISTRY_COLLECTION).document(_REGISTRY_DOC).set(
        {"permissions": body.permissions}
    )
    write_audit_event(
        "permissions_registry_updated",
        uid=user.get("uid", "unknown"),
        permission_count=len(body.permissions),
    )
    return {"updated": True, "total": len(body.permissions)}


@router.post("/api/v1/permissions/seed")
def seed_permissions_registry(request: Request):
    user = request.state.user

    role_permissions = get_all_permissions()
    if not role_permissions:
        raise HTTPException(status_code=404, detail="No permissions found in roles collection — ensure roles are seeded first.")

    existing_doc = _get_db().collection(_REGISTRY_COLLECTION).document(_REGISTRY_DOC).get()
    existing_map: dict[str, dict] = {}
    if existing_doc.exists:
        for entry in (existing_doc.to_dict() or {}).get("permissions", []):
            if entry.get("id"):
                existing_map[entry["id"]] = entry

    added = []
    for perm in role_permissions:
        if perm not in existing_map:
            existing_map[perm] = {"id": perm}
            added.append(perm)

    merged = sorted(existing_map.values(), key=lambda p: p["id"])
    _get_db().collection(_REGISTRY_COLLECTION).document(_REGISTRY_DOC).set(
        {"permissions": merged}
    )
    write_audit_event(
        "permissions_registry_seeded",
        uid=user.get("uid", "unknown"),
        total=len(merged),
        added=len(added),
        added_ids=added,
    )
    return {"seeded": True, "total": len(merged), "added": len(added), "added_ids": added}
