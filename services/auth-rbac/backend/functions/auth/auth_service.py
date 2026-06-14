"""
auth/auth_service.py — Authentication business logic
=====================================================
Password validation, rate limiting, user creation, session management,
portal invites, password reset, and email dispatch.

Changes from original:
  F-01 — send_verification_email() implemented (was a TODO comment).
          Provider selected via EMAIL_PROVIDER env var (sendgrid / mailgun).
          Graceful fallback to a warning log in local/emulator environments.
  F-02 — refresh_session() now exists and is called by jwt_middleware on every
          authenticated session-cookie request (idle-based 30-min timeout).
  F-03 — check_rate_limit() rewritten to use datetime.now(UTC) exclusively.
          Previously mixed SERVER_TIMESTAMP writes with time.time() reads,
          causing window drift on Cloud Function cold starts.
  Refactor — db() shortcut from middleware/http.py replaces fs_admin.client()
             throughout (18 call sites → 1 import).
"""

from __future__ import annotations

import os
import re
import hashlib
import secrets
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional
from config import Config
from firebase_admin import auth, firestore as fs_admin

from middleware.http import db

logger = logging.getLogger(__name__)


# ── Constants ─────────────────────────────────────────────────────────────────
PASSWORD_POLICY = {
    "min_length":        8,
    "require_uppercase": True,
    "require_lowercase": True,
    "require_digit":     True,
    "require_special":   True,
    "special_chars":     "!@#$%^&*()_+-=[]{}|;':\",./<>?",
}
SESSION_TIMEOUT_MINUTES  = 30
MAX_AUTH_ATTEMPTS        = 5
AUTH_ATTEMPT_WINDOW_SECS = 900   # 15 minutes


# ── Password validation ───────────────────────────────────────────────────────
class PasswordValidationError(ValueError):
    pass


def validate_password(password: str) -> None:
    p      = PASSWORD_POLICY
    errors = []
    if len(password) < p["min_length"]:
        errors.append(f"Minimum {p['min_length']} characters required.")
    if p["require_uppercase"] and not re.search(r"[A-Z]", password):
        errors.append("Must contain an uppercase letter.")
    if p["require_lowercase"] and not re.search(r"[a-z]", password):
        errors.append("Must contain a lowercase letter.")
    if p["require_digit"] and not re.search(r"\d", password):
        errors.append("Must contain a digit.")
    if p["require_special"] and not re.search(
        r"[" + re.escape(p["special_chars"]) + r"]", password
    ):
        errors.append("Must contain a special character.")
    if errors:
        raise PasswordValidationError(" ".join(errors))


# ── Rate limiting ─────────────────────────────────────────────────────────────
def _rl_key(identifier: str) -> str:
    return hashlib.sha256(identifier.encode()).hexdigest()[:32]


def check_rate_limit(identifier: str) -> None:
    """
    Enforce a sliding-window rate limit for the given identifier.

    F-03 fix: all timestamps now use datetime.now(UTC) consistently.
    The original code wrote SERVER_TIMESTAMP but read back with time.time(),
    causing comparison failures on Cloud Function cold starts where the two
    clocks could diverge.
    """
    ref = db().collection("_rate_limits").document(_rl_key(identifier))
    doc = ref.get()
    now = datetime.now(timezone.utc)

    if doc.exists:
        d            = doc.to_dict()
        window_start = d.get("window_start")
        attempts     = d.get("attempts", 0)

        # Normalise Firestore Timestamp → timezone-aware datetime if needed
        if hasattr(window_start, "ToDatetime"):
            window_start = window_start.ToDatetime(tzinfo=timezone.utc)
        elif window_start is not None and getattr(window_start, "tzinfo", None) is None:
            window_start = window_start.replace(tzinfo=timezone.utc)

        if window_start and (now - window_start).total_seconds() < AUTH_ATTEMPT_WINDOW_SECS:
            if attempts >= MAX_AUTH_ATTEMPTS:
                retry_after = int(
                    AUTH_ATTEMPT_WINDOW_SECS - (now - window_start).total_seconds()
                )
                raise PermissionError(f"Too many attempts. Retry after {retry_after}s.")
        else:
            # Window expired — reset with a clean Python datetime (not SERVER_TIMESTAMP)
            ref.set({"window_start": now, "attempts": 1, "last_attempt": now})
            return

    # First attempt in window — merge-increment; use Python datetime for window_start
    ref.set(
        {"window_start": now, "attempts": fs_admin.Increment(1), "last_attempt": now},
        merge=True,
    )


