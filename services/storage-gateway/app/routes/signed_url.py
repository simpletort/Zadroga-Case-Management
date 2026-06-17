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
from app.services.gcs_service import MAX_SIGNED_URL_EXPIRY_MINUTES, generate_signed_url
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
    folder_path: str = Query("", description="Folder path relative to caseId, e.g. 'legal-forms/2024'. Empty = case root."),
    file_name: str = Query(..., description="File name, e.g. records_2024.pdf"),
    action: UrlAction = Query(UrlAction.read, description="'read' for download, 'write' for upload"),
    content_type: Optional[str] = Query(None, description="MIME type — required for write action"),
    inline: bool = Query(False, description="Return Content-Disposition: inline so browsers display the file rather than downloading it"),
    expiry_minutes: Optional[int] = Query(None, description=f"Requested TTL in minutes. Capped at {MAX_SIGNED_URL_EXPIRY_MINUTES} min regardless of value supplied."),
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

    blob_path = "{}/{}/{}".format(case_id, folder_path, file_name) if folder_path else "{}/{}".format(case_id, file_name)

    gcs_client = get_gcs_client()
    signed_url, expires_at, ttl_was_capped = generate_signed_url(
        gcs_client=gcs_client,
        blob_path=blob_path,
        action=action,
        content_type=content_type,
        expiry_minutes=expiry_minutes,
        inline=inline,
    )

    if ttl_was_capped:
        log_audit_event(
            action=AuditAction.signed_url_ttl_override,
            request=request,
            case_id=case_id,
            resource=blob_path,
            metadata={
                "requested_expiry_minutes": expiry_minutes or (
                    settings.signed_url_write_expiry_minutes
                    if action == UrlAction.write
                    else settings.signed_url_read_expiry_minutes
                ),
                "capped_expiry_minutes": MAX_SIGNED_URL_EXPIRY_MINUTES,
                "url_action": action.value,
            },
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
