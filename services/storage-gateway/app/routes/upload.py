"""
Upload routes — virus-scan upload flow.

POST /api/v1/storage/upload/register
    Register a pending upload and receive a staging signed URL.
    The caller must PUT the file bytes directly to the signed URL.
    After the upload, the virus-scanner Cloud Function processes the file
    automatically and updates the scan status in Firestore.

GET /api/v1/storage/upload/{fileId}/status
    Poll the scan result.  Returns scan_status of "clean" or "infected"
    once the Cloud Function completes (typically within 10–30 s).
"""

import logging

from fastapi import APIRouter, Request

from app.models.storage import (
    UploadRegistrationRequest,
    UploadRegistrationResponse,
    UploadStatusResponse,
)
from app.services.upload_service import get_upload_status, register_upload
from app.utils.audit import AuditAction, log_audit_event

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/storage/upload", tags=["Upload"])


@router.post(
    "/register",
    response_model=UploadRegistrationResponse,
    status_code=201,
    summary="Register a file upload and receive a staging signed URL",
)
def register_file_upload(
    request: Request,
    body: UploadRegistrationRequest,
):
    """
    Creates a pending upload record in Firestore and returns a pre-signed
    PUT URL pointing to GCS staging.  The caller uploads the file directly
    to GCS (no bytes pass through this service).

    After upload, the virus-scanner Cloud Function is triggered automatically
    by the GCS object-finalise event.
    """
    user = getattr(request.state, "user", {})
    uploaded_by = user.get("uid", "unknown")

    result = register_upload(
        file_name=body.file_name,
        category=body.category,
        content_type=body.content_type,
        uploaded_by=uploaded_by,
        case_id=body.case_id,
        size_bytes=body.size_bytes,
    )

    log_audit_event(
        action=AuditAction.upload_register,
        request=request,
        document_id=result["file_id"],
        case_id=body.case_id,
        resource=result["staging_path"],
        metadata={
            "category": body.category.value,
            "content_type": body.content_type,
            "size_bytes": body.size_bytes,
        },
    )

    return UploadRegistrationResponse(**result)


@router.get(
    "/{file_id}/status",
    response_model=UploadStatusResponse,
    summary="Poll the virus-scan status of a registered upload",
)
def get_file_upload_status(
    file_id: str,
):
    """
    Returns the current scan_status for a given fileId.

    Scan status progression:
      pending   → file registered, not yet uploaded to GCS
      scanning  → Cloud Function has picked up the file
      clean     → passed ClamAV scan; final_path is populated
      infected  → malware detected; file quarantined; staff notified
      error     → scan failed; engineering team alerted via Cloud Logging
    """
    return get_upload_status(file_id)
