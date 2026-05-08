"""
services/storage_service.py
============================
GCS storage gateway — upload, download, delete, and sign URLs for case files.

All blocking GCS calls are run in a thread executor so they never block
the async event loop.

Public API
----------
    upload_case_file(db, case_id, file, file_type, description, uploaded_by, settings)
        -> FileUploadResponse

    list_case_files(db, case_id) -> FileListResponse

    delete_case_file(db, case_id, file_id, settings) -> None

    stream_case_file(file_id, gcs_path, settings) -> bytes

    get_signed_url(file_id, gcs_path, settings) -> SignedUrlResponse
"""
from __future__ import annotations

import asyncio
import os
import uuid
from datetime import datetime, timedelta, timezone
from functools import partial
from typing import Optional

from fastapi import UploadFile
from google.cloud import storage as gcs

from config import Settings
from models.storage import (
    CaseFile,
    CaseFileType,
    FileListResponse,
    FileUploadResponse,
    SignedUrlResponse,
)

# ── Allowed MIME types ────────────────────────────────────────────────────────

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


# ── Firestore reference ───────────────────────────────────────────────────────

def _files_ref(db, case_id: str):
    return (
        db.collection("cases")
          .document(case_id)
          .collection("settlement")
          .document("files")
    )


# ── GCS helpers (blocking — run in executor) ──────────────────────────────────

def _gcs_client(settings: Settings):
    """Return an authenticated GCS client."""
    sa_key = settings.firebase_service_account_key_path
    if sa_key and os.path.isfile(sa_key):
        from google.oauth2 import service_account as _sa
        creds = _sa.Credentials.from_service_account_file(
            sa_key,
            scopes=["https://www.googleapis.com/auth/cloud-platform"],
        )
        return gcs.Client(credentials=creds), creds
    return gcs.Client(), None


def _upload_bytes_to_gcs(
    data: bytes,
    bucket_name: str,
    gcs_object: str,
    content_type: str,
    settings: Settings,
) -> str:
    """Upload raw bytes to GCS. Returns signed URL or gs:// fallback."""
    client, creds = _gcs_client(settings)
    bucket = client.bucket(bucket_name)
    blob   = bucket.blob(gcs_object)
    blob.upload_from_string(data, content_type=content_type)

    if creds:
        return blob.generate_signed_url(
            expiration=timedelta(minutes=60),
            method="GET",
            version="v4",
            credentials=creds,
        )
    return f"gs://{bucket_name}/{gcs_object}"


def _delete_from_gcs(bucket_name: str, gcs_object: str, settings: Settings) -> None:
    """Delete a blob from GCS. Silently skips if not found."""
    client, _ = _gcs_client(settings)
    bucket = client.bucket(bucket_name)
    blob   = bucket.blob(gcs_object)
    if blob.exists():
        blob.delete()


def _download_from_gcs(bucket_name: str, gcs_object: str, settings: Settings) -> bytes:
    """Download a blob from GCS as bytes."""
    client, _ = _gcs_client(settings)
    bucket = client.bucket(bucket_name)
    blob   = bucket.blob(gcs_object)
    if not blob.exists():
        return b""
    return blob.download_as_bytes()


def _make_signed_url(bucket_name: str, gcs_object: str, settings: Settings) -> str:
    """Generate a v4 signed URL (60-minute TTL). Falls back to gs:// URI."""
    client, creds = _gcs_client(settings)
    if not creds:
        return f"gs://{bucket_name}/{gcs_object}"
    bucket = client.bucket(bucket_name)
    blob   = bucket.blob(gcs_object)
    return blob.generate_signed_url(
        expiration=timedelta(minutes=60),
        method="GET",
        version="v4",
        credentials=creds,
    )


# ── Firestore doc converter ───────────────────────────────────────────────────

def _item_to_case_file(item: dict) -> CaseFile:
    def _dt(val):
        if val is None:
            return None
        if hasattr(val, "timestamp"):
            return datetime.fromtimestamp(val.timestamp(), tz=timezone.utc)
        if isinstance(val, datetime):
            return val
        return None

    return CaseFile(
        file_id           = item["fileId"],
        case_id           = item["caseId"],
        original_filename = item["originalFilename"],
        content_type      = item["contentType"],
        size_bytes        = item["sizeBytes"],
        gcs_path          = item["gcsPath"],
        file_type         = CaseFileType(item.get("fileType", "other")),
        description       = item.get("description"),
        linked_to_type    = item.get("linkedToType"),
        linked_to_id      = item.get("linkedToId"),
        uploaded_by       = item.get("uploadedBy", ""),
        uploaded_at       = _dt(item.get("uploadedAt")) or datetime.now(tz=timezone.utc),
        updated_at        = _dt(item.get("updatedAt")),
    )


# ── Public service functions ──────────────────────────────────────────────────

