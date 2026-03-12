"""
middleware/auth.py — JWT Bearer token verification.

Flow:
  1. Extract Bearer token from Authorization header
  2. Fetch JWKS from provider (cached 1hr)
  3. Verify signature, expiry, audience, issuer
  4. Extract partner_id from claims → attach to request.state

Compatible with:
  - Firebase Authentication (default)
  - Auth0
  - GCP Identity Platform
  - Any standard OAuth2 provider with JWKS endpoint
"""
from __future__ import annotations

import time
from typing import Optional
from functools import lru_cache

import httpx
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt, jwk
from jose.utils import base64url_decode

from config import get_settings
from logging_config import get_logger

logger = get_logger(__name__)
security = HTTPBearer()

# ── JWKS cache (refresh every 3600s) ─────────────────────────────────────────

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


# ── Token verification ────────────────────────────────────────────────────────

class PartnerContext:
    """Attach to request.state.partner after successful auth."""
    def __init__(self, partner_id: str, raw_claims: dict):
        self.partner_id = partner_id
        self.raw_claims = raw_claims


async def verify_jwt(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> PartnerContext:
    settings = get_settings()
    token = credentials.credentials

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
        # Decode header to get 'kid' (key ID)
        unverified_header = jwt.get_unverified_header(token)
        kid = unverified_header.get("kid")

        jwks = await _get_jwks()
        # Find the matching key
        matching_key = None
        for key_data in jwks.get("keys", []):
            if key_data.get("kid") == kid:
                matching_key = key_data
                break

        if not matching_key:
            logger.warning("jwt_key_not_found", kid=kid)
            raise credentials_exception

        # Verify and decode
        claims = jwt.decode(
            token,
            matching_key,
            algorithms=["RS256"],
            audience=settings.jwt_audience,
            issuer=settings.jwt_issuer,
            options={"verify_exp": True},
        )

        # Extract partner_id — look for custom claim, fallback to 'sub'
        partner_id: Optional[str] = claims.get("partner_id") or claims.get("sub")
        if not partner_id:
            logger.warning("jwt_missing_partner_id")
            raise credentials_exception

        return PartnerContext(partner_id=partner_id, raw_claims=claims)

    except JWTError as exc:
        logger.warning("jwt_verification_failed", error=str(exc))
        raise credentials_exception


# ── FastAPI dependency shorthand ──────────────────────────────────────────────

async def get_partner(
    request: Request,
    partner_ctx: PartnerContext = Depends(verify_jwt),
) -> PartnerContext:
    """
    Dependency: verifies JWT and attaches PartnerContext to request.state.
    Use as: partner: PartnerContext = Depends(get_partner)
    """
    request.state.partner = partner_ctx
    return partner_ctx
