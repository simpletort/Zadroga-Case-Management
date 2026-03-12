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
    FileMetadataResponse,
    ProcessingStatus,
    VerificationStatus,
)
from app.utils.firestore import get_firestore_client

logger = logging.getLogger(__name__)


def _doc_ref(case_id: str, file_id: str):
    db = get_firestore_client()
    return db.collection("cases").document(case_id).collection("documents").document(file_id)


def get_file_metadata(case_id: str, file_id: str) -> FileMetadataResponse:
    """Fetch a single document metadata record from Firestore."""
    ref = _doc_ref(case_id, file_id)
    snap = ref.get()

    if not snap.exists:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="File '{}' not found for case '{}'.".format(file_id, case_id),
        )

    data = snap.to_dict()
    return FileMetadataResponse(
        file_id=file_id,
        case_id=case_id,
        file_name=data.get("fileName", ""),
        category=DocumentCategory(data.get("category", "client_uploads")),
        gcs_path=data.get("gcsPath", ""),
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
        document_ai_results=data.get("documentAiResults"),
        medical_ai_results=data.get("medicalAiResults"),
    )


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
