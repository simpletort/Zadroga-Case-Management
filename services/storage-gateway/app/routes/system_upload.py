"""
System upload routes — virus-scan upload flow for case-less files.

POST /api/v1/storage/system-upload/register
    Register a pending upload that isn't tied to any case (e.g. a bulk-import
    spreadsheet) and receive a staging signed URL. Same staging/scan pipeline
    as /upload/register — the virus-scanner Cloud Function doesn't care
    whether the upload is case-scoped or system-scoped.

GET /api/v1/storage/upload/{fileId}/status
    Reused as-is for polling — it already tolerates a missing/None caseId.

GET /api/v1/storage/system-upload/{fileId}/read-url
    Once scanStatus is "clean", returns a signed read URL for the file's
    permanent (system-uploads/...) path so the calling service can fetch
    its bytes without ever touching GCS credentials directly.
"""

import logging

from fastapi import APIRouter, Request

from app.models.storage import (
    SystemFileReadUrlResponse,
    SystemUploadRegistrationRequest,
    UploadRegistrationResponse,
)
from app.services.upload_service import get_system_file_read_url, register_system_upload
from app.utils.audit import AuditAction, log_audit_event

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/storage/system-upload", tags=["Upload"])


@router.post(
    "/register",
    response_model=UploadRegistrationResponse,
    status_code=201,
    summary="Register a case-less file upload and receive a staging signed URL",
)
def register_system_file_upload(
    request: Request,
    body: SystemUploadRegistrationRequest,
):
    """
    Creates a pending upload record in Firestore (caseId=None) and returns a
    pre-signed PUT URL pointing to GCS staging. The caller uploads the file
    directly to GCS — no bytes pass through this service.

    After upload, the virus-scanner Cloud Function is triggered automatically
    by the GCS object-finalise event, exactly as with case-scoped uploads.
    """
    user = getattr(request.state, "user", {})
    uploaded_by = user.get("uid", "unknown")

    result = register_system_upload(
        file_name=body.file_name,
        content_type=body.content_type,
        uploaded_by=uploaded_by,
        context=body.context,
        size_bytes=body.size_bytes,
    )

    log_audit_event(
        action=AuditAction.system_upload_register,
        request=request,
        document_id=result["file_id"],
        resource=result["staging_path"],
        metadata={
            "context": body.context,
            "content_type": body.content_type,
            "size_bytes": body.size_bytes,
        },
    )

    return UploadRegistrationResponse(**result)


@router.get(
    "/{file_id}/read-url",
    response_model=SystemFileReadUrlResponse,
    summary="Get a signed read URL for a clean-scanned system upload",
)
def get_system_file_read_url_route(
    request: Request,
    file_id: str,
):
    """
    Returns a signed GET URL for the file's permanent path.

    Returns 409 if the scan hasn't completed clean yet (still pending,
    scanning, infected, or errored) — callers should keep polling
    GET /upload/{fileId}/status until scan_status == "clean" before calling
    this endpoint.
    """
    result = get_system_file_read_url(file_id)

    log_audit_event(
        action=AuditAction.system_upload_read_url,
        request=request,
        document_id=file_id,
        resource=result["blob_path"],
    )

    return SystemFileReadUrlResponse(**result)
