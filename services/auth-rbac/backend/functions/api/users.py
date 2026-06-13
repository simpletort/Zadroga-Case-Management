"""
api/users.py — User management HTTP endpoints
==============================================
  create_user_fn   POST   /createUser
  list_users_fn    GET    /listUsers
  get_user_fn      GET    /getUser?uid=xxx
  update_user_fn   PUT    /updateUser
  delete_user_fn   DELETE /deleteUser?uid=xxx

Changes from original:
  Refactor — handle_options()  replaces 5 identical OPTIONS if-blocks.
             serialise_doc()   replaces 3 separate timestamp-conversion loops
                               and 2 separate inline PHI-strip loops.
             write_audit_event() replaces inline audit_log.add() in delete_user_fn.
             db()              replaces fs_admin.client() throughout.
             REGION            imported from middleware/http.py (was copy-pasted).
"""

from __future__ import annotations

from firebase_functions import https_fn
from firebase_admin import auth, firestore as fs_admin
from config import Config
from auth.rbac import require_permission, has_permission, log_role_change
from auth.auth_service import create_user as _create_user
from middleware.http import REGION, json_ok, json_err, handle_options, db, serialise_doc, write_audit_event

from middleware.jwt_middleware import require_auth


# ── POST /createUser ──────────────────────────────────────────────────────────
@https_fn.on_request(region=REGION)
def create_user_fn(req: https_fn.Request) -> https_fn.Response:
    early = handle_options(req)
    if early:
        return early

    user, err = require_auth(req)
    if err:
        return err
    guard = require_permission(user, "staff.manage", req)
    if guard:
        return guard

    data    = req.get_json(silent=True) or {}
    missing = [f for f in ["email", "password", "display_name", "role"] if not data.get(f)]
    if missing:
        return json_err(f"Missing fields: {missing}", 400)

    requested_role = data["role"]
    caller_role    = user.get("role", "")
    if requested_role != "client" and caller_role not in ("admin_staff", "senior_partner"):
        return json_err("Only Admin or Senior Partner can assign staff roles.", 403)

    try:
        new_user = _create_user(
            email=data["email"],
            password=data["password"],
            display_name=data["display_name"],
            role=requested_role,
            portal_token=data.get("portal_token"),
        )
        return json_ok({"success": True, "user": new_user}, 201)
    except ValueError as exc:
        return json_err(str(exc), 400)
    except Exception as exc:
        return json_err(str(exc), 500)


# ── GET /listUsers ────────────────────────────────────────────────────────────
@https_fn.on_request(region=REGION)
def list_users_fn(req: https_fn.Request) -> https_fn.Response:
    early = handle_options(req)
    if early:
        return early

    user, err = require_auth(req)
    if err:
        return err
    guard = require_permission(user, "staff.manage", req)
    if guard:
        return guard

    col           = db().collection("staff")
    role_filter   = req.args.get("role")
    status_filter = req.args.get("status")
    search        = (req.args.get("search") or "").strip().lower()
    page_size     = min(int(req.args.get("page_size", 20)), 100)
    cursor_id     = req.args.get("cursor")

    query = col
    if role_filter:
        query = query.where("role", "==", role_filter)
    if status_filter:
        query = query.where("isActive", "==", (status_filter == "active"))

    query = query.order_by("createdAt", direction=fs_admin.Query.DESCENDING)

    if cursor_id:
        cursor_doc = col.document(cursor_id).get()
        if cursor_doc.exists:
            query = query.start_after(cursor_doc)

    query    = query.limit(page_size + 1)
    docs     = list(query.stream())
    has_more = len(docs) > page_size
    docs     = docs[:page_size]

    # Fetch maxCaseload once from firmSettings for all users
    firm_doc = db().collection("firmSettings").document("default").get()
    default_max_caseload = (firm_doc.to_dict() or {}).get("defaultMaxCaseload", 20) if firm_doc.exists else 20

    users = []
    for doc in docs:
        d = serialise_doc(doc.to_dict(), strip_phi=True)
        if search:
            name  = (d.get("displayName") or "").lower()
            email = (d.get("email") or "").lower()
            if search not in name and search not in email:
                continue
        # Computed: activeCaseCount per user
        # Computed: activeCaseCount per user
        uid = d.get("userId", "")
        active_statuses = [
            "Pending Paralegal Review",
            "Pending Attorney Review",
            "Approved for Filing",
            "VCF - Submitted",
        ]
        paralegal_cases = (
            db().collection("cases")
            .where("assignment.assignedParalegal", "==", uid)
            .where("status", "in", active_statuses)
            .stream()
        )
        attorney_cases = (
            db().collection("cases")
            .where("assignment.assignedAttorney", "==", uid)
            .where("status", "in", active_statuses)
            .stream()
        )
        d["activeCaseCount"] = sum(1 for _ in paralegal_cases) + sum(1 for _ in attorney_cases)
        d["maxCaseload"]     = default_max_caseload
        users.append(d)

    return json_ok({
        "users":       users,
        "page_size":   page_size,
        "has_more":    has_more,
        "next_cursor": docs[-1].id if has_more and docs else None,
    })


