"""
middleware/jwt_middleware.py — JWT / Session authentication
===========================================================
Validates Firebase Auth tokens and session cookies on every protected request.

Fixes applied:
  F-02 — refresh_session() called on every successful session-cookie auth
          so the 30-minute timeout is idle-based (sliding window).
  F-06 — CACHE_TTL reduced 60 s → 15 s; _evict_token() purges revoked
          tokens from the cache immediately.
  Loose — removed dead PUBLIC_PATHS constant.

Shared HTTP utilities (CORS_HEADERS, json_ok, json_err, REGION, etc.) now
live in middleware/http.py and are re-exported here for backward compatibility
so existing imports don't need to change.
"""

from __future__ import annotations

import time
import logging
from typing import Optional, Tuple

from firebase_admin import auth
from firebase_functions import https_fn

# ── Re-export shared utilities so callers don't need to change their imports ──
from middleware.http import (           # noqa: F401  (intentional re-exports)
    CORS_HEADERS,
    REGION,
    json_ok,
    json_err,
    cors_preflight,
    handle_options,
    write_audit_event,
    db,
)

logger = logging.getLogger(__name__)

# ── In-process token cache ────────────────────────────────────────────────────
# F-06: TTL reduced 60 s → 15 s to narrow the window during which a revoked
# token can be served as valid from a warm Cloud Function instance.
_TOKEN_CACHE: dict[str, Tuple[dict, float]] = {}
_CACHE_TTL: int = 15   # seconds


def _verify_id_token(token: str) -> dict:
    """Verify a Firebase ID token with a 15-second in-memory cache."""
    now = time.monotonic()
    if token in _TOKEN_CACHE:
        claims, cached_at = _TOKEN_CACHE[token]
        if now - cached_at < _CACHE_TTL:
            return claims
        del _TOKEN_CACHE[token]

    claims = auth.verify_id_token(token, check_revoked=True)

    _TOKEN_CACHE[token] = (claims, now)
    # Evict expired entries when the cache grows large
    if len(_TOKEN_CACHE) > 2000:
        cutoff = now - _CACHE_TTL
        for k in [k for k, (_, t) in _TOKEN_CACHE.items() if t < cutoff]:
            _TOKEN_CACHE.pop(k, None)

    return claims


def _evict_token(token: str) -> None:
    """
    F-06: Immediately remove a token from the local cache on revocation.
    Call this from logout_fn (or anywhere a token is explicitly invalidated)
    so this instance cannot re-serve the token for the remaining TTL window.
    """
    _TOKEN_CACHE.pop(token, None)


def _build_user_context(claims: dict) -> dict:
    """Extract the user context dict that handlers receive."""
    return {
        "uid":            claims.get("uid") or claims.get("user_id"),
        "email":          claims.get("email", ""),
        "email_verified": claims.get("email_verified", False),
        "role":           claims.get("role", "client"),
        "active":         claims.get("active", True),
        "display_name":   claims.get("name", ""),
    }


def require_auth(
    req: https_fn.Request,
) -> Tuple[Optional[dict], Optional[https_fn.Response]]:
    """
    Validate the Bearer token or session cookie on a Cloud Function request.

    F-02: on every successful session-cookie auth, refresh_session() is called
    so the 30-minute idle timeout slides forward on each request.

    Returns:
        (user_dict, None)       — success; user_dict is passed to handlers.
        (None, error_response)  — failure; return error_response immediately.
    """
    if req.method == "OPTIONS":
        return None, cors_preflight()

    # ── Bearer token path ─────────────────────────────────────────────────────
    raw_header = req.headers.get("Authorization", "")
    if raw_header.startswith("Bearer "):
        token = raw_header[7:]
        try:
            claims = _verify_id_token(token)
        except auth.ExpiredIdTokenError:
            return None, json_err("Token expired. Please refresh.", 401)
        except auth.RevokedIdTokenError:
            _evict_token(token)   # F-06: purge immediately
            return None, json_err("Token revoked. Please log in again.", 401)
        except auth.InvalidIdTokenError as exc:
            return None, json_err(f"Invalid token: {exc}", 401)
        except Exception as exc:
            logger.warning("JWT verification failed: %s", exc)
            return None, json_err("Authentication failed.", 401)

        user = _build_user_context(claims)
        if not user.get("active", True):
            return None, json_err("Account suspended.", 403)
        return user, None

    # ── Session cookie path ───────────────────────────────────────────────────
    session_cookie = req.cookies.get("session")
    if session_cookie:
        try:
            claims = auth.verify_session_cookie(session_cookie, check_revoked=True)
            user   = _build_user_context(claims)
            if not user.get("active", True):
                return None, json_err("Account suspended.", 403)

            # F-02: slide the idle window forward on every authenticated request.
            session_id = req.cookies.get("session_id")
            if session_id:
                try:
                    from auth.auth_service import refresh_session
                    refresh_session(session_id)
                except Exception as exc:
                    # Non-fatal — log and continue.
                    logger.warning("Session refresh failed for %s: %s", session_id, exc)

            return user, None
        except Exception as exc:
            return None, json_err(f"Invalid session: {exc}", 401)

    return None, json_err("Authentication required.", 401)
