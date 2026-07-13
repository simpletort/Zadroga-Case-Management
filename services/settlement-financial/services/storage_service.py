"""
services/storage_service.py
============================
Case file operations delegated to the Storage Gateway service.

All file I/O goes through the Storage Gateway rather than talking to GCS directly.
This ensures virus scanning, unified audit logging, and consistent Firestore
metadata across all services.

Upload flow
-----------
  1. POST /api/v1/storage/upload/register  → staging signed URL
  2. PUT  <signed_url>                     → bytes land in GCS staging
  3. GET  /api/v1/storage/upload/{id}/status → poll until scan_status="clean"

List / Signed URL / Stream
--------------------------
  GET /api/v1/storage/cases/{caseId}/documents?category=settlement_docs
  GET /api/v1/storage/{fileId}/metadata?case_id={caseId}
  GET /api/v1/storage/signed-url?category=settlement_docs&file_name=...&action=read&case_id=...
"""
from __future__ import annotations

import asyncio
import os
import time
import urllib.request
from datetime import datetime, timezone
from typing import Optional

import httpx
from fastapi import UploadFile

from config import Settings, get_settings
from logging_config import get_logger
from models.storage import (
    CaseFile,
    CaseFileType,
    FileListResponse,
    FileUploadResponse,
    SignedUrlResponse,
)

logger = get_logger(__name__)

# All settlement-service files belong to the settlement_docs category in the gateway
_GATEWAY_CATEGORY = "settlement_docs"

_SCAN_POLL_INTERVAL_S = 3
_SCAN_POLL_TIMEOUT_S  = 60

ALLOWED_CONTENT_TYPES = {
    "application/pdf",
    "image/png",
    "image/jpeg",
    "image/jpg",
    "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.ms-excel",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "text/plain",
    "text/csv",
}

MAX_FILE_SIZE_BYTES = 50 * 1024 * 1024  # 50 MB


# ── OIDC token (service-to-service auth) ─────────────────────────────────────

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
        # Local development fallback — requires `gcloud auth application-default login`
        from google.auth.transport.requests import Request as _GReq
        from google.oauth2.id_token import fetch_id_token as _fetch
        return _fetch(_GReq(), audience)


def _auth_headers(gateway_url: str) -> dict[str, str]:
    token = _get_id_token(gateway_url.rstrip("/"))
    return {"Authorization": f"Bearer {token}"}


# ── Public API ────────────────────────────────────────────────────────────────

