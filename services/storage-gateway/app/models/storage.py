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


class LifecycleAction(str, Enum):
    set_storage_class = "SetStorageClass"
    delete = "Delete"


class LifecycleRule(BaseModel):
    action: LifecycleAction
    storage_class: Optional[str] = Field(
        None, description="Target storage class for SetStorageClass action (e.g. COLDLINE)"
    )
    condition: LifecycleCondition


class LifecycleUpdateRequest(BaseModel):
    rules: list[LifecycleRule] = Field(..., min_length=1)


class LifecycleUpdateResponse(BaseModel):
    bucket: str
    rules_applied: int
    message: str