# ── GET /getUser?uid=xxx ──────────────────────────────────────────────────────
@https_fn.on_request(region=REGION)
def get_user_fn(req: https_fn.Request) -> https_fn.Response:
    early = handle_options(req)
    if early:
        return early

    user, err = require_auth(req)
    if err:
        return err

    target_uid  = req.args.get("uid")
    caller_uid  = user.get("uid")
    caller_role = user.get("role", "")

    if not target_uid:
        return json_err("uid query param required", 400)
    if target_uid != caller_uid and not has_permission(caller_role, "staff.manage"):
        return json_err("Forbidden.", 403)

    # staff docs use userId field
    docs = list(db().collection("staff").where("userId", "==", target_uid).stream())
    if not docs:
        return json_err("User not found.", 404)

    strip_phi = not has_permission(caller_role, "documents.verify")
    d = serialise_doc(docs[0].to_dict(), strip_phi=strip_phi)

    # Computed: activeCaseCount — open cases assigned to this user
    # Computed: activeCaseCount — open cases assigned to this user
    active_statuses = [
        "Pending Paralegal Review",
        "Pending Attorney Review",
        "Approved for Filing",
        "VCF - Submitted",
    ]
    paralegal_cases = (
        db().collection("cases")
        .where("assignment.assignedParalegal", "==", target_uid)
        .where("status", "in", active_statuses)
        .stream()
    )
    attorney_cases = (
        db().collection("cases")
        .where("assignment.assignedAttorney", "==", target_uid)
        .where("status", "in", active_statuses)
        .stream()
    )
    d["activeCaseCount"] = sum(1 for _ in paralegal_cases) + sum(1 for _ in attorney_cases)

    # Computed: maxCaseload — from firmSettings, fallback 20
    firm_doc = db().collection("firmSettings").document("default").get()
    d["maxCaseload"] = (firm_doc.to_dict() or {}).get("defaultMaxCaseload", 20) if firm_doc.exists else 20

    return json_ok({"user": d})


# ── PUT /updateUser ───────────────────────────────────────────────────────────
@https_fn.on_request(region=REGION)
def update_user_fn(req: https_fn.Request) -> https_fn.Response:
    early = handle_options(req)
    if early:
        return early

    user, err = require_auth(req)
    if err:
        return err

    data        = req.get_json(silent=True) or {}
    target_uid  = data.get("uid")
    caller_uid  = user.get("uid")
    caller_role = user.get("role", "")

    if not target_uid:
        return json_err("uid required in body", 400)
    if target_uid != caller_uid and not has_permission(caller_role, "staff.manage"):
        return json_err("Forbidden.", 403)

    # staff docs use roleId as doc ID — find by uid field
    staff_docs = list(db().collection("staff").where("userId", "==", target_uid).stream())
    if not staff_docs:
        return json_err("User not found.", 404)

    ref     = staff_docs[0].reference
    current = staff_docs[0].to_dict()
    is_admin = has_permission(caller_role, "staff.manage")
    allowed  = {"displayName", "googleWorkspaceId"} | ({"role", "isActive"} if is_admin else set())
    updates  = {k: v for k, v in data.items() if k in allowed and k != "uid"}

    if not updates:
        return json_err("No updatable fields provided.", 400)

    if "role" in updates:
        if caller_role not in ("admin_staff", "senior_partner"):
            return json_err("Only Admin or Senior Partner can change roles.", 403)
        old_role = current.get("role", "")
        new_role = updates["role"]
        if old_role != new_role:
            auth.set_custom_user_claims(target_uid, {"role": new_role, "active": True})
            log_role_change(caller_uid, target_uid, old_role, new_role)

    if "isActive" in updates:
        auth.update_user(target_uid, disabled=not updates["isActive"])

    updates['updatedAt'] = fs_admin.SERVER_TIMESTAMP
    ref.update(updates)


    return json_ok({"success": True, "updated_fields": list(updates.keys())})


# ── DELETE /deleteUser?uid=xxx ────────────────────────────────────────────────
@https_fn.on_request(region=REGION)
def delete_user_fn(req: https_fn.Request) -> https_fn.Response:
    early = handle_options(req)
    if early:
        return early

    user, err = require_auth(req)
    if err:
        return err
    guard = require_permission(user, "staff.manage", req)
    if guard:
        return guard

    target_uid = req.args.get("uid")
    if not target_uid:
        return json_err("uid query param required", 400)

    # staff docs use roleId as doc ID — find by uid field
    staff_docs = list(db().collection("staff").where("userId", "==", target_uid).stream())
    if not staff_docs:
        return json_err("User not found.", 404)

    staff_docs[0].reference.update({
        "status":     "deleted",
        "deleted_at": fs_admin.SERVER_TIMESTAMP,
        "deleted_by": user.get("uid"),
    })
    try:
        auth.update_user(target_uid, disabled=True)
        auth.revoke_refresh_tokens(target_uid)
    except Exception:
        pass

    write_audit_event(
        "user_soft_deleted",
        target_uid=target_uid,
        performed_by=user.get("uid"),
    )

    return json_ok({"success": True, "message": f"User {target_uid} soft-deleted."})
