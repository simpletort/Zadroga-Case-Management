"""
Documents route — list, filter, and update document metadata for a case.

GET  /api/v1/storage/cases/{case_id}/documents              — paginated list with filters
PATCH /api/v1/storage/cases/{case_id}/documents/{file_id}  — partial metadata update

Used by:
  - Case Development service  (SD-04 Document List screen)
  - Evidence Management service (updating processingStatus + extractedData after AI pipeline)
  - Staff UI (Document AI Review screen, SD-07)
"""

import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Query, Request

from app.models.storage import (
    DocumentCategory,
    DocumentListResponse,
    DocumentMetadataUpdateRequest,
    FileMetadataResponse,
    ProcessingStatus,
    ScanStatus,
    VerificationStatus,
)
from app.services.metadata_service import query_case_documents, update_document_metadata
from app.utils.audit import AuditAction, log_audit_event
from app.utils.auth import require_min_role

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/storage", tags=["Documents"])


@router.get(
    "/cases/{case_id}/documents",
    response_model=DocumentListResponse,
    summary="List and filter case documents with pagination",
)
def list_case_documents(
    request: Request,
    case_id: str,
    category: Optional[DocumentCategory] = Query(None, description="Filter by document category"),
    processing_status: Optional[ProcessingStatus] = Query(None, description="Filter by AI processing status"),
    verification_status: Optional[VerificationStatus] = Query(None, description="Filter by staff verification status"),
    scan_status: Optional[ScanStatus] = Query(None, description="Filter by virus scan status"),
    uploaded_after: Optional[datetime] = Query(None, description="ISO-8601 — return documents uploaded after this timestamp"),
    uploaded_before: Optional[datetime] = Query(None, description="ISO-8601 — return documents uploaded before this timestamp"),
    page_size: int = Query(20, ge=1, le=100, description="Max documents per page (1–100)"),
    page_token: Optional[str] = Query(None, description="file_id of the last document from the previous page"),
    user: dict = Depends(require_min_role("documents_read")),
):
    """
    Returns documents for a case ordered by uploadedAt DESC.

    Supports filtering by category, processingStatus, verificationStatus, scanStatus,
    and date range.  Cursor-based pagination: pass the returned next_page_token as
    page_token in the next request to get the following page.
    """
    result = query_case_documents(
        case_id=case_id,
        category=category,
        processing_status=processing_status,
        verification_status=verification_status,
        scan_status=scan_status,
        uploaded_after=uploaded_after,
        uploaded_before=uploaded_before,
        page_size=page_size,
        page_token=page_token,
    )

    log_audit_event(
        action=AuditAction.list_documents,
        user=user,
        request=request,
        case_id=case_id,
        metadata={
            "category": category.value if category else None,
            "page_size": page_size,
            "documents_returned": len(result.documents),
        },
    )

    return result


@router.patch(
    "/cases/{case_id}/documents/{file_id}",
    response_model=FileMetadataResponse,
    summary="Update document processing metadata",
)
def patch_document_metadata(
    http_request: Request,
    case_id: str,
    file_id: str,
    request: DocumentMetadataUpdateRequest,
    user: dict = Depends(require_min_role("documents_update")),
):
    """
    Partially updates document metadata.  Only provided fields are written;
    omitted fields are unchanged.

    Intended callers:
      - Evidence Management service — sets processingStatus + extractedData after pipeline completes
      - Staff reviewers — sets verificationStatus after manual review
    """
    result = update_document_metadata(case_id=case_id, file_id=file_id, request=request)

    log_audit_event(
        action=AuditAction.update_metadata,
        user=user,
        request=http_request,
        document_id=file_id,
        case_id=case_id,
        resource=result.gcs_path,
        metadata={
            "fields_updated": [
                k for k, v in {
                    "processing_status": request.processing_status,
                    "verification_status": request.verification_status,
                    "extracted_data": request.extracted_data,
                }.items() if v is not None
            ]
        },
    )

    return result
