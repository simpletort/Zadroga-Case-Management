"""
api/models/bulk_import.py — Pydantic v2 models for bulk lead import from Excel.

PHI NOTE: RowImportResult may reference case data indirectly (caseId only) —
never log full row payloads, matching the PHI-safe logging convention used
throughout this service (see logging_config.py's redact processor).
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field

from models.lead import ErrorDetail, VCFEligibility


# ── Column mapping ───────────────────────────────────────────────────────────

class ColumnMapping(BaseModel):
    """One entry in the confirmed mapping: Excel header -> LeadRequest field path."""
    excelColumn: str = Field(..., min_length=1, description="Raw header text from the sheet, e.g. 'First Name'")
    leadField:   str = Field(..., min_length=1, description="Dotted path into LeadRequest, e.g. 'exposureDates.start'")


class BulkImportRequest(BaseModel):
    """The JSON part of the multipart POST /leads/bulk-import body."""
    columnMappings:      list[ColumnMapping] = Field(..., min_length=1)
    headerRowIndex:       int                = Field(0, ge=0, description="0-based row index of the header row")
    sheetName:            Optional[str]      = Field(None, description="None = first sheet")
    marketingSource:       str               = Field(..., max_length=100)
    defaultReferralCode:  Optional[str]      = Field(None, max_length=100)


# ── Per-row result ────────────────────────────────────────────────────────────

class RowOutcome(str, Enum):
    CREATED           = "created"
    SKIPPED_DUPLICATE = "skipped_duplicate"
    FAILED            = "failed"


class RowImportResult(BaseModel):
    """One row's outcome — persisted at lead_import_jobs/{jobId}/results/{n}."""
    rowNumber:          int
    outcome:            RowOutcome
    caseId:             Optional[str]          = None
    error:               Optional[ErrorDetail] = None
    vcfScreeningStatus: Optional[VCFEligibility] = None


# ── Job status ────────────────────────────────────────────────────────────────

class LeadImportJobStatus(str, Enum):
    QUEUED     = "queued"
    SCANNING   = "scanning"
    PROCESSING = "processing"
    SUCCEEDED  = "succeeded"   # completed, possibly with per-row failures
    FAILED     = "failed"      # job-level failure — virus scan, unparseable file, etc.
    CANCELLED  = "cancelled"


class LeadImportJobSummary(BaseModel):
    totalRows: int = 0
    processed: int = 0
    created:   int = 0
    skipped:   int = 0
    failed:    int = 0


class LeadImportJobResponse(BaseModel):
    """Response body for POST /leads/bulk-import (202) and GET /leads/bulk-import/{jobId}."""
    jobId:       str
    status:      LeadImportJobStatus
    scanStatus:  Optional[str] = None
    summary:     LeadImportJobSummary
    createdAt:   datetime
    updatedAt:   datetime
    completedAt: Optional[datetime] = None
    fileName:    str
    partnerId:   str
    requestId:   str
    errorMessage: Optional[str] = None


class LeadImportJobResultsPage(BaseModel):
    """Response body for GET /leads/bulk-import/{jobId}/results."""
    jobId:         str
    results:       list[RowImportResult]
    nextPageToken: Optional[str] = None
