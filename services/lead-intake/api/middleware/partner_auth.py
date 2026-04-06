"""
api/middleware/partner_auth.py — API Key + HMAC request signing for marketing partners.

Authentication modes supported:
  1. API key only (header: X-API-Key)
  2. API key + HMAC signature (headers: X-API-Key, X-Signature, X-Timestamp)

IP allowlisting:
  - Partner document in Firestore may contain `allowedIps: [...]`
  - Empty list = allow all IPs

HMAC signing:
  - Algorithm: HMAC-SHA256
  - Message: f"{timestamp}\n{method}\n{path}\n{body_sha256}"
  - Secret: partner's HMAC secret (stored hashed in Firestore, plaintext in Secret Manager)
  - Timestamp window: configurable (default 5 minutes)

Partner document schema (/partners/{partnerId}):
  {
    partnerId: str,
    name: str,
    active: bool,
    allowedIps: list[str],   # [] = unrestricted
    requireHmac: bool,
    apiKeys: [
      {
        keyId: str,
        keyHash: str,         # SHA-256(key) hex
        createdAt: timestamp,
        expiresAt: timestamp | null,
        active: bool,
        label: str,
      }
    ],
    hmacSecretName: str | null,  # Secret Manager secret name
    requestCount: int,
    lastRequestAt: timestamp,
    createdAt: timestamp,
    updatedAt: timestamp,
  }
"""
from __future__ import annotations

import hashlib
import hmac
import ipaddress
import time
from dataclasses import dataclass, field
from typing import Optional

from fastapi import HTTPException, Request, status
from google.cloud import firestore, secretmanager

from config import get_settings
from logging_config import get_logger

logger = get_logger(__name__)

_db: Optional[firestore.AsyncClient] = None
_sm_client: Optional[secretmanager.SecretManagerServiceClient] = None


def _get_db() -> firestore.AsyncClient:
    global _db
    if _db is None:
        settings = get_settings()
        _db = firestore.AsyncClient(project=settings.gcp_project_id, database="simpletort-dev")
    return _db


def _get_sm() -> secretmanager.SecretManagerServiceClient:
    global _sm_client
    if _sm_client is None:
        _sm_client = secretmanager.SecretManagerServiceClient()
    return _sm_client


# ── Data classes ──────────────────────────────────────────────────────────────

@dataclass
class PartnerContext:
    """Attached to request.state.partner after successful auth."""
    partner_id: str
    auth_method: str  # "api_key" | "jwt"
    partner_name: str = ""
    raw_claims: dict = field(default_factory=dict)
    ip_verified: bool = False
    hmac_verified: bool = False


# ── Key hashing ───────────────────────────────────────────────────────────────

def _hash_key(api_key: str) -> str:
    """SHA-256 hash of the raw API key (hex digest)."""
    return hashlib.sha256(api_key.encode()).hexdigest()


# ── IP allowlist check ────────────────────────────────────────────────────────