async def upload_case_file(
    db,
    case_id:     str,
    file:        UploadFile,
    file_type:   CaseFileType,
    description: Optional[str],
    uploaded_by: str,
    settings:    Settings,
    linked_to_type: Optional[str] = None,
    linked_to_id:   Optional[str] = None,
) -> FileUploadResponse:
    """
    Read uploaded bytes, validate, push to GCS, save metadata to Firestore.
    Returns FileUploadResponse with a signed download URL.
    """
    # Validate content type
    content_type = file.content_type or "application/octet-stream"
    if content_type not in ALLOWED_CONTENT_TYPES:
        raise ValueError(
            f"File type '{content_type}' is not allowed. "
            f"Accepted: {', '.join(sorted(ALLOWED_CONTENT_TYPES))}"
        )

    # Read bytes + size check
    data = await file.read()
    if len(data) > MAX_FILE_SIZE_BYTES:
        raise ValueError(
            f"File size {len(data):,} bytes exceeds the 50 MB limit."
        )

    file_id   = str(uuid.uuid4())
    now       = datetime.now(tz=timezone.utc)
    safe_name = os.path.basename(file.filename or "upload")
    gcs_object = f"cases/{case_id}/files/{file_type.value}/{file_id}_{safe_name}"
    gcs_path   = f"gs://{settings.gcs_bucket}/{gcs_object}"

    # Upload to GCS in thread executor
    loop = asyncio.get_event_loop()
    download_url = await loop.run_in_executor(
        None,
        partial(
            _upload_bytes_to_gcs,
            data,
            settings.gcs_bucket,
            gcs_object,
            content_type,
            settings,
        ),
    )

    # Persist metadata in Firestore
    from google.cloud import firestore as _fs
    new_item = {
        "fileId":           file_id,
        "caseId":           case_id,
        "originalFilename": safe_name,
        "contentType":      content_type,
        "sizeBytes":        len(data),
        "gcsPath":          gcs_path,
        "fileType":         file_type.value,
        "description":      description,
        "linkedToType":     linked_to_type,
        "linkedToId":       linked_to_id,
        "uploadedBy":       uploaded_by,
        "uploadedAt":       now,
        "updatedAt":        None,
    }
    await _files_ref(db, case_id).set(
        {"items": _fs.ArrayUnion([new_item])}, merge=True
    )

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
        uploaded_at       = now,
        download_url      = download_url,
    )


async def list_case_files(db, case_id: str) -> FileListResponse:
    """Return all file metadata records for a case."""
    snap  = await _files_ref(db, case_id).get()
    items = (snap.to_dict() or {}).get("items", []) if snap.exists else []
    files = [_item_to_case_file(i) for i in items]
    return FileListResponse(case_id=case_id, total=len(files), files=files)


async def delete_case_file(
    db, case_id: str, file_id: str, settings: Settings
) -> None:
    """
    Remove a file from GCS and its metadata from Firestore.
    Raises ValueError if not found.
    """
    doc_ref = _files_ref(db, case_id)
    snap    = await doc_ref.get()
    items   = (snap.to_dict() or {}).get("items", []) if snap.exists else []

    target    = next((i for i in items if i["fileId"] == file_id), None)
    if not target:
        raise ValueError(f"File '{file_id}' not found for case '{case_id}'.")

    # Extract GCS object path from gs:// URI
    gcs_path   = target["gcsPath"]                     # gs://bucket/path
    gcs_object = gcs_path.split(f"gs://{settings.gcs_bucket}/", 1)[-1]

    # Delete from GCS in executor
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(
        None,
        partial(_delete_from_gcs, settings.gcs_bucket, gcs_object, settings),
    )

    # Remove metadata from Firestore
    new_items = [i for i in items if i["fileId"] != file_id]
    await doc_ref.set({"items": new_items})


async def stream_case_file(
    db, case_id: str, file_id: str, settings: Settings
) -> tuple[bytes, str, str]:
    """
    Download file bytes from GCS.
    Returns (bytes, content_type, original_filename).
    Raises ValueError if not found.
    """
    snap  = await _files_ref(db, case_id).get()
    items = (snap.to_dict() or {}).get("items", []) if snap.exists else []

    target = next((i for i in items if i["fileId"] == file_id), None)
    if not target:
        raise ValueError(f"File '{file_id}' not found for case '{case_id}'.")

    gcs_path   = target["gcsPath"]
    gcs_object = gcs_path.split(f"gs://{settings.gcs_bucket}/", 1)[-1]

    loop = asyncio.get_event_loop()
    data = await loop.run_in_executor(
        None,
        partial(_download_from_gcs, settings.gcs_bucket, gcs_object, settings),
    )

    if not data:
        raise ValueError(f"File '{file_id}' not found in Cloud Storage.")

    return data, target.get("contentType", "application/octet-stream"), target["originalFilename"]


async def get_signed_url(
    db, case_id: str, file_id: str, settings: Settings
) -> SignedUrlResponse:
    """Generate a 60-minute signed URL for a file."""
    snap  = await _files_ref(db, case_id).get()
    items = (snap.to_dict() or {}).get("items", []) if snap.exists else []

    target = next((i for i in items if i["fileId"] == file_id), None)
    if not target:
        raise ValueError(f"File '{file_id}' not found for case '{case_id}'.")

    gcs_path   = target["gcsPath"]
    gcs_object = gcs_path.split(f"gs://{settings.gcs_bucket}/", 1)[-1]

    loop       = asyncio.get_event_loop()
    signed_url = await loop.run_in_executor(
        None,
        partial(_make_signed_url, settings.gcs_bucket, gcs_object, settings),
    )

    return SignedUrlResponse(
        file_id    = file_id,
        gcs_path   = gcs_path,
        signed_url = signed_url,
    )
