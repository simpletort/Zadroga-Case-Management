"""
app/routes/users.py — User management endpoints
================================================
  POST   /api/v1/users          — create user (staff.manage)
  GET    /api/v1/users          — list users (staff.manage)
  GET    /api/v1/users/{uid}    — get user (staff.manage or own uid)
  PUT    /api/v1/users/{uid}    — update user (staff.manage for others / role changes)
  DELETE /api/v1/users/{uid}    — delete user (staff.manage)
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Query, Request
from firebase_admin import auth, firestore as _fs_admin
from google.cloud.firestore_v1 import Query as FSQuery

from app.models.users import CreateUserRequest, UpdateUserRequest
from app.services.auth_service import create_user as _create_user
from app.services.rbac_service import (
    has_permission,
    log_role_change,
    serialise_doc,
    write_audit_event,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/users", tags=["users"])

_ACTIVE_STATUSES = [
    "Pending Paralegal Review",
    "Pending Attorney Review",
    "Approved for Filing",
    "VCF - Submitted",
]


def _get_db():
    from app.utils.firestore import get_firestore_client
    return get_firestore_client()


def _active_case_count(uid: str) -> int:
    try:
        db = _get_db()
        paralegal = db.collection("cases").where("assignment.assignedParalegal", "==", uid).where("status", "in", _ACTIVE_STATUSES).stream()
        attorney  = db.collection("cases").where("assignment.assignedAttorney",  "==", uid).where("status", "in", _ACTIVE_STATUSES).stream()
        return sum(1 for _ in paralegal) + sum(1 for _ in attorney)
    except Exception as exc:
        logger.warning("activeCaseCount query failed for uid=%s: %s", uid, exc)
        return 0


def _max_caseload() -> int:
    doc = _get_db().collection("firmSettings").document("default").get()
    return (doc.to_dict() or {}).get("defaultMaxCaseload", 20) if doc.exists else 20


@router.post("", status_code=201)
def create_user(body: CreateUserRequest, request: Request):
    user = request.state.user
    try:
        new_user = _create_user(
            email=body.email,
            password=body.password,
            display_name=body.display_name,
            role=body.role,
            portal_token=body.portal_token,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    return {"success": True, "user": new_user}


@router.get("")
def list_users(
    request: Request,
    role: str = Query(default=None),
    status: str = Query(default=None),
    search: str = Query(default=None),
    page_size: int = Query(default=20, le=100),
    cursor: str = Query(default=None),
):
    db = _get_db()
    col   = db.collection("staff")
    query = col

    if role:
        query = query.where("role", "==", role)
    if status:
        query = query.where("isActive", "==", (status == "active"))

    query = query.order_by("createdAt", direction=FSQuery.DESCENDING)

    if cursor:
        cursor_doc = col.document(cursor).get()
        if cursor_doc.exists:
            query = query.start_after(cursor_doc)

    query    = query.limit(page_size + 1)
    docs     = list(query.stream())
    has_more = len(docs) > page_size
    docs     = docs[:page_size]

    max_caseload = _max_caseload()
    search_lower = (search or "").strip().lower()
    users = []
    for doc in docs:
        d = serialise_doc(doc.to_dict(), strip_phi=True)
        if search_lower:
            if search_lower not in (d.get("displayName") or "").lower() and search_lower not in (d.get("email") or "").lower():
                continue
        uid = d.get("userId", "")
        d["activeCaseCount"] = _active_case_count(uid)
        d["maxCaseload"]     = max_caseload
        users.append(d)

    return {
        "users":       users,
        "page_size":   page_size,
        "has_more":    has_more,
        "next_cursor": docs[-1].id if has_more and docs else None,
    }


@router.get("/{uid}")
def get_user(uid: str, request: Request):
    caller      = request.state.user
    caller_uid  = caller.get("uid")
    caller_role = caller.get("role", "")

    if uid != caller_uid and not has_permission(caller_role, "staff.manage"):
        raise HTTPException(status_code=403, detail="Forbidden.")

    docs = list(_get_db().collection("staff").where("userId", "==", uid).stream())
    if not docs:
        raise HTTPException(status_code=404, detail="User not found.")

    strip_phi = not has_permission(caller_role, "documents.verify")
    d = serialise_doc(docs[0].to_dict(), strip_phi=strip_phi)
    d["activeCaseCount"] = _active_case_count(uid)
    d["maxCaseload"]     = _max_caseload()
    return {"user": d}


@router.put("/{uid}")
def update_user(uid: str, body: UpdateUserRequest, request: Request):
    caller      = request.state.user
    caller_uid  = caller.get("uid")
    caller_role = caller.get("role", "")

    if uid != caller_uid and not has_permission(caller_role, "staff.manage"):
        raise HTTPException(status_code=403, detail="Forbidden.")

    staff_docs = list(_get_db().collection("staff").where("userId", "==", uid).stream())
    if not staff_docs:
        raise HTTPException(status_code=404, detail="User not found.")

    ref     = staff_docs[0].reference
    current = staff_docs[0].to_dict()
    is_admin = has_permission(caller_role, "staff.manage")

    updates: dict = {}
    if body.displayName is not None:
        updates["displayName"] = body.displayName
    if body.googleWorkspaceId is not None:
        updates["googleWorkspaceId"] = body.googleWorkspaceId
    if is_admin:
        if body.role is not None:
            updates["role"] = body.role
        if body.isActive is not None:
            updates["isActive"] = body.isActive

    if not updates:
        raise HTTPException(status_code=400, detail="No updatable fields provided.")

    if "role" in updates:
        old_role = current.get("role", "")
        new_role = updates["role"]
        if old_role != new_role:
            try:
                auth.set_custom_user_claims(uid, {"role": new_role, "active": True})
            except Exception as exc:
                logger.warning("set_custom_user_claims failed for uid=%s: %s", uid, exc)
            log_role_change(caller_uid, uid, old_role, new_role)

    if "isActive" in updates:
        try:
            auth.update_user(uid, disabled=not updates["isActive"])
        except Exception as exc:
            logger.warning("auth.update_user failed for uid=%s: %s", uid, exc)

    updates["updatedAt"] = _fs_admin.SERVER_TIMESTAMP
    ref.update(updates)
    return {"success": True, "updated_fields": list(updates.keys())}


@router.delete("/{uid}")
def delete_user(uid: str, request: Request):
    staff_docs = list(_get_db().collection("staff").where("userId", "==", uid).stream())
    if not staff_docs:
        raise HTTPException(status_code=404, detail="User not found.")

    staff_docs[0].reference.delete()
    try:
        auth.delete_user(uid)
    except Exception as exc:
        logger.warning("Firebase Auth delete failed for uid=%s: %s", uid, exc)

    write_audit_event(
        "user_deleted",
        target_uid=uid,
        performed_by=request.state.user.get("uid"),
    )
    return {"success": True, "message": f"User {uid} deleted."}