async def upload_case_file(
    db,                              # kept for API compatibility, unused
    case_id:        str,
    file:           UploadFile,
    file_type:      CaseFileType,
    description:    Optional[str],
    uploaded_by:    str,
    settings:       Settings,
    linked_to_type: Optional[str] = None,
    linked_to_id:   Optional[str] = None,
) -> FileUploadResponse:
    """
    Upload a file through the Storage Gateway.

    Steps: register → PUT to GCS staging → poll virus scan → return metadata.
    Raises ValueError for invalid content type, oversized files, or infected files.
    Raises TimeoutError if the virus scan does not complete within 60 s.
    """
    content_type = file.content_type or "application/octet-stream"
    if content_type not in ALLOWED_CONTENT_TYPES:
        raise ValueError(
            f"File type '{content_type}' is not allowed. "
            f"Accepted: {', '.join(sorted(ALLOWED_CONTENT_TYPES))}"
        )

    data = await file.read()
    if len(data) > MAX_FILE_SIZE_BYTES:
        raise ValueError(f"File size {len(data):,} bytes exceeds the 50 MB limit.")

    gw        = settings.storage_gateway_url.rstrip("/")
    safe_name = os.path.basename(file.filename or "upload")
    headers   = _auth_headers(gw)

    async with httpx.AsyncClient(timeout=30) as client:
        # 1. Register — gateway creates Firestore record + returns staging signed URL
        reg = await client.post(
            f"{gw}/api/v1/storage/upload/register",
            json={
                "file_name":    safe_name,
                "category":     _GATEWAY_CATEGORY,
                "content_type": content_type,
                "case_id":      case_id,
                "size_bytes":   len(data),
            },
            headers=headers,
        )
        reg.raise_for_status()
        reg_data   = reg.json()
        file_id    = reg_data["file_id"]
        signed_url = reg_data["signed_url"]

        logger.info("storage_upload_registered", file_id=file_id, case_id=case_id)

        # 2. PUT bytes directly to GCS staging (signed URL — no auth header needed)
        put = await client.put(
            signed_url,
            content=data,
            headers={"Content-Type": content_type},
        )
        put.raise_for_status()
        logger.info("storage_upload_bytes_sent", file_id=file_id, size=len(data))

    # 3. Poll until virus scan completes
    deadline    = time.monotonic() + _SCAN_POLL_TIMEOUT_S
    scan_status = "pending"
    gcs_path    = ""

    async with httpx.AsyncClient(timeout=15) as client:
        while time.monotonic() < deadline:
            st = await client.get(
                f"{gw}/api/v1/storage/upload/{file_id}/status",
                headers=headers,
            )
            st.raise_for_status()
            st_data     = st.json()
            scan_status = st_data.get("scan_status", "pending")

            if scan_status == "clean":
                gcs_path = st_data.get("final_path") or ""
                logger.info("storage_scan_clean", file_id=file_id)
                break
            elif scan_status == "infected":
                raise ValueError("File rejected: malware detected during virus scan.")
            elif scan_status == "error":
                raise ValueError("Virus scan failed unexpectedly. Please try again.")

            await asyncio.sleep(_SCAN_POLL_INTERVAL_S)

    if scan_status != "clean":
        raise TimeoutError(
            f"Virus scan did not complete within {_SCAN_POLL_TIMEOUT_S}s. "
            f"Poll GET /api/v1/storage/upload/{file_id}/status for the result."
        )

    # 4. Get a signed download URL for the clean file
    download_url = await _signed_read_url(gw, headers, case_id, safe_name)

    return FileUploadResponse(
        file_id           = file_id,
        case_id           = case_id,
        original_filename = safe_name,
        content_type      = content_type,
        size_bytes        = len(data),
        gcs_path          = gcs_path,
        file_type         = file_type,
        description       = description,
        uploaded_by       = uploaded_by,
        uploaded_at       = datetime.now(timezone.utc),
        download_url      = download_url,
    )


async def list_case_files(db, case_id: str) -> FileListResponse:
    """Return all settlement_docs for a case from the Storage Gateway."""
    settings = get_settings()
    gw       = settings.storage_gateway_url.rstrip("/")
    headers  = _auth_headers(gw)

    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(
            f"{gw}/api/v1/storage/cases/{case_id}/documents",
            params={"category": _GATEWAY_CATEGORY, "page_size": 100},
            headers=headers,
        )
        resp.raise_for_status()
        body = resp.json()

    files = [_to_case_file(doc, case_id) for doc in body.get("documents", [])]
    return FileListResponse(case_id=case_id, total=len(files), files=files)


async def delete_case_file(db, case_id: str, file_id: str, settings: Settings) -> None:
    """
    The Storage Gateway does not expose a delete endpoint — file retention is
    managed via bucket lifecycle policies.  This operation is intentionally
    unsupported to preserve the audit trail.
    """
    raise ValueError(
        "Individual file deletion is not supported. "
        "Contact an administrator to manage file retention via lifecycle policies."
    )


