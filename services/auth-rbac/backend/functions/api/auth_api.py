"""
api/auth_api.py — Authentication HTTP endpoints
================================================
  register_fn         POST  /register
  create_session_fn   POST  /createSession
  logout_fn           POST  /logout
  password_reset_fn   POST  /passwordReset
  create_invite_fn    POST  /createInvite

Changes from original:
  F-06 — logout_fn calls _evict_token() so the revoked token is purged from
          the in-process JWT cache immediately on this instance.
  Refactor — handle_options() replaces 10 identical OPTIONS if-blocks.
             REGION imported from middleware/http.py (was copy-pasted).
"""

from __future__ import annotations

import json
import os

from firebase_functions import https_fn
from firebase_admin import auth

from auth.auth_service import (
    create_user,
    create_session,
    revoke_session,
    request_password_reset,
    generate_portal_invite,
)
from auth.rbac import Permission, require_permission
from middleware.http import REGION, CORS_HEADERS, json_ok, json_err, handle_options
from middleware.jwt_middleware import require_auth, _evict_token


# ── POST /register ────────────────────────────────────────────────────────────
@https_fn.on_request(region=REGION, cors=https_fn.options.CorsOptions(
    cors_origins="*", cors_methods=["POST", "OPTIONS"]
))
def register_fn(req: https_fn.Request) -> https_fn.Response:
    early = handle_options(req)
    if early:
        return early

    data    = req.get_json(silent=True) or {}
    missing = [f for f in ["email", "password", "display_name"] if not data.get(f)]
    if missing:
        return json_err(f"Missing fields: {missing}", 400)

    try:
        user = create_user(
            email=data["email"],
            password=data["password"],
            display_name=data["display_name"],
            role=data.get("role", "client"),
            portal_token=data.get("portal_token"),
        )
        return json_ok({"success": True, "uid": user["uid"]}, 201)
    except PermissionError as exc:
        return json_err(str(exc), 429)
    except ValueError as exc:
        return json_err(str(exc), 400)
    except Exception as exc:
        return json_err(f"Registration failed: {exc}", 500)


# ── POST /createSession ───────────────────────────────────────────────────────
@https_fn.on_request(region=REGION, cors=https_fn.options.CorsOptions(
    cors_origins="*", cors_methods=["POST", "OPTIONS"]
))
def create_session_fn(req: https_fn.Request) -> https_fn.Response:
    early = handle_options(req)
    if early:
        return early

    data     = req.get_json(silent=True) or {}
    id_token = data.get("id_token")
    if not id_token:
        return json_err("id_token required", 400)

    try:
        decoded = auth.verify_id_token(id_token)
        session = create_session(decoded["uid"], id_token)

        response = https_fn.Response(
            json.dumps({"success": True, "session_id": session["session_id"]}),
            status=200,
            headers={**CORS_HEADERS, "Content-Type": "application/json"},
        )
        max_age = session["expires_in_minutes"] * 60
        response.set_cookie(
            "session", session["session_cookie"],
            max_age=max_age, httponly=True, secure=True, samesite="Strict",
        )
        response.set_cookie(
            "session_id", session["session_id"],
            max_age=max_age, httponly=True, secure=True, samesite="Strict",
        )
        return response
    except Exception as exc:
        return json_err(str(exc), 401)


# ── POST /logout ──────────────────────────────────────────────────────────────
@https_fn.on_request(region=REGION, cors=https_fn.options.CorsOptions(
    cors_origins="*", cors_methods=["POST", "OPTIONS"]
))
def logout_fn(req: https_fn.Request) -> https_fn.Response:
    early = handle_options(req)
    if early:
        return early

    user, err = require_auth(req)
    if err:
        return err

    # F-06: evict the token from the in-process cache immediately so this
    # instance cannot re-use it for the remaining TTL window.
    raw_header = req.headers.get("Authorization", "")
    if raw_header.startswith("Bearer "):
        _evict_token(raw_header[7:])

    revoke_session(user["uid"])

    response = https_fn.Response(
        json.dumps({"success": True}),
        status=200,
        headers={**CORS_HEADERS, "Content-Type": "application/json"},
    )
    response.delete_cookie("session")
    response.delete_cookie("session_id")
    return response


# ── POST /passwordReset ───────────────────────────────────────────────────────
@https_fn.on_request(region=REGION, cors=https_fn.options.CorsOptions(
    cors_origins="*", cors_methods=["POST", "OPTIONS"]
))
def password_reset_fn(req: https_fn.Request) -> https_fn.Response:
    early = handle_options(req)
    if early:
        return early

    data  = req.get_json(silent=True) or {}
    email = data.get("email", "")
    ip    = req.headers.get("X-Forwarded-For", req.remote_addr or "unknown")

    try:
        request_password_reset(email, ip)
    except PermissionError as exc:
        return json_err(str(exc), 429)
    except Exception:
        pass   # silent — don't reveal whether the email is registered

    return json_ok({"message": "If this email is registered, a reset link has been sent."})


# ── POST /createInvite ────────────────────────────────────────────────────────
@https_fn.on_request(region=REGION, cors=https_fn.options.CorsOptions(
    cors_origins="*", cors_methods=["POST", "OPTIONS"]
))
def create_invite_fn(req: https_fn.Request) -> https_fn.Response:
    early = handle_options(req)
    if early:
        return early

    user, err = require_auth(req)
    if err:
        return err
    guard = require_permission(user, Permission.MANAGE_USERS, req)
    if guard:
        return guard

    data  = req.get_json(silent=True) or {}
    email = data.get("email")
    if not email:
        return json_err("email required", 400)

    token      = generate_portal_invite(email, user["uid"])
    base_url   = os.environ.get("PORTAL_BASE_URL", "https://your-project.web.app")
    invite_link = f"{base_url}/register?token={token}&email={email}"

    return json_ok({"invite_link": invite_link, "token": token})
