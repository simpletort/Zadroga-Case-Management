"""
api/services/storage_gateway_client.py — OIDC HTTP client for storage-gateway's
case-less "system upload" flow (used to virus-scan bulk-import spreadsheets
before a case exists).

Mirrors the OIDC token pattern already used in
services/settlement-financial/services/storage_service.py: on Cloud Run the
identity token comes from the metadata server; locally it falls back to ADC
via google.oauth2.id_token.fetch_id_token(). Satisfies the repo's
"inter-service calls always use OIDC" rule (AI_CONTEXT.md).

Unlike settlement-financial's client, this one does NOT poll-loop inside a
single call — bulk-import's scan wait is driven by a Cloud Task retry loop
(services/bulk_import_service.py:handle_scan_check), not a blocking request,
so each method here is a single HTTP round trip.
"""
from __future__ import annotations

import urllib.request
from typing import Optional

import httpx

from config import Settings
from logging_config import get_logger

logger = get_logger(__name__)

_DEFAULT_TIMEOUT = 15.0


def _get_id_token(audience: str) -> str:
    """
    Fetch a Google-signed OIDC identity token.
    On Cloud Run: reads from the GCE metadata server (no credentials needed).
    Locally:     falls back to google.oauth2.id_token.fetch_id_token() via ADC.
    """
    try:
        url = (
            "http://metadata.google.internal/computeMetadata/v1/instance/"
            f"service-accounts/default/identity?audience={audience}"
        )
        req = urllib.request.Request(url, headers={"Metadata-Flavor": "Google"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.read().decode("utf-8")
    except Exception:
        from google.auth.transport.requests import Request as _GReq
        from google.oauth2.id_token import fetch_id_token as _fetch
        return _fetch(_GReq(), audience)


def _auth_headers(gateway_url: str) -> dict[str, str]:
    token = _get_id_token(gateway_url.rstrip("/"))
    return {"Authorization": f"Bearer {token}"}


async def register_system_upload(
    settings:     Settings,
    file_name:    str,
    content_type: str,
    size_bytes:   Optional[int],
    context:      str = "bulk_lead_import",
) -> dict:
    """
    Register a case-less upload with storage-gateway.
    Returns {"file_id", "staging_path", "signed_url", "expires_at", "bucket"}.
    """
    gw      = settings.storage_gateway_url.rstrip("/")
    headers = _auth_headers(gw)

    async with httpx.AsyncClient(timeout=_DEFAULT_TIMEOUT) as client:
        resp = await client.post(
            f"{gw}/api/v1/storage/system-upload/register",
            json={
                "file_name":    file_name,
                "content_type": content_type,
                "size_bytes":   size_bytes,
                "context":      context,
            },
            headers=headers,
        )
        resp.raise_for_status()
        return resp.json()


async def put_file_bytes(signed_url: str, data: bytes, content_type: str) -> None:
    """PUT file bytes directly to GCS via the signed URL — no auth header needed."""
    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.put(
            signed_url, content=data, headers={"Content-Type": content_type},
        )
        resp.raise_for_status()


async def get_upload_status(settings: Settings, file_id: str) -> dict:
    """
    Poll scan status. Returns storage-gateway's UploadStatusResponse dict,
    notably {"scan_status": "pending"|"scanning"|"clean"|"infected"|"error", ...}.
    """
    gw      = settings.storage_gateway_url.rstrip("/")
    headers = _auth_headers(gw)

    async with httpx.AsyncClient(timeout=_DEFAULT_TIMEOUT) as client:
        resp = await client.get(
            f"{gw}/api/v1/storage/upload/{file_id}/status",
            headers=headers,
        )
        resp.raise_for_status()
        return resp.json()


async def get_system_upload_read_url(settings: Settings, file_id: str) -> dict:
    """
    Fetch a signed read URL for a clean-scanned system upload.
    Returns {"signed_url", "blob_path", "bucket", "expires_at"}.
    Raises httpx.HTTPStatusError(409) if the scan hasn't cleared yet.
    """
    gw      = settings.storage_gateway_url.rstrip("/")
    headers = _auth_headers(gw)

    async with httpx.AsyncClient(timeout=_DEFAULT_TIMEOUT) as client:
        resp = await client.get(
            f"{gw}/api/v1/storage/system-upload/{file_id}/read-url",
            headers=headers,
        )
        resp.raise_for_status()
        return resp.json()


async def fetch_bytes(signed_url: str) -> bytes:
    """Download file bytes from GCS via a signed read URL — no auth header needed."""
    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.get(signed_url)
        resp.raise_for_status()
        return resp.content
