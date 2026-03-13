from datetime import datetime
from enum import Enum
from typing import Any, Optional
from pydantic import BaseModel, Field


class DocumentCategory(str, Enum):
    temp_lead_attachments = "temp_lead_attachments"
    medical_records = "medical_records"
    proof_of_presence = "proof_of_presence"
    id_documents = "id_documents"
    legal_forms = "legal_forms"
    vcf_documents = "vcf_documents"
    settlement_docs = "settlement_docs"
    client_uploads = "client_uploads"


class UrlAction(str, Enum):
    read = "read"
    write = "write"


class ProcessingStatus(str, Enum):
    pending = "Pending"
    processing = "Processing"
    completed = "Completed"
    failed = "Failed"


class VerificationStatus(str, Enum):
    unverified = "Unverified"
    ai_verified = "AI Verified"
    manually_verified = "Manually Verified"
    rejected = "Rejected"


class ScanStatus(str, Enum):
    pending = "pending"       # registered, not yet uploaded
    scanning = "scanning"     # Cloud Function picked it up
    clean = "clean"           # passed scan, moved to final path
    infected = "infected"     # malware detected, quarantined
    error = "error"           # scan failed unexpectedly


# ── Request / Response models ──────────────────────────────────────────────

class SignedUrlResponse(BaseModel):
    signed_url: str = Field(..., description="Pre-signed GCS URL for direct upload or download")
    blob_path: str = Field(..., description="Full GCS object path within the bucket")
    bucket: str
    expires_at: datetime
    action: UrlAction


class FileMetadataResponse(BaseModel):
    file_id: str
    case_id: str
    file_name: str
    category: DocumentCategory
    gcs_path: str
    mime_type: Optional[str] = None
    size_bytes: Optional[int] = None
    uploaded_by: Optional[str] = None
    uploaded_at: Optional[datetime] = None
    processing_status: ProcessingStatus = ProcessingStatus.pending
    verification_status: VerificationStatus = VerificationStatus.unverified
    document_ai_results: Optional[dict[str, Any]] = None
    medical_ai_results: Optional[dict[str, Any]] = None


class LifecycleCondition(BaseModel):
    age_days: int = Field(..., ge=1, description="Object age in days before rule applies")
    matches_prefix: Optional[list[str]] = Field(
        None, description="Restrict rule to objects whose name starts with one of these prefixes"
    )


class LifecycleAction(str, Enum):
    set_storage_class = "SetStorageClass"
    delete = "Delete"


class LifecycleRule(BaseModel):
    action: LifecycleAction
    storage_class: Optional[str] = Field(
        None, description="Target storage class for SetStorageClass action (e.g. NEARLINE, COLDLINE)"
    )
    condition: LifecycleCondition


class LifecycleUpdateRequest(BaseModel):
    rules: list[LifecycleRule] = Field(..., min_length=1)


class LifecycleUpdateResponse(BaseModel):
    bucket: str
    rules_applied: int
    message: str


class LifecyclePolicyResponse(BaseModel):
    bucket: str
    rules: list[dict[str, Any]]
    soft_delete_retention_days: Optional[int] = Field(
        None, description="Soft-delete retention window in days; None if not configured"
    )


class SoftDeleteRequest(BaseModel):
    retention_days: int = Field(
        30, ge=7, le=90,
        description="Number of days soft-deleted objects are recoverable (7–90)"
    )


class SoftDeleteResponse(BaseModel):
    bucket: str
    retention_days: int
    message: str


class CaseHoldRequest(BaseModel):
    hold: bool = Field(..., description="True to protect documents from lifecycle; False to release")


class CaseHoldResponse(BaseModel):
    case_id: str
    hold: bool
    documents_updated: int
    message: str


# ── Upload / Virus-scan models ─────────────────────────────────────────────

class UploadRegistrationRequest(BaseModel):
    file_name: str = Field(..., description="Original file name including extension")
    category: DocumentCategory
    content_type: str = Field(..., description="MIME type of the file")
    case_id: Optional[str] = Field(
        None, description="Required for case-scoped document categories"
    )
    size_bytes: Optional[int] = Field(None, ge=1)


class UploadRegistrationResponse(BaseModel):
    file_id: str = Field(..., description="UUID assigned to this upload — use for status polling")
    staging_path: str = Field(..., description="GCS staging path where the signed URL points")
    signed_url: str = Field(..., description="PUT this URL with the file bytes to upload")
    expires_at: datetime
    bucket: str


class UploadStatusResponse(BaseModel):
    file_id: str
    case_id: Optional[str] = None
    file_name: str
    category: DocumentCategory
    scan_status: ScanStatus
    staging_path: str
    final_path: Optional[str] = Field(None, description="Permanent GCS path — set after clean scan")
    quarantine_path: Optional[str] = Field(None, description="Set if file was infected")
    is_quarantined: bool = False
    scan_completed_at: Optional[datetime] = None
    registered_at: datetime