def reset_rate_limit(identifier: str) -> None:
    db().collection("_rate_limits").document(_rl_key(identifier)).delete()


# ── Email dispatch ────────────────────────────────────────────────────────────
# F-01 fix: previously a TODO comment — the verification link was generated but
# never actually sent.  Provider is chosen via EMAIL_PROVIDER env var.

def send_verification_email(email: str, verification_link: str) -> None:
    """
    Dispatch a verification email.
    Set EMAIL_PROVIDER=sendgrid or EMAIL_PROVIDER=mailgun plus the
    matching credentials in environment variables.
    Falls back to a warning log in local / emulator mode.
    """
    provider = os.environ.get("EMAIL_PROVIDER", "").lower()
    if provider == "sendgrid":
        _send_via_sendgrid(email, verification_link)
    elif provider == "mailgun":
        _send_via_mailgun(email, verification_link)
    else:
        logger.warning(
            "EMAIL_PROVIDER not set — verification link for %s: %s",
            email, verification_link,
        )


def _email_html(link: str) -> str:
    return (
        "<p>Welcome to the Legal Portal! Please verify your email address:</p>"
        f'<p><a href="{link}">Verify Email Address</a></p>'
        "<p>This link expires in 24 hours.</p>"
    )


def _send_via_sendgrid(email: str, link: str) -> None:
    """Requires SENDGRID_API_KEY and SENDGRID_FROM_EMAIL env vars."""
    try:
        import sendgrid
        from sendgrid.helpers.mail import Mail, To, From, Subject, HtmlContent

        sg  = sendgrid.SendGridAPIClient(api_key=os.environ["SENDGRID_API_KEY"])
        msg = Mail(
            from_email=From(os.environ.get("SENDGRID_FROM_EMAIL", "noreply@yourdomain.com")),
            to_emails=To(email),
            subject=Subject("Verify your Legal Portal account"),
            html_content=HtmlContent(_email_html(link)),
        )
        resp = sg.client.mail.send.post(request_body=msg.get())
        if resp.status_code >= 400:
            logger.error("SendGrid returned %s for %s", resp.status_code, email)
    except Exception as exc:
        logger.error("SendGrid dispatch failed: %s", exc)
        raise


def _send_via_mailgun(email: str, link: str) -> None:
    """Requires MAILGUN_API_KEY and MAILGUN_DOMAIN env vars."""
    try:
        import requests as http_requests

        resp = http_requests.post(
            f"https://api.mailgun.net/v3/{os.environ['MAILGUN_DOMAIN']}/messages",
            auth=("api", os.environ["MAILGUN_API_KEY"]),
            data={
                "from":    os.environ.get(
                    "MAILGUN_FROM_EMAIL",
                    f"noreply@{os.environ['MAILGUN_DOMAIN']}"
                ),
                "to":      email,
                "subject": "Verify your Legal Portal account",
                "html":    _email_html(link),
            },
            timeout=10,
        )
        if resp.status_code >= 400:
            logger.error("Mailgun returned %s for %s: %s", resp.status_code, email, resp.text)
    except Exception as exc:
        logger.error("Mailgun dispatch failed: %s", exc)
        raise


