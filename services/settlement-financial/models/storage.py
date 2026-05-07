"""
models/storage.py
=================
Pydantic models for the GCS storage gateway endpoints.
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel


class CaseFileType(str, Enum):
    receipt          = "receipt"           # expense receipts
    lien_document    = "lien_document"     # lien supporting documents
    loan_document    = "loan_document"     # loan agreements
    settlement_doc   = "settlement_doc"    # executed settlement agreements
    case_document    = "case_document"     # general case files
    other            = "other"


class CaseFile(BaseModel):
    """Metadata for a single uploaded file."""
    file_id:           str
    case_id:           str
    original_filename: str
    content_type:      str
    size_bytes:        int
    gcs_path:          str                 # gs://bucket/path — canonical storage ref
    file_type:         CaseFileType
    description:       Optional[str] = None
    linked_to_type:    Optional[str] = None   # "expense" | "lien" | "loan" | None
    linked_to_id:      Optional[str] = None   # ID of linked record
    uploaded_by:       str
    uploaded_at:       datetime
    updated_at:        Optional[datetime] = None


class FileUploadResponse(BaseModel):
    """Returned after a successful file upload."""
    file_id:           str
    case_id:           str
    original_filename: str
    content_type:      str
    size_bytes:        int
    gcs_path:          str
    file_type:         CaseFileType
    description:       Optional[str] = None
    uploaded_by:       str
    uploaded_at:       datetime
    download_url:      str                 # signed URL (60 min) or gs:// fallback


class FileListResponse(BaseModel):
    """List of all files for a case."""
    case_id: str
    total:   int
    files:   List[CaseFile]


class SignedUrlResponse(BaseModel):
    """Signed download URL for a specific file."""
    file_id:    str
    gcs_path:   str
    signed_url: str
    expires_in: str = "60 minutes"