def _get_client_ip(request: Request) -> str:
    """Extract real IP from X-Forwarded-For (Cloud Run sets this)."""
    forwarded = request.headers.get("X-Forwarded-For", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "0.0.0.0"


def _ip_allowed(client_ip: str, allowed_ips: list[str]) -> bool:
    """True if allowed_ips is empty (unrestricted) or client_ip is in the list."""
    if not allowed_ips:
        return True
    try:
        client_addr = ipaddress.ip_address(client_ip)
        for entry in allowed_ips:
            try:
                if "/" in entry:
                    if client_addr in ipaddress.ip_network(entry, strict=False):
                        return True
                elif ipaddress.ip_address(entry) == client_addr:
                    return True
            except ValueError:
                continue
    except ValueError:
        pass
    return False


# ── HMAC signature verification ───────────────────────────────────────────────

async def _get_hmac_secret(secret_name: str) -> str:
    """Fetch HMAC secret from Secret Manager."""
    settings = get_settings()
    sm = _get_sm()
    name = f"projects/{settings.gcp_project_id}/secrets/{secret_name}/versions/latest"
    response = sm.access_secret_version(request={"name": name})
    return response.payload.data.decode("utf-8").strip()


async def _verify_hmac(
    request: Request,
    partner_doc: dict,
    body: bytes,
) -> bool:
    """
    Verify HMAC-SHA256 signature.
    Returns True if valid, False if verification fails (caller decides severity).
    """
    settings = get_settings()
    signature_header = request.headers.get("X-Signature", "")
    timestamp_header = request.headers.get("X-Timestamp", "")

    if not signature_header or not timestamp_header:
        return False

    # Timestamp must be recent
    try:
        req_time = int(timestamp_header)
    except ValueError:
        return False

    now = int(time.time())
    if abs(now - req_time) > settings.hmac_signature_max_age_seconds:
        logger.warning("hmac_timestamp_expired", partner_id=partner_doc.get("partnerId"))
        return False

    # Fetch HMAC secret
    secret_name = partner_doc.get("hmacSecretName")
    if not secret_name:
        return False

    try:
        secret = await _get_hmac_secret(secret_name)
    except Exception as exc:
        logger.error("hmac_secret_fetch_failed", error=str(exc))
        return False

    # Build the message to sign
    body_hash = hashlib.sha256(body).hexdigest()
    method = request.method.upper()
    path = request.url.path
    message = f"{timestamp_header}\n{method}\n{path}\n{body_hash}".encode()

    expected = hmac.new(
        secret.encode(),
        message,
        hashlib.sha256,
    ).hexdigest()

    return hmac.compare_digest(expected, signature_header)


# ── Main verification function ────────────────────────────────────────────────

async def verify_api_key(request: Request, api_key: str) -> PartnerContext:
    """
    Verify X-API-Key header against partner records in Firestore.
    Raises HTTP 401 on any auth failure (generic message to prevent enumeration).
    """
    settings = get_settings()
    db = _get_db()

    unauthorized = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail={
            "error": "UNAUTHORIZED",
            "message": "Invalid API key or unauthorized request",
            "details": [],
        },
    )

    key_hash = _hash_key(api_key)

    # Query Firestore for a partner with a matching active API key
    partners_ref = db.collection(settings.firestore_partners_collection)
    query = partners_ref.where("active", "==", True)

    partner_doc_data = None
    partner_id = None

    async for doc in query.stream():
        data = doc.to_dict()
        for key_entry in data.get("apiKeys", []):
            if (
                key_entry.get("active", False)
                and key_entry.get("keyHash") == key_hash
            ):
                # Check expiry
                expires_at = key_entry.get("expiresAt")
                if expires_at:
                    import datetime
                    if isinstance(expires_at, datetime.datetime):
                        if expires_at < datetime.datetime.utcnow():
                            logger.warning("api_key_expired", partner_id=doc.id)
                            raise unauthorized

                partner_doc_data = data
                partner_id = doc.id
                break
        if partner_id:
            break

    if not partner_doc_data or not partner_id:
        logger.warning("api_key_not_found", key_prefix=api_key[:8] + "...")
        raise unauthorized

    # IP allowlist check
    client_ip = _get_client_ip(request)
    allowed_ips = partner_doc_data.get("allowedIps", [])
    ip_ok = _ip_allowed(client_ip, allowed_ips)

    if not ip_ok:
        logger.warning(
            "ip_not_allowed",
            partner_id=partner_id,
            client_ip=client_ip,
        )
        raise unauthorized

    # HMAC check (if partner requires it)
    hmac_verified = False
    if partner_doc_data.get("requireHmac", False):
        body = await request.body()
        hmac_ok = await _verify_hmac(request, partner_doc_data, body)
        if not hmac_ok:
            logger.warning("hmac_verification_failed", partner_id=partner_id)
            raise unauthorized
        hmac_verified = True

    # Log request for billing/analytics (non-blocking)
    try:
        await _log_partner_request(
            db=db,
            partner_id=partner_id,
            request=request,
            settings=settings,
        )
    except Exception as exc:
        logger.error("request_log_failed_non_fatal", error=str(exc))

    logger.info(
        "api_key_auth_success",
        partner_id=partner_id,
        ip_verified=ip_ok,
        hmac_verified=hmac_verified,
    )

    return PartnerContext(
        partner_id=partner_id,
        auth_method="api_key",
        partner_name=partner_doc_data.get("name", ""),
        ip_verified=ip_ok,
        hmac_verified=hmac_verified,
    )


async def _log_partner_request(
    db: firestore.AsyncClient,
    partner_id: str,
    request: Request,
    settings,
) -> None:
    """
    Increment partner request counter and write a request log entry.
    Used for billing and analytics.
    """
    import datetime
    now = datetime.datetime.utcnow()

    # Increment counter on partner doc
    partner_ref = db.collection(settings.firestore_partners_collection).document(partner_id)
    await partner_ref.update({
        "requestCount": firestore.Increment(1),
        "lastRequestAt": firestore.SERVER_TIMESTAMP,
    })

    # Write log entry to subcollection
    log_ref = partner_ref.collection(
        settings.firestore_request_logs_collection
    ).document()
    await log_ref.set({
        "timestamp": firestore.SERVER_TIMESTAMP,
        "method": request.method,
        "path": request.url.path,
        "ip": _get_client_ip(request),
        "userAgent": request.headers.get("User-Agent", ""),
        "date": now.strftime("%Y-%m-%d"),
    })
