"""
api/auth_api.py — Auth endpoints: register, login, logout, password-reset, invite.

Integration with lead-intake:
  Firebase ID tokens issued by create_session_fn are accepted by the
  lead-intake service's GET /leads, PATCH /leads/:id/status, and all
  /admin/partners endpoints when sent as:
    Authorization: Bearer <firebase_id_token>

  The lead-intake auth middleware reads the 'role' custom claim to decide
  which operations the staff member can perform:
    senior_partner / system_admin → full access including partner management
    junior_partner / paralegal / admin_staff → case read/write, no admin endpoints
"""
from __future__ import annotations

import logging

from firebase_admin import auth
from firebase_functions import https_fn

from auth.auth_service import (
    check_rate_limit, create_session, create_user,
    generate_portal_invite, request_password_reset,
)
from auth.rbac import get_role_permissions, require_permission
from middleware.http import (
    REGION, db, handle_options,
    json_err, json_ok, write_audit_event,
)
from middleware.jwt_middleware import require_auth

logger = logging.getLogger(__name__)


@https_fn.on_request(region=REGION)
def register_fn(req: https_fn.Request) -> https_fn.Response:
    """
    POST /register — Create a new staff user account.
    Body: { email, password, display_name, role, portal_token? }
    Returns: { uid, email, display_name, role, permissions[] }
    """
    if early := handle_options(req):
        return early

    try:
        body         = req.get_json(silent=True) or {}
        email        = body.get("email", "").strip().lower()
        password     = body.get("password", "")
        display_name = body.get("display_name", "").strip()
        role         = body.get("role", "")
        portal_token = body.get("portal_token")
        if role != 'client':
            caller, auth_err = require_auth(req)
            if auth_err:
                return auth_err
            guard = require_permission(caller, "staff.manage", req)
            if guard:
                return guard

        if not email or not password or not display_name:
            return json_err("email, password, and display_name are required.", 400)

        result = create_user(
            email=email, password=password,
            display_name=display_name, role=role,
            portal_token=portal_token,
        )

        write_audit_event("user_registered", uid=result["uid"], email=email, role=role)
        logger.info("User registered: %s (%s)", email, role)
        return json_ok({
            "uid":          result["uid"],
            "email":        result["email"],
            "display_name": result["display_name"],
            "role":         result["role"],
            "permissions":  get_role_permissions(result["role"]),
        }, 201)

    except ValueError as exc:
        return json_err(str(exc), 400)
    except auth.EmailAlreadyExistsError:
        return json_err("Email already registered.", 409)
    except Exception as exc:
        logger.error("register_fn error: %s", exc)
        return json_err("Registration failed.", 500)


@https_fn.on_request(region=REGION)
def create_session_fn(req: https_fn.Request) -> https_fn.Response:
    """
    POST /createSession — Exchange a Firebase ID token for a session cookie.
    Body: { id_token }
    Returns: { session_id, expires_in_minutes, uid, role, permissions[] }

    Note: the id_token returned by Firebase Auth (client SDK signInWithEmailAndPassword)
    can also be used directly as a Bearer token in the lead-intake service without
    calling this endpoint first.
    """
    if early := handle_options(req):
        return early

    try:
        body     = req.get_json(silent=True) or {}
        id_token = body.get("id_token", "")
        if not id_token:
            return json_err("id_token is required.", 400)

        decoded  = auth.verify_id_token(id_token)
        uid      = decoded["uid"]
        role     = decoded.get("role", "admin_staff")

        result = create_session(uid=uid, id_token=id_token)
        write_audit_event("session_created", uid=uid, role=role)

        resp = json_ok({
            "session_id":         result["session_id"],
            "expires_in_minutes": result["expires_in_minutes"],
            "uid":                uid,
            "role":               role,
            "permissions":        get_role_permissions(role),
        })
        resp.set_cookie(
            "session",    result["session_cookie"],
            httponly=True, secure=True, samesite="Strict",
            max_age=result["expires_in_minutes"] * 60,
        )
        resp.set_cookie("session_id", result["session_id"], httponly=True, secure=True, samesite="Strict")
        return resp

    except auth.InvalidIdTokenError as exc:
        return json_err(f"Invalid ID token: {exc}", 401)
    except Exception as exc:
        logger.error("create_session_fn error: %s", exc)
        return json_err("Session creation failed.", 500)


@https_fn.on_request(region=REGION)
def logout_fn(req: https_fn.Request) -> https_fn.Response:
    """POST /logout — Revoke all refresh tokens and clear session cookies."""
    if early := handle_options(req):
        return early

    user, err = require_auth(req)
    if err:
        return err

    try:
        from auth.auth_service import revoke_session
        revoke_session(user["uid"])
        from middleware.jwt_middleware import _evict_token
        raw_header = req.headers.get("Authorization", "")
        if raw_header.startswith("Bearer "):
            _evict_token(raw_header[7:])

        write_audit_event("logout", uid=user["uid"])
        resp = json_ok({"message": "Logged out successfully."})
        resp.set_cookie("session", "", max_age=0)
        resp.set_cookie("session_id", "", max_age=0)
        return resp
    except Exception as exc:
        logger.error("logout_fn error: %s", exc)
        return json_err("Logout failed.", 500)


@https_fn.on_request(region=REGION)
def password_reset_fn(req: https_fn.Request) -> https_fn.Response:
    """POST /passwordReset — Send a password reset email. Body: { email }"""
    if early := handle_options(req):
        return early

    try:
        body  = req.get_json(silent=True) or {}
        email = body.get("email", "").strip().lower()
        if not email:
            return json_err("email is required.", 400)

        ip = req.headers.get("X-Forwarded-For", req.remote_addr or "unknown")
        check_rate_limit(f"reset:{ip}")
        request_password_reset(email=email, ip=ip)
        return json_ok({"message": "If that email is registered, a reset link has been sent."})

    except PermissionError as exc:
        return json_err(str(exc), 429)
    except Exception as exc:
        logger.error("password_reset_fn error: %s", exc)
        return json_err("Password reset failed.", 500)


@https_fn.on_request(region=REGION)
def create_invite_fn(req: https_fn.Request) -> https_fn.Response:
    """
    POST /createInvite — Generate a portal invite link for a new user.
    Requires: senior_partner or system_admin role.
    Body: { email }
    """
    if early := handle_options(req):
        return early

    user, err = require_auth(req)
    if err:
        return err

    role = user.get("role", "")
    if role not in ("senior_partner", "system_admin"):
        return json_err("senior_partner or system_admin role required.", 403)

    try:
        body  = req.get_json(silent=True) or {}
        email = body.get("email", "").strip().lower()
        if not email:
            return json_err("email is required.", 400)

        token    = generate_portal_invite(email=email, created_by_uid=user["uid"])
        inv_link = f"https://portal.zadlegal.com/register?token={token}"
        write_audit_event("invite_created", created_by=user["uid"], target_email=email)
        return json_ok({"invite_link": inv_link, "expires_in_days": 7})

    except Exception as exc:
        logger.error("create_invite_fn error: %s", exc)
        return json_err("Invite creation failed.", 500)
