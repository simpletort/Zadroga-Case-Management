"""
vcf_models.py — Pydantic models for VCF registration tracking workflow.

VCF Status Flow:
  Not Registered → Registration Pending → Registered
  On registration: capture VCF claim number and registration date.
  Registration date triggers VCF deadline calculation (certDate + 2 years).
"""

from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


class VCFRegistrationStatus(str, Enum):
    NOT_REGISTERED = "Not Registered"
    REGISTRATION_PENDING = "Registration Pending"
    REGISTERED = "Registered"


class VCFRegistrationStep(str, Enum):
    ELIGIBILITY_REVIEW = "eligibility_review"
    FORM_PREPARATION = "form_preparation"
    SUBMISSION_PENDING = "submission_pending"
    REGISTRATION_CONFIRMED = "registration_confirmed"
    DEADLINE_CALCULATED = "deadline_calculated"
    COMPLETE = "complete"


class DeadlineStatus(str, Enum):
    ACTIVE = "active"           # > 90 days remaining
    WARNING_90 = "warning_90"   # 61-90 days remaining
    WARNING_60 = "warning_60"   # 31-60 days remaining
    WARNING_30 = "warning_30"   # 1-30 days remaining
    EXPIRED = "expired"         # deadline passed
    NOT_SET = "not_set"         # no certification date yet


# ── Request models ────────────────────────────────────────────────────────────

class InitiateVCFRegistrationRequest(BaseModel):
    """Request to initiate VCF registration workflow for a case."""
    case_id: str = Field(..., description="Firestore case document ID")


class UpdateVCFStatusRequest(BaseModel):
    """Request to update VCF registration status."""
    status: VCFRegistrationStatus = Field(..., description="New VCF registration status")
    vcf_claim_number: Optional[str] = Field(
        None, description="VCF claim number (required when status=Registered)"
    )
    registration_date: Optional[datetime] = Field(
        None, description="Date registration was confirmed"
    )
    notes: Optional[str] = Field(None, max_length=1000)
    performed_by: str = Field(..., description="Staff user ID making the update")


# ── Response models ───────────────────────────────────────────────────────────

class VCFRegistrationRecord(BaseModel):
    """VCF registration data stored in the case document."""
    case_id: str
    status: VCFRegistrationStatus
    registration_step: VCFRegistrationStep
    vcf_claim_number: Optional[str] = None
    registration_date: Optional[datetime] = None
    vcf_filing_deadline: Optional[date] = None
    deadline_status: DeadlineStatus = DeadlineStatus.NOT_SET
    days_until_deadline: Optional[int] = None
    last_alert_milestone: Optional[int] = None   # last alert sent: 90, 60, or 30
    last_updated_at: Optional[datetime] = None
    last_updated_by: Optional[str] = None


class VCFRegistrationInitiateResponse(BaseModel):
    """Response after initiating VCF registration workflow."""
    case_id: str
    initiated: bool
    registration_step: VCFRegistrationStep
    task_id: Optional[str] = None
    message: str


class VCFStatusUpdateResponse(BaseModel):
    """Response after updating VCF registration status."""
    case_id: str
    old_status: str
    new_status: VCFRegistrationStatus
    timeline_event_id: str
    vcf_filing_deadline: Optional[str] = None   # ISO date string
    next_task_id: Optional[str] = None
    message: str


class VCFFormPrefillData(BaseModel):
    """Pre-filled data for VCF registration form, sourced from case record."""
    case_id: str
    # Identifying info (from case — minimal PHI exposure, only what VCF needs)
    date_of_birth: Optional[str] = None
    social_security_last4: Optional[str] = None
    # Exposure details
    exposure_location: Optional[str] = None
    exposure_start_date: Optional[str] = None
    exposure_end_date: Optional[str] = None
    # Condition details
    certified_condition: Optional[str] = None
    certification_date: Optional[str] = None
    # Legal representation
    attorney_name: Optional[str] = None
    firm_name: str = "Zadroga Law"
    firm_address: str = ""
    firm_phone: str = ""
    # VCF deadlines
    vcf_filing_deadline: Optional[str] = None   # certificationDate + 2 years
    generated_at: datetime = Field(default_factory=datetime.utcnow)


# ── Dashboard models ──────────────────────────────────────────────────────────

class DeadlineSummaryItem(BaseModel):
    case_id: str
    vcf_filing_deadline: str        # ISO date
    days_until_deadline: int
    deadline_status: DeadlineStatus
    vcf_registration_status: VCFRegistrationStatus
    assigned_paralegal: Optional[str] = None


class EnrollmentDashboardRow(BaseModel):
    case_id: str
    wtc_status: Optional[str] = None
    vcf_status: Optional[str] = None
    vcf_filing_deadline: Optional[str] = None
    deadline_status: Optional[DeadlineStatus] = None
    days_until_deadline: Optional[int] = None
    assigned_paralegal: Optional[str] = None
    last_updated: Optional[str] = None


class EnrollmentDashboardResponse(BaseModel):
    wtc_pipeline: dict[str, int]       # { "Not Enrolled": 5, "Application Pending": 3, ... }
    vcf_pipeline: dict[str, int]       # { "Not Registered": 8, ... }
    deadline_summary: dict[str, int]   # { "warning_30": 2, "warning_60": 4, ... }
    overdue_count: int
    cases: list[EnrollmentDashboardRow]
    total: int
    filtered_by_paralegal: Optional[str] = None
    filtered_by_status: Optional[str] = None
