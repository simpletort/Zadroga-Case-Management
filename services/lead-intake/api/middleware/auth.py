"""
api/middleware/auth.py — Unified auth: JWT Bearer OR API Key + HMAC.

Priority:
  1. If X-API-Key header present → API key auth path
  2. If Authorization: Bearer <token> present → JWT auth path
  3. Neither → 401

This allows marketing partners to use whichever method they were onboarded with.
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
security = HTTPBearer(auto_error=False)  # auto_error=False → we handle it manually

# ── JWKS cache ────────────────────────────────────────────────────────────────

_jwks_cache: dict = {}
_jwks_fetched_at: float = 0.0
JWKS_TTL = 3600


async def _get_jwks() -> dict:
    global _jwks_cache, _jwks_fetched_at
    now = time.monotonic()
    if _jwks_cache and (now - _jwks_fetched_at) < JWKS_TTL:
        return _jwks_cache

    settings = get_settings()
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(settings.jwks_uri)
        resp.raise_for_status()
        _jwks_cache = resp.json()
        _jwks_fetched_at = now
        logger.info("jwks_refreshed", uri=settings.jwks_uri)
        return _jwks_cache


# ── JWT verification ──────────────────────────────────────────────────────────

async def _verify_jwt(token: str) -> PartnerContext:
    settings = get_settings()
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail={
            "error": "UNAUTHORIZED",
            "message": "Invalid or expired token",
            "details": [],
        },
        headers={"WWW-Authenticate": "Bearer"},
    )

    try:
        unverified_header = jwt.get_unverified_header(token)
        kid = unverified_header.get("kid")
        jwks = await _get_jwks()

        matching_key = None
        for key_data in jwks.get("keys", []):
            if key_data.get("kid") == kid:
                matching_key = key_data
                break

        if not matching_key:
            logger.warning("jwt_key_not_found", kid=kid)
            raise credentials_exception

        claims = jwt.decode(
            token,
            matching_key,
            algorithms=["RS256"],
            audience=settings.jwt_audience,
            issuer=settings.jwt_issuer,
            options={"verify_exp": True},
        )

        partner_id: Optional[str] = claims.get("partner_id") or claims.get("sub")
        if not partner_id:
            raise credentials_exception

        return PartnerContext(
            partner_id=partner_id,
            auth_method="jwt",
            raw_claims=claims,
        )

    except JWTError as exc:
        logger.warning("jwt_verification_failed", error=str(exc))
        raise credentials_exception


# ── Unified auth dependency ───────────────────────────────────────────────────

async def get_partner(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> PartnerContext:
    """
    FastAPI dependency: authenticates via API key OR JWT Bearer.
    Attaches PartnerContext to request.state.partner.
    """
    api_key = request.headers.get("X-API-Key")

    if api_key:
        # Path 1: API key authentication
        ctx = await verify_api_key(request, api_key)
        request.state.partner = ctx
        return ctx

    if credentials:
        # Path 2: JWT Bearer authentication
        ctx = await _verify_jwt(credentials.credentials)
        request.state.partner = ctx
        return ctx

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail={
            "error": "UNAUTHORIZED",
            "message": "Provide X-API-Key header or Authorization: Bearer <token>",
            "details": [],
        },
        headers={"WWW-Authenticate": "Bearer"},
    )
