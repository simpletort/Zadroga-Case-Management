# """
# shared/middlewares/auth.py — Request authentication & authorisation middleware.

# Two paths are handled:
#   1. Frontend via API Gateway  — header `x-apigateway-api-userinfo` (base64 JWT claims)
#      → decode claims, resolve role, fetch Firestore permissions, check route permission.
#   2. Service-to-service (OIDC) — `Authorization: Bearer <google-oidc-token>`
#      → verify Google-signed token, check email against trusted service account allowlist.

# Health-check and OPTIONS requests are always passed through.
# """

# from __future__ import annotations

# import base64
# import json
# import logging
# import re
# import time
# from collections.abc import Collection
# from typing import Any, Sequence

# from cachetools import TTLCache
# from starlette.middleware.base import BaseHTTPMiddleware
# from starlette.requests import Request
# from starlette.responses import JSONResponse

# logger = logging.getLogger(__name__)

# # ---------------------------------------------------------------------------
# # Module-level singletons (lazy-initialised on first request)
# # ---------------------------------------------------------------------------
# _roles_cache: TTLCache = TTLCache(maxsize=20, ttl=300)  # 5-minute TTL per role
# _firestore_client = None


# def _get_firestore_client(project: str, database: str):
#     global _firestore_client
#     if _firestore_client is None:
#         from google.cloud import firestore
#         _firestore_client = firestore.AsyncClient(project=project, database=database)
#     return _firestore_client


# # ---------------------------------------------------------------------------
# # x-apigateway-api-userinfo decoding
# # ---------------------------------------------------------------------------

# def _decode_api_gateway_userinfo(header_value: str) -> dict:
#     """Base64-decode and JSON-parse the API Gateway userinfo header."""
#     padded = header_value + "=" * (-len(header_value) % 4)
#     try:
#         return json.loads(base64.urlsafe_b64decode(padded).decode("utf-8"))
#     except Exception as exc:
#         raise ValueError(f"Cannot decode x-apigateway-api-userinfo: {exc}") from exc


# def _extract_role(claims: dict) -> str | None:
#     """Pull role from claims, checking top-level and Firebase custom attributes."""
#     if role := claims.get("role"):
#         return role
#     firebase = claims.get("firebase", {})
#     attrs = firebase.get("sign_in_attributes") or firebase.get("claims", {})
#     return attrs.get("role")


# # ---------------------------------------------------------------------------
# # Route permission matching
# # ---------------------------------------------------------------------------

# def _match_route_permission(
#     method: str,
#     path: str,
#     route_permissions: Sequence[tuple[str, str, str]],
# ) -> str | None:
#     """Return the required permission string for this method+path, or None if unguarded."""
#     for (m, pattern, permission) in route_permissions:
#         if m.upper() == method.upper() and re.search(pattern, path):
#             return permission
#     return None


# # ---------------------------------------------------------------------------
# # Firestore roles lookup (cached)
# # ---------------------------------------------------------------------------

# async def _get_role_permissions(
#     role: str,
#     firestore_project: str,
#     firestore_database: str,
# ) -> list[str]:
#     if role in _roles_cache:
#         return _roles_cache[role]

#     db = _get_firestore_client(firestore_project, firestore_database)
#     doc = await db.collection("roles").document(role).get()
#     if not doc.exists:
#         logger.warning("Role document 'roles/%s' not found in Firestore", role)
#         permissions: list[str] = []
#     else:
#         data = doc.to_dict() or {}
#         permissions = data.get("permissions", [])

#     _roles_cache[role] = permissions
#     return permissions


# # ---------------------------------------------------------------------------
# # OIDC verification for service-to-service calls
# # ---------------------------------------------------------------------------

# def _verify_oidc_token(token: str) -> dict[str, Any]:
#     from google.auth.transport import requests as google_requests
#     from google.oauth2 import id_token

#     request = google_requests.Request()
#     # verify_oauth2_token checks signature, expiry, and issuer
#     return dict(id_token.verify_oauth2_token(token, request))


