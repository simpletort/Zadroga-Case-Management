"""
Upload Service — registration and status tracking for the virus-scan upload flow.

Upload lifecycle:
  1. Staff POSTs /upload/register  → Firestore record created, staging signed URL returned
  2. Staff PUTs file to GCS staging path (via signed URL)
  3. GCS Eventarc triggers virus-scanner Cloud Function
  4. Cloud Function updates scan_status → "scanning" → "clean" | "infected"
  5. Staff polls GET /upload/{fileId}/status until scan_status != "pending"/"scanning"

Firestore collections written here:
  - file_uploads/{fileId}                            — scan tracking (all uploads)
  - cases/{caseId}/documents/{fileId}  (case-scoped) — standard document metadata
"""

import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException, status
from google.cloud import firestore

from app.config import get_settings
from app.models.storage import (
    DocumentCategory,
    ProcessingStatus,
    ScanStatus,
    UploadStatusResponse,
    VerificationStatus,
    UrlAction,
)
from app.services.gcs_service import generate_signed_url
from app.utils.firestore import get_firestore_client
from app.utils.gcs_client import get_gcs_client

logger = logging.getLogger(__name__)
settings = get_settings()


def _staging_path(file_id: str, file_name: str) -> str:
    """
    All uploads land under staging/{fileId}/{fileName} so the virus-scanner
    Cloud Function can extract the fileId from the blob path.
    """
    return "{}/{}/{}".format(settings.gcs_staging_prefix, file_id, file_name)


def register_upload(
    file_name: str,
    folder_path: str,
    content_type: str,
    uploaded_by: str,
    case_id: str,
    size_bytes: Optional[int] = None,
) -> dict:
    """
    Register a pending upload:
      - Validates folder_path stays within the case directory.
      - Generates a unique fileId.
      - Creates the file_uploads/{fileId} Firestore record.
      - Creates the cases/{caseId}/documents/{fileId} skeleton record.
      - Returns a signed PUT URL pointing to the staging path.
    """
    if ".." in folder_path.split("/") or folder_path.startswith("/"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Invalid folder_path: must not escape the case directory.",
        )

    from shared.middlewares.file_validation import validate_file_extension
    validate_file_extension(file_name)

    file_id = str(uuid.uuid4())
    staging_path = _staging_path(file_id, file_name)
    final_path = "{}/{}/{}".format(case_id, folder_path, file_name) if folder_path else "{}/{}".format(case_id, file_name)
    registered_at = datetime.now(tz=timezone.utc)

    db = get_firestore_client()

    # 1. Write the scan-tracking record (top-level, allows lookup without caseId)
    db.collection("file_uploads").document(file_id).set({
        "fileId": file_id,
        "caseId": case_id,
        "fileName": file_name,
        "folderPath": folder_path,
        "mimeType": content_type,
        "sizeBytes": size_bytes,
        "uploadedBy": uploaded_by,
        "registeredAt": registered_at,
        "stagingPath": staging_path,
        "finalPath": final_path,
        "scanStatus": ScanStatus.pending.value,
        "scanCompletedAt": None,
        "scanResult": None,
        "isQuarantined": False,
        "quarantinePath": None,
    })

    # Derive category from folder_path if it matches a known DocumentCategory value
    _category_values = {c.value: c.value for c in DocumentCategory}
    derived_category = _category_values.get(folder_path.lower()) if folder_path else None

    # 2. Create the document skeleton under the case
    db.collection("cases").document(case_id).collection("documents").document(file_id).set({
        "fileName": file_name,
        "folderPath": folder_path,
        "category": derived_category,
        "gcsPath": None,            # populated after clean scan
        "mimeType": content_type,
        "sizeBytes": size_bytes,
        "uploadedBy": uploaded_by,
        "uploadedAt": registered_at,
        "processingStatus": ProcessingStatus.pending.value,
        "verificationStatus": VerificationStatus.unverified.value,
        "scanStatus": ScanStatus.pending.value,
        "extractedData": None,
        "documentAiResults": None,
        "medicalAiResults": None,
        "manualOverrides": [],
    })

    logger.info(
        "Upload registered: fileId=%s case=%s folderPath=%s staging=%s",
        file_id, case_id, folder_path, staging_path,
    )

    # 3. Generate the staging signed URL
    gcs_client = get_gcs_client()
    signed_url, expires_at, _ = generate_signed_url(
        gcs_client=gcs_client,
        blob_path=staging_path,
        action=UrlAction.write,
        content_type=content_type,
    )

    return {
        "file_id": file_id,
        "staging_path": staging_path,
        "signed_url": signed_url,
        "expires_at": expires_at,
        "bucket": settings.gcs_bucket_name,
    }


