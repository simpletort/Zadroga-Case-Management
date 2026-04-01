"""
api/middleware/auth.py — Unified authentication for lead-intake.

Auth priority order:
  1. X-API-Key header present → marketing partner API key auth
  2. Authorization: Bearer <token> with Firebase issuer → staff Firebase JWT auth
     (Firebase tokens issued by auth-rbac service, role in custom claims)
  3. Authorization: Bearer <token> without Firebase issuer → partner JWT auth
  4. Neither → 401

This dual-path allows:
  - Marketing partners to submit leads using API keys (external API)
  - Internal staff (admin_ui) to use Firebase ID tokens from auth-rbac
    to access the admin endpoints (GET /leads, PATCH /leads/:id/status, etc.)

Staff Firebase JWT custom claims format (set by auth-rbac service):
  { "role": "senior_partner", "active": true }

Role values: system_admin | senior_partner | junior_partner | paralegal | admin_staff
"""
from __future__ import annotations

import time
from typing import Optional

import httpx
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt

from config import get_settings
from logging_config import get_logger
from middleware.partner_auth import verify_api_key, PartnerContext

logger = get_logger(__name__)
security = HTTPBearer(auto_error=False)

# ── JWKS caches (separate for partner JWTs and Firebase staff JWTs) ───────────

_partner_jwks_cache:   dict  = {}
_partner_jwks_fetched: float = 0.0
_firebase_jwks_cache:  dict  = {}
_firebase_jwks_fetched: float = 0.0
JWKS_TTL = 3600


async def _get_partner_jwks() -> dict:
    global _partner_jwks_cache, _partner_jwks_fetched
    now = time.monotonic()
    if _partner_jwks_cache and (now - _partner_jwks_fetched) < JWKS_TTL:
        return _partner_jwks_cache
    settings = get_settings()
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(settings.jwks_uri)
        resp.raise_for_status()
        _partner_jwks_cache   = resp.json()
        _partner_jwks_fetched = now
        logger.info("partner_jwks_refreshed")
        return _partner_jwks_cache


async def _get_firebase_jwks() -> dict:
    """Fetch Google's public certs for Firebase Auth JWT verification."""
    global _firebase_jwks_cache, _firebase_jwks_fetched
    now = time.monotonic()
    if _firebase_jwks_cache and (now - _firebase_jwks_fetched) < JWKS_TTL:
        return _firebase_jwks_cache
    settings = get_settings()
    # Firebase returns X.509 PEM certs, not JWKS, but jose can work with RSA PEM
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(settings.firebase_jwks_uri)
        resp.raise_for_status()
        _firebase_jwks_cache   = resp.json()
        _firebase_jwks_fetched = now
        logger.info("firebase_jwks_refreshed")
        return _firebase_jwks_cache


def _is_firebase_token(token: str) -> bool:
    """Quick check: is this a Firebase Auth JWT (issued by securetoken.google.com)?"""
    try:
        unverified = jwt.get_unverified_claims(token)
        issuer     = unverified.get("iss", "")
        return issuer.startswith("https://securetoken.google.com/")
    except Exception:
        return False


# ── Staff Firebase JWT verification ──────────────────────────────────────────