# def _is_trusted_service(claims: dict, trusted_accounts: Collection[str]) -> bool:
#     email = claims.get("email", "")
#     return bool(email) and claims.get("email_verified", False) and email in trusted_accounts


# # ---------------------------------------------------------------------------
# # Middleware
# # ---------------------------------------------------------------------------

# class AuthMiddleware(BaseHTTPMiddleware):
#     """
#     ASGI middleware handling two authentication flows:
#       - API Gateway (frontend): x-apigateway-api-userinfo header
#       - Service-to-service: Google OIDC Bearer token
#     """

#     def __init__(
#         self,
#         app,
#         *,
#         route_permissions: list[tuple[str, str, str]],
#         roles_firestore_project: str,
#         roles_firestore_database: str,
#         trusted_service_accounts: list[str],
#         skip_paths: list[str] | None = None,
#     ) -> None:
#         super().__init__(app)
#         self._route_permissions = route_permissions
#         self._fs_project = roles_firestore_project
#         self._fs_database = roles_firestore_database
#         self._trusted_accounts = set(trusted_service_accounts)
#         self._skip_paths: set[str] = set(skip_paths or ["/health"])

#     async def dispatch(self, request: Request, call_next):
#         # Always pass through health-check and CORS preflight
#         if request.method == "OPTIONS" or request.url.path in self._skip_paths:
#             return await call_next(request)

#         gw_header = request.headers.get("x-apigateway-api-userinfo")
#         auth_header = request.headers.get("authorization", "")

#         if gw_header:
#             return await self._handle_frontend(request, call_next, gw_header)

#         if auth_header.startswith("Bearer "):
#             return await self._handle_service(request, call_next, auth_header[7:])

#         return JSONResponse({"detail": "Authentication required."}, status_code=401)

#     # ------------------------------------------------------------------
#     # Frontend path (API Gateway → service)
#     # ------------------------------------------------------------------

#     async def _handle_frontend(self, request: Request, call_next, gw_header: str):
#         try:
#             claims = _decode_api_gateway_userinfo(gw_header)
#         except ValueError as exc:
#             logger.warning("Bad x-apigateway-api-userinfo: %s", exc)
#             return JSONResponse({"detail": "Malformed gateway user header."}, status_code=401)

#         uid = claims.get("sub") or claims.get("user_id")
#         role = _extract_role(claims)
#         email = claims.get("email", "")

#         if not uid or not role:
#             return JSONResponse({"detail": "Token missing uid or role."}, status_code=401)

#         required = _match_route_permission(
#             request.method, request.url.path, self._route_permissions
#         )

#         if required is not None:
#             try:
#                 permissions = await _get_role_permissions(
#                     role, self._fs_project, self._fs_database
#                 )
#             except Exception as exc:
#                 logger.error("Firestore roles lookup failed: %s", exc)
#                 return JSONResponse({"detail": "Authorization unavailable."}, status_code=503)

#             if required not in permissions:
#                 logger.info(
#                     "Permission denied uid=%s role=%s required=%s path=%s",
#                     uid, role, required, request.url.path,
#                 )
#                 return JSONResponse({"detail": "Forbidden: insufficient permissions."}, status_code=403)

#         request.state.user = {"uid": uid, "role": role, "email": email}
#         return await call_next(request)

#     # ------------------------------------------------------------------
#     # Service-to-service path (OIDC Bearer token)
#     # ------------------------------------------------------------------

#     async def _handle_service(self, request: Request, call_next, token: str):
#         try:
#             claims = _verify_oidc_token(token)
#         except Exception as exc:
#             logger.warning("OIDC token verification failed: %s", exc)
#             return JSONResponse({"detail": "Invalid service token."}, status_code=401)

#         if not _is_trusted_service(claims, self._trusted_accounts):
#             logger.warning(
#                 "Untrusted service account '%s' attempted access to %s",
#                 claims.get("email", "<unknown>"),
#                 request.url.path,
#             )
#             return JSONResponse({"detail": "Service account not authorised."}, status_code=403)

