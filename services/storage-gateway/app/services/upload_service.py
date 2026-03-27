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
)
from app.services.gcs_service import build_blob_path, generate_signed_url
from app.models.storage import UrlAction
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
    category: DocumentCategory,
    content_type: str,
    uploaded_by: str,
    case_id: Optional[str] = None,
    size_bytes: Optional[int] = None,
) -> dict:
    """
    Register a pending upload:
      - Validates that case_id is present for case-scoped categories.
      - Generates a unique fileId.
      - Creates the file_uploads/{fileId} Firestore record.
      - Creates the cases/{caseId}/documents/{fileId} skeleton record (case-scoped only).
      - Returns a signed PUT URL pointing to the staging path.
    """
    # Validate case_id requirement
    case_scoped_categories = {
        DocumentCategory.medical_records,
        DocumentCategory.proof_of_presence,
        DocumentCategory.id_documents,
        DocumentCategory.legal_forms,
        DocumentCategory.vcf_documents,
        DocumentCategory.settlement_docs,
    }
    if category in case_scoped_categories and not case_id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="case_id is required for category '{}'.".format(category.value),
        )

    file_id = str(uuid.uuid4())
    staging_path = _staging_path(file_id, file_name)
    registered_at = datetime.now(tz=timezone.utc)

    # Build the final (permanent) path — used after a clean scan
    try:
        final_path = build_blob_path(category, file_name, case_id)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(e),
        )

    db = get_firestore_client()

    # 1. Write the scan-tracking record (top-level, allows lookup without caseId)
    db.collection("file_uploads").document(file_id).set({
        "fileId": file_id,
        "caseId": case_id,
        "fileName": file_name,
        "category": category.value,
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

    # 2. Create the document skeleton under the case (if case-scoped)
    if case_id:
        db.collection("cases").document(case_id).collection("documents").document(file_id).set({
            "fileName": file_name,
            "category": category.value,
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
        "Upload registered: fileId=%s case=%s category=%s staging=%s",
        file_id, case_id, category.value, staging_path,
    )

    # 3. Generate the staging signed URL
    gcs_client = get_gcs_client()
    signed_url, expires_at = generate_signed_url(
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
        case_id=data.get("caseId"),
        file_name=data.get("fileName", ""),
        category=DocumentCategory(data.get("category", "client_uploads")),
        scan_status=ScanStatus(data.get("scanStatus", ScanStatus.pending.value)),
        staging_path=data.get("stagingPath", ""),
        final_path=data.get("finalPath") if data.get("scanStatus") == ScanStatus.clean.value else None,
        quarantine_path=data.get("quarantinePath"),
        is_quarantined=data.get("isQuarantined", False),
        scan_completed_at=data.get("scanCompletedAt"),
        registered_at=data["registeredAt"],
    )