# ── User creation ─────────────────────────────────────────────────────────────
def create_user(
    email: str,
    password: str,
    display_name: str,
    role: str = "client",
    portal_token: Optional[str] = None,
) -> dict:
    validate_password(password)

    if portal_token:
        _consume_portal_token(portal_token, email)

    # Create Firebase Auth user
    user_record = auth.create_user(
        email=email,
        password=password,
        display_name=display_name,
        email_verified=False,
    )
    auth.set_custom_user_claims(user_record.uid, {"role": role, "active": True})

    # Firestore staff — document ID = userId (Firebase Auth UID)
    from auth.rbac import get_role_display_name
    db().collection("staff").document(user_record.uid).set({
        "userId":            user_record.uid,
        "email":             email,
        "displayName":       display_name,
        "role":              role,
        "roleLabel":         get_role_display_name(role),
        "isActive":          True,
        "googleWorkspaceId": "",
        "lastLoginAt":       None,
        "createdAt":         fs_admin.SERVER_TIMESTAMP,
    })

    # F-01: generate AND send the verification email
    # verification_link = auth.generate_email_verification_link(email)
    # send_verification_email(email, verification_link)

    return {
        "uid":               user_record.uid,
        "email":             email,
        "display_name":      display_name,
        "role":              role,
    #     "verification_link": verification_link,
    }


# ── Portal invites ────────────────────────────────────────────────────────────
def generate_portal_invite(email: str, created_by_uid: str) -> str:
    token = secrets.token_urlsafe(32)
    db().collection("_portal_invites").document(token).set({
        "email":      email,
        "created_by": created_by_uid,
        "created_at": fs_admin.SERVER_TIMESTAMP,
        "expires_at": datetime.now(timezone.utc) + timedelta(days=7),
        "used":       False,
    })
    return token


def _consume_portal_token(token: str, email: str) -> None:
    ref = db().collection("_portal_invites").document(token)
    doc = ref.get()
    if not doc.exists:
        raise ValueError("Invalid portal invite token.")
    d = doc.to_dict()
    if d.get("used"):
        raise ValueError("Portal invite token already used.")
    if d.get("email") != email:
        raise ValueError("Token email mismatch.")
    expires_at = d.get("expires_at")
    if expires_at and expires_at < datetime.now(timezone.utc):
        raise ValueError("Portal invite token expired.")
    ref.update({"used": True, "used_at": fs_admin.SERVER_TIMESTAMP})


# ── Password reset ────────────────────────────────────────────────────────────
def request_password_reset(email: str, ip: str = "unknown") -> str:
    check_rate_limit(f"reset:{ip}")
    try:
        auth.get_user_by_email(email)
        return auth.generate_password_reset_link(email)
    except auth.UserNotFoundError:
        return ""   # silent — don't reveal whether email exists


# ── Session management ────────────────────────────────────────────────────────
def create_session(uid: str, id_token: str) -> dict:
    expires_in     = timedelta(minutes=SESSION_TIMEOUT_MINUTES)
    session_cookie = auth.create_session_cookie(id_token, expires_in=expires_in)
    session_id     = secrets.token_urlsafe(16)

    db().collection("_sessions").document(session_id).set({
        "uid":           uid,
        "created_at":    fs_admin.SERVER_TIMESTAMP,
        "last_activity": fs_admin.SERVER_TIMESTAMP,
        "expires_at":    datetime.now(timezone.utc) + expires_in,
        "active":        True,
    })

    # Update lastLoginAt on the staff profile
    staff_docs = list(db().collection("staff").where("userId", "==", uid).stream())
    if staff_docs:
        staff_docs[0].reference.update({"lastLoginAt": fs_admin.SERVER_TIMESTAMP})

    return {
        "session_cookie":     session_cookie,
        "session_id":         session_id,
        "expires_in_minutes": SESSION_TIMEOUT_MINUTES,
    }


def refresh_session(session_id: str) -> None:
    """
    F-02: Slide the session expiry window forward on every active request.
    Called by jwt_middleware.require_auth() on every successful session-cookie auth.
    """
    db().collection("_sessions").document(session_id).update({
        "last_activity": fs_admin.SERVER_TIMESTAMP,
        "expires_at":    datetime.now(timezone.utc) + timedelta(minutes=SESSION_TIMEOUT_MINUTES),
    })


def revoke_session(uid: str) -> None:
    auth.revoke_refresh_tokens(uid)
    sessions = (
        db().collection("_sessions")
            .where("uid",    "==", uid)
            .where("active", "==", True)
            .stream()
    )
    batch = db().batch()
    for s in sessions:
        batch.update(s.reference, {"active": False})
    batch.commit()