#         request.state.user = {
#             "uid": claims.get("sub"),
#             "service": claims.get("email"),
#         }
#         return await call_next(request)


"""
shared/middlewares/auth.py — Unified authentication & authorisation middleware.

Auth priority order (checked in this sequence):
  1. x-apigateway-api-userinfo header present
       → Request came through GCP API Gateway which already verified the Firebase JWT.
       → Decode the base64 claims blob, extract uid/role, check Firestore permissions.
  2. X-API-Key header present
       → Marketing partner submitting leads via external API.
       → Verify key hash against Firestore partners collection, check IP allowlist + HMAC.
       → Sets request.state.partner (PartnerContext) and request.state.user.
  3. Authorization: Bearer <token> where iss = securetoken.google.com
       → Staff member calling directly (dev/staging without API Gateway in front, or
         when the gateway is in passthrough mode).
       → Verify Firebase JWT signature, extract uid/role from custom claims.
  4. Authorization: Bearer <token> where iss = accounts.google.com
       → Service-to-service OIDC call from a trusted Cloud Run / Cloud Tasks SA.
       → Verify Google-signed token, check SA email against trusted allowlist.
  5. None of the above → 401.

Routes that require a specific permission key are checked against a Firestore
`roles/{role}` document (5-minute TTL cache). Routes not in the permission map
pass through once the caller is authenticated.

Health-check and OPTIONS requests always pass through without any auth check.
"""
from __future__ import annotations

import base64
import hashlib
import hmac as hmac_lib
import ipaddress
import json
import logging
import re
import time
from collections.abc import Collection
from dataclasses import dataclass, field
from typing import Any, Sequence

import httpx
from cachetools import TTLCache
from jose import JWTError, jwt
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# PartnerContext — attached to request.state.partner after successful auth.
# Routers import this from shared rather than from middleware.partner_auth.
# ---------------------------------------------------------------------------

@dataclass
class PartnerContext:
    """Result of any successful authentication. Always present on request.state.partner."""
    partner_id:   str          # Firebase uid (staff) or Firestore partner doc id (API key)
    auth_method:  str          # "gateway" | "api_key" | "firebase_jwt" | "oidc"
    role:         str  = ""    # Firebase custom claim role value (staff paths only)
    partner_name: str  = ""    # Partner display name (API key path only)
    ip_verified:  bool = False
    hmac_verified: bool = False
    raw_claims:   dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Module-level singletons
# ---------------------------------------------------------------------------

_roles_cache: TTLCache = TTLCache(maxsize=100, ttl=300)  # 5-min per (project, database, role)
_firestore_clients: dict[tuple[str, str], Any] = {}
_firebase_jwks_cache:  dict  = {}
_firebase_jwks_fetched: float = 0.0
_JWKS_TTL = 3600  # 1 hour


def _get_firestore_client(project: str, database: str):
    key = (project, database)
    client = _firestore_clients.get(key)
    if client is None:
        from google.cloud import firestore
        client = firestore.AsyncClient(project=project, database=database)
        _firestore_clients[key] = client
    return client


# ---------------------------------------------------------------------------
# Firebase JWKS (PEM certs from Google)
# ---------------------------------------------------------------------------

async def _get_firebase_jwks() -> dict:
    """Fetch and cache Google's X.509 public certs for Firebase JWT verification."""
    global _firebase_jwks_cache, _firebase_jwks_fetched
    now = time.monotonic()
    if _firebase_jwks_cache and (now - _firebase_jwks_fetched) < _JWKS_TTL:
        return _firebase_jwks_cache
    url = "https://www.googleapis.com/robot/v1/metadata/x509/securetoken@system.gserviceaccount.com"
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        _firebase_jwks_cache   = resp.json()
        _firebase_jwks_fetched = now
    logger.debug("firebase_jwks_refreshed")
    return _firebase_jwks_cache


