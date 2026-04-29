"""
Metadata route — GET /api/v1/storage/{fileId}/metadata

Returns document metadata stored in cases/{caseId}/documents/{fileId}.
Used by SD-06 (Doc Viewer) and SD-07 (Doc AI Review) to show file info,
processing status, and AI results alongside the document.
"""

import logging

from fastapi import APIRouter, Query, Request

from app.models.storage import FileMetadataResponse
from app.services.metadata_service import get_file_metadata
from app.utils.audit import AuditAction, log_audit_event

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/storage", tags=["Storage"])


@router.get(
    "/{file_id}/metadata",
    response_model=FileMetadataResponse,
    summary="Get file metadata including AI processing results",
)
def get_metadata(
    request: Request,
    file_id: str,
    case_id: str = Query(..., description="Case ID that owns this document"),
):
    result = get_file_metadata(case_id=case_id, file_id=file_id)

    log_audit_event(
        action=AuditAction.view_metadata,
        request=request,
        document_id=file_id,
        case_id=case_id,
        resource=result.gcs_path,
    )

    return result