async def stream_case_file(
    db, case_id: str, file_id: str, settings: Settings
) -> tuple[bytes, str, str]:
    """
    Download file bytes via the Storage Gateway.
    Returns (bytes, content_type, original_filename).
    """
    gw      = settings.storage_gateway_url.rstrip("/")
    headers = _auth_headers(gw)

    async with httpx.AsyncClient(timeout=15) as client:
        # Get file metadata to retrieve file_name and mime_type
        meta = await client.get(
            f"{gw}/api/v1/storage/{file_id}/metadata",
            params={"case_id": case_id},
            headers=headers,
        )
        if meta.status_code == 404:
            raise ValueError(f"File '{file_id}' not found for case '{case_id}'.")
        meta.raise_for_status()
        meta_data    = meta.json()
        file_name    = meta_data.get("file_name", "file")
        content_type = meta_data.get("mime_type") or "application/octet-stream"

        # Get a signed read URL from the gateway
        signed = await client.get(
            f"{gw}/api/v1/storage/signed-url",
            params={"category": _GATEWAY_CATEGORY, "file_name": file_name,
                    "action": "read", "case_id": case_id},
            headers=headers,
        )
        if signed.status_code == 404:
            raise ValueError(f"File '{file_id}' not found in Cloud Storage.")
        signed.raise_for_status()
        signed_url = signed.json()["signed_url"]

    # Fetch bytes from GCS via the signed URL (no auth required)
    async with httpx.AsyncClient(timeout=60) as gcs:
        file_resp = await gcs.get(signed_url)
        file_resp.raise_for_status()

    return file_resp.content, content_type, file_name


async def get_signed_url(
    db, case_id: str, file_id: str, settings: Settings
) -> SignedUrlResponse:
    """Generate a 60-minute signed read URL via the Storage Gateway."""
    gw      = settings.storage_gateway_url.rstrip("/")
    headers = _auth_headers(gw)

    async with httpx.AsyncClient(timeout=15) as client:
        # Resolve file_name from metadata
        meta = await client.get(
            f"{gw}/api/v1/storage/{file_id}/metadata",
            params={"case_id": case_id},
            headers=headers,
        )
        if meta.status_code == 404:
            raise ValueError(f"File '{file_id}' not found for case '{case_id}'.")
        meta.raise_for_status()
        meta_data = meta.json()
        file_name = meta_data.get("file_name", "file")
        gcs_path  = meta_data.get("gcs_path") or ""

        # Get signed URL
        signed = await client.get(
            f"{gw}/api/v1/storage/signed-url",
            params={"category": _GATEWAY_CATEGORY, "file_name": file_name,
                    "action": "read", "case_id": case_id},
            headers=headers,
        )
        if signed.status_code == 404:
            raise ValueError(f"File '{file_id}' not found in Cloud Storage.")
        signed.raise_for_status()
        signed_url = signed.json()["signed_url"]

    return SignedUrlResponse(
        file_id    = file_id,
        gcs_path   = gcs_path,
        signed_url = signed_url,
    )


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _signed_read_url(gw: str, headers: dict, case_id: str, file_name: str) -> str:
    """Fetch a signed read URL from the gateway. Returns '' on failure."""
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"{gw}/api/v1/storage/signed-url",
                params={"category": _GATEWAY_CATEGORY, "file_name": file_name,
                        "action": "read", "case_id": case_id},
                headers=headers,
            )
            resp.raise_for_status()
            return resp.json().get("signed_url", "")
    except Exception as exc:
        logger.warning("signed_url_fetch_failed", error=str(exc))
        return ""


def _to_case_file(doc: dict, case_id: str) -> CaseFile:
    """Translate a storage-gateway FileMetadataResponse dict to a CaseFile."""
    uploaded_at = doc.get("uploaded_at")
    if isinstance(uploaded_at, str):
        uploaded_at = datetime.fromisoformat(uploaded_at.replace("Z", "+00:00"))
    if not isinstance(uploaded_at, datetime):
        uploaded_at = datetime.now(timezone.utc)

    return CaseFile(
        file_id           = doc["file_id"],
        case_id           = case_id,
        original_filename = doc.get("file_name", ""),
        content_type      = doc.get("mime_type") or "application/octet-stream",
        size_bytes        = doc.get("size_bytes") or 0,
        gcs_path          = doc.get("gcs_path") or "",
        file_type         = CaseFileType.settlement_doc,
        description       = None,
        linked_to_type    = None,
        linked_to_id      = None,
        uploaded_by       = doc.get("uploaded_by") or "",
        uploaded_at       = uploaded_at,
    )