# ---------------------------------------------------------------------------
# Token-type sniffing (fast, no network)
# ---------------------------------------------------------------------------

def _is_firebase_token(token: str) -> bool:
    """Return True if the JWT was issued by Firebase Auth (securetoken.google.com)."""
    try:
        iss = jwt.get_unverified_claims(token).get("iss", "")
        return iss.startswith("https://securetoken.google.com/")
    except Exception:
        return False


def _is_google_oidc_token(token: str) -> bool:
    """Return True if the JWT was issued by Google OIDC (service-to-service)."""
    try:
        iss = jwt.get_unverified_claims(token).get("iss", "")
        return iss in (
            "https://accounts.google.com",
            "accounts.google.com",
        )
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Path 1 — API Gateway: x-apigateway-api-userinfo
# ---------------------------------------------------------------------------

def _decode_api_gateway_userinfo(header_value: str) -> dict:
    """Base64url-decode the API Gateway claims blob injected after JWT verification."""
    padded = header_value + "=" * (-len(header_value) % 4)
    try:
        return json.loads(base64.urlsafe_b64decode(padded).decode("utf-8"))
    except Exception as exc:
        raise ValueError(f"Cannot decode x-apigateway-api-userinfo: {exc}") from exc


def _extract_role(claims: dict) -> str:
    """Pull role from JWT claims, checking both top-level and Firebase custom attributes."""
    if role := claims.get("role"):
        return str(role)
    firebase = claims.get("firebase", {})
    attrs = firebase.get("sign_in_attributes") or firebase.get("claims", {})
    return str(attrs.get("role", ""))


# ---------------------------------------------------------------------------
# Path 2 — Partner API key (X-API-Key header)
# ---------------------------------------------------------------------------

def _hash_key(api_key: str) -> str:
    return hashlib.sha256(api_key.encode()).hexdigest()


