"""
Signed URL route — GET /api/v1/storage/signed-url

Used by the staff dashboard (SD-06 Doc Viewer, SD-18 Document Upload)
to get a time-limited, scoped URL for direct browser ↔ GCS transfer
without routing file bytes through this service.
"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.models.storage import DocumentCategory, SignedUrlResponse, UrlAction
from app.services.gcs_service import build_blob_path, generate_signed_url
from app.utils.auth import require_min_role
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
    category: DocumentCategory = Query(..., description="Document category determines GCS path"),
    file_name: str = Query(..., description="Original file name (e.g. records_2024.pdf)"),
    action: UrlAction = Query(UrlAction.read, description="'read' for download, 'write' for upload"),
    case_id: Optional[str] = Query(None, description="Required for case-scoped categories"),
    content_type: Optional[str] = Query(None, description="MIME type — required for write action"),
    _user: dict = Depends(require_min_role("signed_url")),
):
    if action == UrlAction.write and not content_type:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="content_type is required for write (upload) actions.",
        )

    try:
        blob_path = build_blob_path(category, file_name, case_id)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(e),
        )

    gcs_client = get_gcs_client()
    signed_url, expires_at = generate_signed_url(
        gcs_client=gcs_client,
        blob_path=blob_path,
        action=action,
        content_type=content_type,
    )

    return SignedUrlResponse(
        signed_url=signed_url,
        blob_path=blob_path,
        bucket=settings.gcs_bucket_name,
        expires_at=expires_at,
        action=action,
    )
