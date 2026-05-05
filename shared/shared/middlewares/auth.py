"""
shared/middlewares/auth.py — Request authentication & authorisation middleware.

Two paths are handled:
  1. Frontend via API Gateway  — header `x-apigateway-api-userinfo` (base64 JWT claims)
     → decode claims, resolve role, fetch Firestore permissions, check route permission.
  2. Service-to-service (OIDC) — `Authorization: Bearer <google-oidc-token>`
     → verify Google-signed token, check email against trusted service account allowlist.

Health-check and OPTIONS requests are always passed through.
"""

from __future__ import annotations

import base64
import json
import logging
import re
import time
from collections.abc import Collection
from typing import Any, Sequence

from cachetools import TTLCache
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module-level singletons (lazy-initialised on first request)
# ---------------------------------------------------------------------------
_roles_cache: TTLCache = TTLCache(maxsize=20, ttl=300)  # 5-minute TTL per role
_firestore_client = None


def _get_firestore_client(project: str, database: str):
    global _firestore_client
    if _firestore_client is None:
        from google.cloud import firestore
        _firestore_client = firestore.AsyncClient(project=project, database=database)
    return _firestore_client


# ---------------------------------------------------------------------------
# x-apigateway-api-userinfo decoding
# ---------------------------------------------------------------------------

def _decode_api_gateway_userinfo(header_value: str) -> dict:
    """Base64-decode and JSON-parse the API Gateway userinfo header."""
    padded = header_value + "=" * (-len(header_value) % 4)
    try:
        return json.loads(base64.urlsafe_b64decode(padded).decode("utf-8"))
    except Exception as exc:
        raise ValueError(f"Cannot decode x-apigateway-api-userinfo: {exc}") from exc


def _extract_role(claims: dict) -> str | None:
    """Pull role from claims, checking top-level and Firebase custom attributes."""
    if role := claims.get("role"):
        return role
    firebase = claims.get("firebase", {})
    attrs = firebase.get("sign_in_attributes") or firebase.get("claims", {})
    return attrs.get("role")


# ---------------------------------------------------------------------------
# Route permission matching
# ---------------------------------------------------------------------------

def _match_route_permission(
    method: str,
    path: str,
    route_permissions: Sequence[tuple[str, str, str]],
) -> str | None:
    """Return the required permission string for this method+path, or None if unguarded."""
    for (m, pattern, permission) in route_permissions:
        if m.upper() == method.upper() and re.search(pattern, path):
            return permission
    return None


# ---------------------------------------------------------------------------
# Firestore roles lookup (cached)
# ---------------------------------------------------------------------------

async def _get_role_permissions(
    role: str,
    firestore_project: str,
    firestore_database: str,
) -> list[str]:
    if role in _roles_cache:
        return _roles_cache[role]

    db = _get_firestore_client(firestore_project, firestore_database)
    doc = await db.collection("roles").document(role).get()
    if not doc.exists:
        logger.warning("Role document 'roles/%s' not found in Firestore", role)
        permissions: list[str] = []
    else:
        data = doc.to_dict() or {}
        permissions = data.get("permissions", [])

    _roles_cache[role] = permissions
    return permissions


# ---------------------------------------------------------------------------
# OIDC verification for service-to-service calls
# ---------------------------------------------------------------------------

def _verify_oidc_token(token: str) -> dict[str, Any]:
    from google.auth.transport import requests as google_requests
    from google.oauth2 import id_token

    request = google_requests.Request()
    # verify_oauth2_token checks signature, expiry, and issuer
    return dict(id_token.verify_oauth2_token(token, request))


def _is_trusted_service(claims: dict, trusted_accounts: Collection[str]) -> bool:
    email = claims.get("email", "")
    return bool(email) and claims.get("email_verified", False) and email in trusted_accounts


# ---------------------------------------------------------------------------
# Middleware
# ---------------------------------------------------------------------------

class AuthMiddleware(BaseHTTPMiddleware):
    """
    ASGI middleware handling two authentication flows:
      - API Gateway (frontend): x-apigateway-api-userinfo header
      - Service-to-service: Google OIDC Bearer token
    """

    def __init__(
        self,
        app,
        *,
        route_permissions: list[tuple[str, str, str]],
        roles_firestore_project: str,
        roles_firestore_database: str,
        trusted_service_accounts: list[str],
        skip_paths: list[str] | None = None,
    ) -> None:
        super().__init__(app)
        self._route_permissions = route_permissions
        self._fs_project = roles_firestore_project
        self._fs_database = roles_firestore_database
        self._trusted_accounts = set(trusted_service_accounts)
        self._skip_paths: set[str] = set(skip_paths or ["/health"])

    async def dispatch(self, request: Request, call_next):
        # Always pass through health-check and CORS preflight
        if request.method == "OPTIONS" or request.url.path in self._skip_paths:
            return await call_next(request)

        gw_header = request.headers.get("x-apigateway-api-userinfo")
        auth_header = request.headers.get("authorization", "")

        if gw_header:
            return await self._handle_frontend(request, call_next, gw_header)

        if auth_header.startswith("Bearer "):
            return await self._handle_service(request, call_next, auth_header[7:])

        return JSONResponse({"detail": "Authentication required."}, status_code=401)

    # ------------------------------------------------------------------
    # Frontend path (API Gateway → service)
    # ------------------------------------------------------------------

    async def _handle_frontend(self, request: Request, call_next, gw_header: str):
        try:
            claims = _decode_api_gateway_userinfo(gw_header)
        except ValueError as exc:
            logger.warning("Bad x-apigateway-api-userinfo: %s", exc)
            return JSONResponse({"detail": "Malformed gateway user header."}, status_code=401)

        uid = claims.get("sub") or claims.get("user_id")
        role = _extract_role(claims)
        email = claims.get("email", "")

        if not uid or not role:
            return JSONResponse({"detail": "Token missing uid or role."}, status_code=401)

        required = _match_route_permission(
            request.method, request.url.path, self._route_permissions
        )

        if required is not None:
            try:
                permissions = await _get_role_permissions(
                    role, self._fs_project, self._fs_database
                )
            except Exception as exc:
                logger.error("Firestore roles lookup failed: %s", exc)
                return JSONResponse({"detail": "Authorization unavailable."}, status_code=503)

            if required not in permissions:
                logger.info(
                    "Permission denied uid=%s role=%s required=%s path=%s",
                    uid, role, required, request.url.path,
                )
                return JSONResponse({"detail": "Forbidden: insufficient permissions."}, status_code=403)

        request.state.user = {"uid": uid, "role": role, "email": email}
        return await call_next(request)

    # ------------------------------------------------------------------
    # Service-to-service path (OIDC Bearer token)
    # ------------------------------------------------------------------

    async def _handle_service(self, request: Request, call_next, token: str):
        try:
            claims = _verify_oidc_token(token)
        except Exception as exc:
            logger.warning("OIDC token verification failed: %s", exc)
            return JSONResponse({"detail": "Invalid service token."}, status_code=401)

        if not _is_trusted_service(claims, self._trusted_accounts):
            logger.warning(
                "Untrusted service account '%s' attempted access to %s",
                claims.get("email", "<unknown>"),
                request.url.path,
            )
            return JSONResponse({"detail": "Service account not authorised."}, status_code=403)

        request.state.user = {
            "uid": claims.get("sub"),
            "service": claims.get("email"),
        }
        return await call_next(request)