def _get_client_ip(request: Request) -> str:
    forwarded = request.headers.get("X-Forwarded-For", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "0.0.0.0"


def _ip_allowed(client_ip: str, allowed_ips: list[str]) -> bool:
    if not allowed_ips:
        return True
    try:
        addr = ipaddress.ip_address(client_ip)
        for entry in allowed_ips:
            try:
                if "/" in entry:
                    if addr in ipaddress.ip_network(entry, strict=False):
                        return True
                elif ipaddress.ip_address(entry) == addr:
                    return True
            except ValueError:
                continue
    except ValueError:
        pass
    return False


async def _get_hmac_secret(secret_name: str, gcp_project_id: str) -> str:
    """Fetch HMAC secret from Secret Manager (sync call wrapped for async context)."""
    from google.cloud import secretmanager
    sm = secretmanager.SecretManagerServiceClient()
    name = f"projects/{gcp_project_id}/secrets/{secret_name}/versions/latest"
    response = sm.access_secret_version(request={"name": name})
    return response.payload.data.decode("utf-8").strip()


async def _verify_hmac(
    request: Request,
    partner_doc: dict,
    body: bytes,
    gcp_project_id: str,
    hmac_max_age: int,
) -> bool:
    sig_header = request.headers.get("X-Signature", "")
    ts_header  = request.headers.get("X-Timestamp", "")
    if not sig_header or not ts_header:
        return False
    try:
        req_time = int(ts_header)
    except ValueError:
        return False
    if abs(int(time.time()) - req_time) > hmac_max_age:
        logger.warning("hmac_timestamp_expired partner_id=%s", partner_doc.get("partnerId"))
        return False
    secret_name = partner_doc.get("hmacSecretName")
    if not secret_name:
        return False
    try:
        secret = await _get_hmac_secret(secret_name, gcp_project_id)
    except Exception as exc:
        logger.error("hmac_secret_fetch_failed error=%s", exc)
        return False
    body_hash = hashlib.sha256(body).hexdigest()
    message = f"{ts_header}\n{request.method.upper()}\n{request.url.path}\n{body_hash}".encode()
    expected = hmac_lib.new(secret.encode(), message, hashlib.sha256).hexdigest()
    return hmac_lib.compare_digest(expected, sig_header)


async def _verify_api_key(
    request: Request,
    api_key: str,
    *,
    firestore_project: str,
    firestore_database: str,
    partners_collection: str,
    request_logs_collection: str,
    gcp_project_id: str,
    hmac_max_age: int,
) -> PartnerContext:
    """Verify X-API-Key against Firestore partner records."""
    from google.cloud import firestore as _fs

    db = _get_firestore_client(firestore_project, firestore_database)
    key_hash = _hash_key(api_key)

    partner_doc_data: dict | None = None
    partner_id: str | None = None

    query = db.collection(partners_collection).where("active", "==", True)
    async for doc in query.stream():
        data = doc.to_dict()
        for key_entry in data.get("apiKeys", []):
            if key_entry.get("active", False) and key_entry.get("keyHash") == key_hash:
                import datetime
                expires_at = key_entry.get("expiresAt")
                if expires_at and isinstance(expires_at, datetime.datetime):
                    if expires_at < datetime.datetime.utcnow():
                        logger.warning("api_key_expired partner_id=%s", doc.id)
                        raise _api_key_unauthorized()
                partner_doc_data = data
                partner_id = doc.id
                break
        if partner_id:
            break

    if not partner_doc_data or not partner_id:
        logger.warning("api_key_not_found key_prefix=%s", api_key[:8])
        raise _api_key_unauthorized()

    client_ip = _get_client_ip(request)
    if not _ip_allowed(client_ip, partner_doc_data.get("allowedIps", [])):
        logger.warning("ip_not_allowed partner_id=%s ip=%s", partner_id, client_ip)
        raise _api_key_unauthorized()

    hmac_verified = False
    if partner_doc_data.get("requireHmac", False):
        body = await request.body()
        if not await _verify_hmac(request, partner_doc_data, body, gcp_project_id, hmac_max_age):
            logger.warning("hmac_verification_failed partner_id=%s", partner_id)
            raise _api_key_unauthorized()
        hmac_verified = True

    # Non-blocking request log
    try:
        import datetime
        partner_ref = db.collection(partners_collection).document(partner_id)
        await partner_ref.update({
            "requestCount": _fs.Increment(1),
            "lastRequestAt": _fs.SERVER_TIMESTAMP,
        })
        await partner_ref.collection(request_logs_collection).document().set({
            "timestamp":  _fs.SERVER_TIMESTAMP,
            "method":     request.method,
            "path":       request.url.path,
            "ip":         client_ip,
            "userAgent":  request.headers.get("User-Agent", ""),
        })
    except Exception as exc:
        logger.error("partner_request_log_failed error=%s", exc)

    logger.info("api_key_auth_success partner_id=%s hmac=%s", partner_id, hmac_verified)
    return PartnerContext(
        partner_id    = partner_id,
        auth_method   = "api_key",
        partner_name  = partner_doc_data.get("name", ""),
        ip_verified   = True,
        hmac_verified = hmac_verified,
        # raw_claims is empty for API key auth (no JWT), but role key must exist
        # so downstream checks like partner.raw_claims.get("role") return "" not KeyError
        raw_claims    = {},
    )


def _api_key_unauthorized() -> None:
    """Raise a 401 HTTPException for API key failures (generic to prevent enumeration)."""
    from fastapi import HTTPException as _HTTPException, status as _status
    raise _HTTPException(
        status_code=_status.HTTP_401_UNAUTHORIZED,
        detail={
            "error":   "UNAUTHORIZED",
            "message": "Invalid API key or unauthorized request.",
            "details": [],
        },
    )


# ---------------------------------------------------------------------------
# Path 3 — Firebase JWT (direct, no API Gateway)
# ---------------------------------------------------------------------------

async def _verify_firebase_jwt(
    token: str,
    *,
    firebase_project_id: str,
    app_env: str,
) -> PartnerContext:
    """
    Verify a Firebase Auth ID token.

    In development/test: skips signature + expiry checks to allow emulator tokens.
    In production: full RS256 verification against Google public certs.
    """
    unauth = JSONResponse(
        {"detail": "Invalid or expired Firebase token."},
        status_code=401,
    )

    try:
        if app_env in ("development", "test"):
            claims = jwt.decode(
                token, key="", algorithms=["RS256"],
                options={"verify_signature": False, "verify_exp": False, "verify_aud": False},
            )
        else:
            firebase_certs = await _get_firebase_jwks()
            kid = jwt.get_unverified_header(token).get("kid")
            pem_key = firebase_certs.get(kid)
            if not pem_key:
                logger.warning("firebase_jwt_kid_not_found kid=%s", kid)
                return unauth
            issuer = f"https://securetoken.google.com/{firebase_project_id}"
            claims = jwt.decode(
                token, pem_key, algorithms=["RS256"],
                audience=firebase_project_id,
                issuer=issuer,
                options={"verify_exp": True},
            )

        uid    = claims.get("user_id") or claims.get("uid") or claims.get("sub")
        role   = claims.get("role", "admin_staff")
        active = claims.get("active", True)

        if not uid:
            return unauth
        if not active:
            return JSONResponse({"detail": "Account is inactive."}, status_code=403)

        logger.info("firebase_jwt_verified uid=%s role=%s", uid, role)
        return PartnerContext(
            partner_id  = uid,
            auth_method = "firebase_jwt",
            role        = role,
            raw_claims  = {**claims, "role": role, "uid": uid},
        )

    except JWTError as exc:
        logger.warning("firebase_jwt_verification_failed error=%s", exc)
        return unauth


# ---------------------------------------------------------------------------
# Path 4 — Google OIDC (service-to-service)
# ---------------------------------------------------------------------------

def _verify_oidc_token(token: str) -> dict[str, Any]:
    from google.auth.transport import requests as google_requests
    from google.oauth2 import id_token
    return dict(id_token.verify_oauth2_token(token, google_requests.Request()))


def _is_trusted_service(claims: dict, trusted_accounts: Collection[str]) -> bool:
    email = claims.get("email", "")
    return bool(email) and claims.get("email_verified", False) and email in trusted_accounts


# ---------------------------------------------------------------------------
# Firestore roles lookup (cached, path 1 + 3)
# ---------------------------------------------------------------------------

async def _get_role_permissions(
    role: str,
    firestore_project: str,
    firestore_database: str,
) -> list[str]:
    cache_key = (firestore_project, firestore_database, role)
    if cache_key in _roles_cache:
        return _roles_cache[cache_key]
    db = _get_firestore_client(firestore_project, firestore_database)
    doc = await db.collection("roles").document(role).get()
    if not doc.exists:
        logger.warning(
            "Role document 'roles/%s' not found in Firestore project=%s database=%s",
            role, firestore_project, firestore_database,
        )
        permissions: list[str] = []
    else:
        permissions = (doc.to_dict() or {}).get("permissions", [])
    _roles_cache[cache_key] = permissions
    return permissions


# ---------------------------------------------------------------------------
# Route permission matching
# ---------------------------------------------------------------------------

def _match_route_permission(
    method: str,
    path: str,
    route_permissions: Sequence[tuple[str, str, str]],
) -> str | None:
    for (m, pattern, permission) in route_permissions:
        if m.upper() == method.upper() and re.search(pattern, path):
            return permission
    return None


# ---------------------------------------------------------------------------
# Middleware
# ---------------------------------------------------------------------------

class AuthMiddleware(BaseHTTPMiddleware):
    """
    Unified ASGI authentication middleware for SimpleTort services.

    Constructor params
    ------------------
    route_permissions        : list of (METHOD, url_regex, permission_key) tuples
    roles_firestore_project  : GCP project id for Firestore roles lookup
    roles_firestore_database : Firestore database name (e.g. "simpletort-dev")
    trusted_service_accounts : list[str] of SA emails for OIDC path
    skip_paths               : list[str] of paths that always pass (default: ["/health"])
    # Partner-key params (only needed if service uses X-API-Key auth):
    partners_collection      : Firestore collection name for partners (default: "partners")
    request_logs_collection  : subcollection name for request logs (default: "request_logs")
    gcp_project_id           : GCP project for Secret Manager HMAC secrets
    hmac_max_age_seconds     : max timestamp age for HMAC verification (default: 300)
    firebase_project_id      : Firebase project id for JWT issuer/audience check
    app_env                  : "development" | "test" | "production" — controls JWT strictness
    """

    def __init__(
        self,
        app,
        *,
        route_permissions:        list[tuple[str, str, str]],
        roles_firestore_project:  str,
        roles_firestore_database: str,
        trusted_service_accounts: list[str] | str = "",
        skip_paths:               list[str] | None = None,
        # Partner key config
        partners_collection:      str  = "partners",
        request_logs_collection:  str  = "request_logs",
        gcp_project_id:           str  = "",
        hmac_max_age_seconds:     int  = 300,
        # Firebase JWT config
        firebase_project_id:      str  = "",
        app_env:                  str  = "production",
    ) -> None:
        super().__init__(app)
        self._route_permissions = route_permissions
        self._fs_project  = roles_firestore_project
        self._fs_database = roles_firestore_database

        # Accept both list[str] and comma-separated string
        if isinstance(trusted_service_accounts, str):
            self._trusted_accounts = {
                e.strip() for e in trusted_service_accounts.split(",") if e.strip()
            }
        else:
            self._trusted_accounts = set(trusted_service_accounts)

        self._skip_paths            = set(skip_paths or ["/health"])
        self._partners_collection   = partners_collection
        self._request_logs_coll     = request_logs_collection
        self._gcp_project_id        = gcp_project_id or roles_firestore_project
        self._hmac_max_age          = hmac_max_age_seconds
        self._firebase_project_id   = firebase_project_id or roles_firestore_project
        self._app_env               = app_env

    # ------------------------------------------------------------------

    async def dispatch(self, request: Request, call_next):
        if request.method == "OPTIONS" or request.url.path in self._skip_paths:
            return await call_next(request)

        gw_header   = request.headers.get("x-apigateway-api-userinfo")
        api_key     = request.headers.get("X-API-Key")
        auth_header = request.headers.get("authorization", "")

        # ── Path 1: API Gateway ───────────────────────────────────────
        if gw_header:
            return await self._handle_gateway(request, call_next, gw_header)

        # ── Path 2: Partner API key ───────────────────────────────────
        if api_key:
            return await self._handle_api_key(request, call_next, api_key)

        # ── Path 3 & 4: Bearer token ──────────────────────────────────
        if auth_header.startswith("Bearer "):
            token = auth_header[7:]
            if _is_firebase_token(token):
                return await self._handle_firebase_jwt(request, call_next, token)
            if _is_google_oidc_token(token):
                return await self._handle_oidc(request, call_next, token)
            # Unknown issuer — try Firebase first (catches emulator tokens without iss)
            return await self._handle_firebase_jwt(request, call_next, token)

        return JSONResponse(
            {"detail": "Authentication required. Provide X-API-Key or Authorization: Bearer <token>."},
            status_code=401,
        )

    # ------------------------------------------------------------------
    # Path 1 — API Gateway userinfo header
    # ------------------------------------------------------------------

    async def _handle_gateway(self, request: Request, call_next, gw_header: str):
        try:
            claims = _decode_api_gateway_userinfo(gw_header)
        except ValueError as exc:
            logger.warning("Bad x-apigateway-api-userinfo: %s", exc)
            return JSONResponse({"detail": "Malformed gateway user header."}, status_code=401)

        uid  = claims.get("sub") or claims.get("user_id")
        role = _extract_role(claims)
        email = claims.get("email", "")

        if not uid or not role:
            return JSONResponse({"detail": "Token missing uid or role."}, status_code=401)

        result = await self._check_permission(request, role)
        if result is not None:
            return result

        ctx = PartnerContext(
            partner_id  = uid,
            auth_method = "gateway",
            role        = role,
            raw_claims  = claims,
        )
        request.state.partner = ctx
        request.state.user    = {"uid": uid, "role": role, "email": email}
        return await call_next(request)

    # ------------------------------------------------------------------
    # Path 2 — Partner API key
    # ------------------------------------------------------------------

    async def _handle_api_key(self, request: Request, call_next, api_key: str):
        try:
            ctx = await _verify_api_key(
                request, api_key,
                firestore_project       = self._fs_project,
                firestore_database      = self._fs_database,
                partners_collection     = self._partners_collection,
                request_logs_collection = self._request_logs_coll,
                gcp_project_id          = self._gcp_project_id,
                hmac_max_age            = self._hmac_max_age,
            )
        except Exception:
            return JSONResponse(
                {"detail": "Invalid API key or unauthorized request."},
                status_code=401,
            )

        request.state.partner = ctx
        request.state.user    = {"uid": ctx.partner_id, "role": "partner", "email": ""}
        return await call_next(request)

    # ------------------------------------------------------------------
    # Path 3 — Firebase JWT (direct Bearer)
    # ------------------------------------------------------------------

    async def _handle_firebase_jwt(self, request: Request, call_next, token: str):
        result = await _verify_firebase_jwt(
            token,
            firebase_project_id = self._firebase_project_id,
            app_env             = self._app_env,
        )

        # _verify_firebase_jwt returns JSONResponse on failure, PartnerContext on success
        if isinstance(result, JSONResponse):
            return result

        ctx: PartnerContext = result
        perm_result = await self._check_permission(request, ctx.role)
        if perm_result is not None:
            return perm_result

        request.state.partner = ctx
        request.state.user    = {
            "uid":   ctx.partner_id,
            "role":  ctx.role,
            "email": ctx.raw_claims.get("email", ""),
        }
        return await call_next(request)

    # ------------------------------------------------------------------
    # Path 4 — Google OIDC (service-to-service)
    # ------------------------------------------------------------------

    async def _handle_oidc(self, request: Request, call_next, token: str):
        try:
            claims = _verify_oidc_token(token)
        except Exception as exc:
            logger.warning("OIDC token verification failed: %s", exc)
            return JSONResponse({"detail": "Invalid service token."}, status_code=401)

        if not _is_trusted_service(claims, self._trusted_accounts):
            logger.warning(
                "Untrusted service account '%s' on %s",
                claims.get("email", "<unknown>"),
                request.url.path,
            )
            return JSONResponse({"detail": "Service account not authorised."}, status_code=403)

        ctx = PartnerContext(
            partner_id  = claims.get("sub", ""),
            auth_method = "oidc",
            raw_claims  = claims,
        )
        request.state.partner = ctx
        request.state.user    = {"uid": claims.get("sub"), "service": claims.get("email")}
        return await call_next(request)

    # ------------------------------------------------------------------
    # Permission check (shared by gateway + firebase_jwt paths)
    # ------------------------------------------------------------------

    async def _check_permission(
        self, request: Request, role: str
    ) -> JSONResponse | None:
        """
        Returns a JSONResponse if the role is denied, None if allowed.
        """
        required = _match_route_permission(
            request.method, request.url.path, self._route_permissions
        )
        if required is None:
            return None  # route not in map → no extra permission check

        try:
            permissions = await _get_role_permissions(
                role, self._fs_project, self._fs_database
            )
        except Exception as exc:
            logger.error("Firestore roles lookup failed: %s", exc)
            return JSONResponse({"detail": "Authorization unavailable."}, status_code=503)

        if required not in permissions:
            logger.info(
                "Permission denied role=%s required=%s path=%s",
                role, required, request.url.path,
            )
            return JSONResponse({"detail": "Forbidden: insufficient permissions."}, status_code=403)

        return None
