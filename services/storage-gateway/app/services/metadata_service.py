"""
Metadata Service — Firestore operations for file metadata.

File metadata lives in:  cases/{caseId}/documents/{fileId}

Fields written here are read by Evidence Management (AI processing),
Case Development (document list), and the Storage Gateway itself.
"""

import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException, status
from google.cloud import firestore

from app.models.storage import (
    DocumentCategory,
    DocumentListResponse,
    DocumentMetadataUpdateRequest,
    FileMetadataResponse,
    ProcessingStatus,
    ScanStatus,
    VerificationStatus,
)
from app.utils.firestore import get_firestore_client

logger = logging.getLogger(__name__)


def _doc_ref(case_id: str, file_id: str):
    db = get_firestore_client()
    return db.collection("cases").document(case_id).collection("documents").document(file_id)


def _snap_to_response(file_id: str, case_id: str, data: dict) -> FileMetadataResponse:
    """Build a FileMetadataResponse from a raw Firestore document dict."""
    return FileMetadataResponse(
        file_id=file_id,
        case_id=case_id,
        file_name=data.get("fileName", ""),
        category=DocumentCategory(data.get("category", "client_uploads")),
        gcs_path=data.get("gcsPath"),
        mime_type=data.get("mimeType"),
        size_bytes=data.get("sizeBytes"),
        uploaded_by=data.get("uploadedBy"),
        uploaded_at=data.get("uploadedAt"),
        processing_status=ProcessingStatus(
            data.get("processingStatus", ProcessingStatus.pending.value)
        ),
        verification_status=VerificationStatus(
            data.get("verificationStatus", VerificationStatus.unverified.value)
        ),
        scan_status=ScanStatus(
            data.get("scanStatus", ScanStatus.pending.value)
        ),
        extracted_data=data.get("extractedData"),
        document_ai_results=data.get("documentAiResults"),
        medical_ai_results=data.get("medicalAiResults"),
    )


def get_file_metadata(case_id: str, file_id: str) -> FileMetadataResponse:
    """Fetch a single document metadata record from Firestore."""
    ref = _doc_ref(case_id, file_id)
    snap = ref.get()

    if not snap.exists:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="File '{}' not found for case '{}'.".format(file_id, case_id),
        )

    return _snap_to_response(file_id, case_id, snap.to_dict())


def create_file_metadata(
    case_id: str,
    file_id: str,
    file_name: str,
    category: DocumentCategory,
    gcs_path: str,
    uploaded_by: str,
    mime_type: Optional[str] = None,
    size_bytes: Optional[int] = None,
) -> None:
    """
    Create a new document metadata record in Firestore.

    Called by the Evidence Management service (or staff upload handler)
    immediately after a file lands in GCS.
    """
    ref = _doc_ref(case_id, file_id)
    ref.set({
        "fileName": file_name,
        "category": category.value,
        "gcsPath": gcs_path,
        "mimeType": mime_type,
        "sizeBytes": size_bytes,
        "uploadedBy": uploaded_by,
        "uploadedAt": datetime.now(tz=timezone.utc),
        "processingStatus": ProcessingStatus.pending.value,
        "verificationStatus": VerificationStatus.unverified.value,
        "scanStatus": ScanStatus.pending.value,
        "extractedData": None,
        "documentAiResults": None,
        "medicalAiResults": None,
        "manualOverrides": [],
    })
    logger.info("Created metadata for file %s in case %s", file_id, case_id)


def update_processing_status(
    case_id: str,
    file_id: str,
    new_status: ProcessingStatus,
) -> None:
    """Update the AI processing status of a document. Called by Evidence Management."""
    ref = _doc_ref(case_id, file_id)
    ref.update({"processingStatus": new_status.value})
    logger.info(
        "Processing status updated: case=%s file=%s status=%s",
        case_id, file_id, new_status.value,
    )


def query_case_documents(
    case_id: str,
    category: Optional[DocumentCategory] = None,
    processing_status: Optional[ProcessingStatus] = None,
    verification_status: Optional[VerificationStatus] = None,
    scan_status: Optional[ScanStatus] = None,
    uploaded_after: Optional[datetime] = None,
    uploaded_before: Optional[datetime] = None,
    page_size: int = 20,
    page_token: Optional[str] = None,
) -> DocumentListResponse:
    """
    Query case documents with optional filters and cursor-based pagination.

    Results are always ordered by uploadedAt DESC.  Caller supplies
    page_token = file_id of the last document from the previous page to
    receive the next page.

    Composite Firestore indexes required (see firestore.indexes.json):
      documents: category + uploadedAt DESC
      documents: processingStatus + uploadedAt DESC
      documents: verificationStatus + uploadedAt DESC
      documents: scanStatus + uploadedAt DESC
    """
    db = get_firestore_client()
    col = db.collection("cases").document(case_id).collection("documents")

    query = col.order_by("uploadedAt", direction=firestore.Query.DESCENDING)

    if category is not None:
        query = query.where("category", "==", category.value)
    if processing_status is not None:
        query = query.where("processingStatus", "==", processing_status.value)
    if verification_status is not None:
        query = query.where("verificationStatus", "==", verification_status.value)
    if scan_status is not None:
        query = query.where("scanStatus", "==", scan_status.value)
    if uploaded_after is not None:
        query = query.where("uploadedAt", ">=", uploaded_after)
    if uploaded_before is not None:
        query = query.where("uploadedAt", "<=", uploaded_before)

    # Cursor pagination: start after the last document from the previous page
    if page_token:
        cursor_snap = col.document(page_token).get()
        if cursor_snap.exists:
            query = query.start_after(cursor_snap)

    # Fetch one extra document to determine whether another page exists
    docs = list(query.limit(page_size + 1).stream())

    has_more = len(docs) > page_size
    docs = docs[:page_size]
    next_page_token = docs[-1].id if has_more else None

    results = [
        _snap_to_response(doc.id, case_id, doc.to_dict() or {})
        for doc in docs
    ]

    logger.info(
        "Queried documents: case=%s filters=[cat=%s ps=%s vs=%s ss=%s] page_size=%s has_more=%s",
        case_id, category, processing_status, verification_status, scan_status,
        page_size, has_more,
    )

    return DocumentListResponse(
        case_id=case_id,
        documents=results,
        page_size=page_size,
        next_page_token=next_page_token,
        has_more=has_more,
    )


def update_document_metadata(
    case_id: str,
    file_id: str,
    request: DocumentMetadataUpdateRequest,
) -> FileMetadataResponse:
    """
    Partial update of document metadata fields.

    Only fields present in the request are written; all others remain unchanged.
    Returns the full updated document.
    """
    ref = _doc_ref(case_id, file_id)
    snap = ref.get()

    if not snap.exists:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="File '{}' not found for case '{}'.".format(file_id, case_id),
        )

    updates: dict = {}
    if request.processing_status is not None:
        updates["processingStatus"] = request.processing_status.value
    if request.verification_status is not None:
        updates["verificationStatus"] = request.verification_status.value
    if request.extracted_data is not None:
        updates["extractedData"] = request.extracted_data

    if updates:
        ref.update(updates)
        logger.info(
            "Document metadata updated: case=%s file=%s fields=%s",
            case_id, file_id, list(updates.keys()),
        )

    updated_snap = ref.get()
    return _snap_to_response(file_id, case_id, updated_snap.to_dict() or {})