def _system_staging_path(file_id: str, file_name: str) -> str:
    """Same staging prefix as case-scoped uploads — the virus-scanner Cloud
    Function only keys off staging/{fileId}/{fileName}, it doesn't care
    whether the upload is case-scoped or system-scoped."""
    return "{}/{}/{}".format(settings.gcs_staging_prefix, file_id, file_name)


def register_system_upload(
    file_name: str,
    content_type: str,
    uploaded_by: str,
    context: str,
    size_bytes: Optional[int] = None,
) -> dict:
    """
    Register a case-less pending upload (e.g. a bulk-import spreadsheet):
      - Generates a unique fileId.
      - Creates the file_uploads/{fileId} Firestore record with caseId=None.
      - Does NOT create a cases/{caseId}/documents/{fileId} record — there is
        no case yet.
      - Final GCS path (post clean-scan) is system-uploads/{context}/{fileId}/{fileName},
        not case-scoped. Subject to a short (2-day) lifecycle deletion rule.
      - Returns a signed PUT URL pointing to the same staging path scheme as
        case-scoped uploads, so the existing virus-scanner Cloud Function
        picks it up unmodified.
    """
    if ".." in context.split("/") or context.startswith("/") or not context:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Invalid context: must be a non-empty path segment that does not escape.",
        )

    from shared.middlewares.file_validation import validate_file_extension
    validate_file_extension(file_name)

    file_id = str(uuid.uuid4())
    staging_path = _system_staging_path(file_id, file_name)
    final_path = "system-uploads/{}/{}/{}".format(context, file_id, file_name)
    registered_at = datetime.now(tz=timezone.utc)

    db = get_firestore_client()

    db.collection("file_uploads").document(file_id).set({
        "fileId": file_id,
        "caseId": None,
        "context": context,
        "fileName": file_name,
        "folderPath": "",
        "mimeType": content_type,
        "sizeBytes": size_bytes,
        "uploadedBy": uploaded_by,
        "registeredAt": registered_at,
        "stagingPath": staging_path,
        "finalPath": final_path,
        "scanStatus": ScanStatus.pending.value,
        "scanCompletedAt": None,
        "scanResult": None,
        "isQuarantined": False,
        "quarantinePath": None,
    })

    logger.info(
        "System upload registered: fileId=%s context=%s staging=%s",
        file_id, context, staging_path,
    )

    gcs_client = get_gcs_client()
    signed_url, expires_at, _ = generate_signed_url(
        gcs_client=gcs_client,
        blob_path=staging_path,
        action=UrlAction.write,
        content_type=content_type,
    )

    return {
        "file_id": file_id,
        "staging_path": staging_path,
        "signed_url": signed_url,
        "expires_at": expires_at,
        "bucket": settings.gcs_bucket_name,
    }


def get_system_file_read_url(file_id: str) -> dict:
    """
    Return a signed READ url for a system upload's finalPath. Requires the
    virus scan to have completed clean — the finalPath doesn't exist (and
    the object is untrusted) before that.
    """
    db = get_firestore_client()
    snap = db.collection("file_uploads").document(file_id).get()

    if not snap.exists:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Upload '{}' not found.".format(file_id),
        )

    data = snap.to_dict()
    scan_status = data.get("scanStatus", ScanStatus.pending.value)
    if scan_status != ScanStatus.clean.value:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="File '{}' is not ready for read — scanStatus is '{}'.".format(
                file_id, scan_status,
            ),
        )

    final_path = data.get("finalPath")
    gcs_client = get_gcs_client()
    signed_url, expires_at, _ = generate_signed_url(
        gcs_client=gcs_client,
        blob_path=final_path,
        action=UrlAction.read,
    )

    return {
        "signed_url": signed_url,
        "blob_path": final_path,
        "bucket": settings.gcs_bucket_name,
        "expires_at": expires_at,
    }


def get_upload_status(file_id: str) -> UploadStatusResponse:
    """Fetch the current scan status from file_uploads/{fileId}."""
    db = get_firestore_client()
    snap = db.collection("file_uploads").document(file_id).get()

    if not snap.exists:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Upload '{}' not found.".format(file_id),
        )

    data = snap.to_dict()
    return UploadStatusResponse(
        file_id=file_id,
        case_id=data.get("caseId") or "",
        file_name=data.get("fileName", ""),
        folder_path=data.get("folderPath", ""),
        scan_status=ScanStatus(data.get("scanStatus", ScanStatus.pending.value)),
        staging_path=data.get("stagingPath", ""),
        final_path=data.get("finalPath") if data.get("scanStatus") == ScanStatus.clean.value else None,
        quarantine_path=data.get("quarantinePath"),
        is_quarantined=data.get("isQuarantined", False),
        scan_completed_at=data.get("scanCompletedAt"),
        registered_at=data["registeredAt"],
    )
