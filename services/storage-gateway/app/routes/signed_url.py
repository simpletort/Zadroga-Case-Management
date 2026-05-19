"""
Signed URL route — GET /api/v1/storage/signed-url

Used by the staff dashboard (SD-06 Doc Viewer, SD-18 Document Upload)
to get a time-limited, scoped URL for direct browser ↔ GCS transfer
without routing file bytes through this service.
"""

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Request, status

from app.models.storage import SignedUrlResponse, UrlAction
from app.services.gcs_service import generate_signed_url
from app.utils.audit import AuditAction, log_audit_event
from app.utils.gcs_client import get_gcs_client
from app.config import get_settings

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/storage", tags=["Storage"])
settings = get_settings()


@router.get(
    "/signed-url",
    response_model=SignedUrlResponse,
    summary="Generate a pre-signed GCS URL for secure file upload or download",
)
def get_signed_url(
    request: Request,
    case_id: str = Query(..., description="Case the file belongs to"),
    folder_path: str = Query(..., description="Folder path relative to caseId, e.g. 'legal-forms/2024'"),
    file_name: str = Query(..., description="File name, e.g. records_2024.pdf"),
    action: UrlAction = Query(UrlAction.read, description="'read' for download, 'write' for upload"),
    content_type: Optional[str] = Query(None, description="MIME type — required for write action"),
):
    if action == UrlAction.write and not content_type:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="content_type is required for write (upload) actions.",
        )

    if ".." in folder_path.split("/") or folder_path.startswith("/"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Invalid folder_path: must not escape the case directory.",
        )

    blob_path = "{}/{}/{}".format(case_id, folder_path, file_name)

    gcs_client = get_gcs_client()
    signed_url, expires_at = generate_signed_url(
        gcs_client=gcs_client,
        blob_path=blob_path,
        action=action,
        content_type=content_type,
    )

    audit_action = AuditAction.signed_url_read if action == UrlAction.read else AuditAction.signed_url_write
    log_audit_event(
        action=audit_action,
        request=request,
        case_id=case_id,
        resource=blob_path,
        metadata={"folder_path": folder_path, "file_name": file_name},
    )

    return SignedUrlResponse(
        signed_url=signed_url,
        blob_path=blob_path,
        bucket=settings.gcs_bucket_name,
        expires_at=expires_at,
        action=action,
    )
