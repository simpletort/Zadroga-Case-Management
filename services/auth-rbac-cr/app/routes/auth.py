"""
app/routes/auth.py — Authentication endpoints
==============================================
  POST /api/v1/auth/register       — create user (public for client invite; staff.manage for staff)
  POST /api/v1/auth/session        — exchange Firebase ID token for session cookie (public)
  POST /api/v1/auth/logout         — revoke tokens and clear cookies (any authenticated user)
  POST /api/v1/auth/password-reset — send password reset email (public, rate-limited)
  POST /api/v1/auth/invite         — generate a portal invite link (staff.invite or system.admin)

These routes are in skip_paths for AuthMiddleware (register, session, password-reset).
Logout and invite rely on request.state.user set by AuthMiddleware.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from firebase_admin import auth

from app.models.auth import (
    InviteRequest,
    PasswordResetRequest,
    RegisterRequest,
    SessionRequest,
)
from app.services.auth_service import (
    check_rate_limit,
    create_session,
    create_user,
    generate_portal_invite,
    request_password_reset,
)
from app.services.rbac_service import (
    get_role_permissions,
    has_permission,
    write_audit_event,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


@router.post("/register", status_code=201)
def register(body: RegisterRequest, request: Request):
    """
    Create a new user.
    - Client self-registration (via portal invite): no auth required.
    - Staff creation: requires staff.manage or system.admin (enforced inline
      because this route is in skip_paths for the middleware).
    """
    email        = body.email.strip().lower()
    password     = body.password
    display_name = body.display_name.strip()
    role         = body.role
    portal_token = body.portal_token

    if role != "client":
        caller = getattr(request.state, "user", None)
        if caller is None:
            raise HTTPException(status_code=401, detail="Authentication required.")
        if not (has_permission(caller.get("role", ""), "staff.manage")
                or has_permission(caller.get("role", ""), "system.admin")):
            raise HTTPException(status_code=403, detail="Forbidden: insufficient permissions.")

    if not email or not password or not display_name:
        raise HTTPException(status_code=400, detail="email, password, and display_name are required.")

    try:
        result = create_user(
            email=email,
            password=password,
            display_name=display_name,
            role=role,
            portal_token=portal_token,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except auth.EmailAlreadyExistsError:
        raise HTTPException(status_code=409, detail="Email already registered.")
    except Exception as exc:
        logger.error("register error: %s", exc)
        raise HTTPException(status_code=500, detail="Registration failed.")

    write_audit_event("user_registered", uid=result["uid"], email=email, role=role)
    return {
        "uid":          result["uid"],
        "email":        result["email"],
        "display_name": result["display_name"],
        "role":         result["role"],
        "permissions":  get_role_permissions(result["role"]),
    }


@router.post("/session")
def create_session_route(body: SessionRequest, response: Response):
    """Exchange a Firebase ID token for a 30-minute session cookie."""
    if not body.id_token:
        raise HTTPException(status_code=400, detail="id_token is required.")

    try:
        decoded = auth.verify_id_token(body.id_token)
    except auth.InvalidIdTokenError as exc:
        raise HTTPException(status_code=401, detail=f"Invalid ID token: {exc}")
    except Exception as exc:
        logger.error("create_session error: %s", exc)
        raise HTTPException(status_code=500, detail="Session creation failed.")

    uid  = decoded["uid"]
    role = decoded.get("role") or "client"

    try:
        result = create_session(uid=uid, id_token=body.id_token)
    except Exception as exc:
        logger.error("create_session service error: %s", exc)
        raise HTTPException(status_code=500, detail="Session creation failed.")

    write_audit_event("session_created", uid=uid, role=role)

    max_age = result["expires_in_minutes"] * 60
    response.set_cookie("session",    result["session_cookie"], httponly=True, secure=True, samesite="strict", max_age=max_age)
    response.set_cookie("session_id", result["session_id"],     httponly=True, secure=True, samesite="strict")

    return {
        "session_id":         result["session_id"],
        "expires_in_minutes": result["expires_in_minutes"],
        "uid":                uid,
        "role":               role,
        "permissions":        get_role_permissions(role),
    }


@router.post("/logout")
def logout(request: Request, response: Response):
    """Revoke all refresh tokens and clear session cookies."""
    user = getattr(request.state, "user", None)
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication required.")

    try:
        from app.services.auth_service import revoke_session
        revoke_session(user["uid"])
    except Exception as exc:
        logger.error("logout error: %s", exc)
        raise HTTPException(status_code=500, detail="Logout failed.")

    write_audit_event("logout", uid=user["uid"])
    response.delete_cookie("session")
    response.delete_cookie("session_id")
    return {"message": "Logged out successfully."}


@router.post("/password-reset")
def password_reset(body: PasswordResetRequest, request: Request):
    """Send a password reset email. Always returns 200 to prevent email enumeration."""
    email = body.email.strip().lower()
    if not email:
        raise HTTPException(status_code=400, detail="email is required.")

    ip = request.headers.get("X-Forwarded-For", "").split(",")[0].strip() or "unknown"

    try:
        check_rate_limit(f"reset:{ip}")
        request_password_reset(email=email, ip=ip)
    except PermissionError as exc:
        raise HTTPException(status_code=429, detail=str(exc))
    except Exception as exc:
        logger.error("password_reset error: %s", exc)
        raise HTTPException(status_code=500, detail="Password reset failed.")

    return {"message": "If that email is registered, a reset link has been sent."}


@router.post("/invite")
def create_invite(body: InviteRequest, request: Request):
    """Generate a 7-day portal invite link. Requires staff.invite or system.admin."""
    user = getattr(request.state, "user", None)
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication required.")

    email = body.email.strip().lower()
    if not email:
        raise HTTPException(status_code=400, detail="email is required.")

    try:
        token    = generate_portal_invite(email=email, created_by_uid=user["uid"])
        inv_link = f"https://portal.zadlegal.com/register?token={token}"
    except Exception as exc:
        logger.error("create_invite error: %s", exc)
        raise HTTPException(status_code=500, detail="Invite creation failed.")

    write_audit_event("invite_created", created_by=user["uid"], target_email=email)
    return {"invite_link": inv_link, "expires_in_days": 7}