async def _verify_firebase_jwt(token: str) -> PartnerContext:
    """
    Verify a Firebase Auth ID token issued by the auth-rbac service.
    Returns a PartnerContext with role from Firebase custom claims.

    In dev/test mode: skips signature verification (allows emulator tokens).
    """
    settings = get_settings()
    unauth_exc = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail={"error": "UNAUTHORIZED", "message": "Invalid or expired Firebase token", "details": []},
        headers={"WWW-Authenticate": "Bearer"},
    )

    try:
        if settings.app_env in ("development", "test"):
            # Dev mode: skip signature verification for Firebase emulator tokens
            claims = jwt.decode(
                token,
                key="",
                algorithms=["RS256"],
                options={"verify_signature": False, "verify_exp": False, "verify_aud": False},
            )
        else:
            # Production: full verification using Firebase public certs
            firebase_certs = await _get_firebase_jwks()
            kid            = jwt.get_unverified_header(token).get("kid")
            pem_key        = firebase_certs.get(kid)
            if not pem_key:
                logger.warning("firebase_jwt_kid_not_found", kid=kid)
                raise unauth_exc
            claims = jwt.decode(
                token,
                pem_key,
                algorithms=["RS256"],
                audience=settings.firebase_project_id,
                issuer=settings.firebase_jwt_issuer,
                options={"verify_exp": True},
            )

        uid    = claims.get("user_id") or claims.get("uid") or claims.get("sub")
        role   = claims.get("role", "admin_staff")
        active = claims.get("active", True)

        if not uid:
            raise unauth_exc
        if not active:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={"error": "FORBIDDEN", "message": "Account is inactive", "details": []},
            )

        logger.info("firebase_jwt_verified", uid=uid, role=role)
        return PartnerContext(
            partner_id   = uid,
            auth_method  = "firebase_jwt",
            raw_claims   = {**claims, "role": role, "uid": uid, "active": active},
        )
    except HTTPException:
        raise
    except JWTError as exc:
        logger.warning("firebase_jwt_verification_failed", error=str(exc))
        raise unauth_exc


# ── Partner JWT verification ──────────────────────────────────────────────────

async def _verify_partner_jwt(token: str) -> PartnerContext:
    settings = get_settings()
    unauth_exc = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail={"error": "UNAUTHORIZED", "message": "Invalid or expired token", "details": []},
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        if settings.app_env in ("development", "test"):
            claims     = jwt.decode(
                token, key="", algorithms=["RS256"],
                options={"verify_signature": False, "verify_exp": False, "verify_aud": False},
            )
            partner_id: Optional[str] = claims.get("partner_id") or claims.get("sub")
            if not partner_id:
                raise unauth_exc
            logger.info("partner_jwt_dev_bypass", sub=partner_id)
            return PartnerContext(partner_id=partner_id, auth_method="jwt", raw_claims=claims)

        unverified_header = jwt.get_unverified_header(token)
        kid  = unverified_header.get("kid")
        jwks = await _get_partner_jwks()
        key  = next((k for k in jwks.get("keys", []) if k.get("kid") == kid), None)
        if not key:
            logger.warning("partner_jwt_key_not_found", kid=kid)
            raise unauth_exc

        claims     = jwt.decode(
            token, key, algorithms=["RS256"],
            audience=settings.jwt_audience, issuer=settings.jwt_issuer,
            options={"verify_exp": True},
        )
        partner_id = claims.get("partner_id") or claims.get("sub")
        if not partner_id:
            raise unauth_exc
        return PartnerContext(partner_id=partner_id, auth_method="jwt", raw_claims=claims)

    except (JWTError, HTTPException) as exc:
        if isinstance(exc, HTTPException):
            raise
        logger.warning("partner_jwt_verification_failed", error=str(exc))
        raise unauth_exc


# ── Unified auth dependency ───────────────────────────────────────────────────

async def get_partner(
    request:     Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> PartnerContext:
    """
    FastAPI dependency: authenticates via API key → Firebase JWT → partner JWT.
    Attaches PartnerContext to request.state.partner.
    """
    api_key = request.headers.get("X-API-Key")
    if api_key:
        ctx = await verify_api_key(request, api_key)
        request.state.partner = ctx
        return ctx

    if credentials:
        token = credentials.credentials
        if _is_firebase_token(token):
            ctx = await _verify_firebase_jwt(token)
        else:
            ctx = await _verify_partner_jwt(token)
        request.state.partner = ctx
        return ctx

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail={
            "error":   "UNAUTHORIZED",
            "message": "Provide X-API-Key header (partner) or Authorization: Bearer <Firebase ID token> (staff)",
            "details": [],
        },
        headers={"WWW-Authenticate": "Bearer"},
    )
