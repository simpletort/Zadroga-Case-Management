"""
Generic Registration Models.

Represents enrollment/registration in any claims fund, benefits program, or
administrative system (e.g. VCF, FDNY claims, state compensation funds).

Replaces the VCF-specific vcf_models.py — field names and enums are now
program-agnostic so the same workflow engine can handle any registration.

Firestore field names (on cases/{caseId}):
  enrollment.registrationStatus      — RegistrationStatus enum value
  enrollment.registrationProgram     — program identifier string
  enrollment.registrationNumber      — claim/registration number once confirmed
  enrollment.filingDeadline          — ISO date string (calculated from certificationDate)
  enrollment.deadlineStatus          — DeadlineStatus enum value
  enrollment.lastAlertMilestone      — int: last alert fired (90 | 60 | 30 | 0)
  enrollment.registrationUpdatedAt   — ISO datetime
  enrollment.registrationUpdatedBy   — staff UID
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Status enums
# ---------------------------------------------------------------------------

class RegistrationStatus(str, Enum):
    """
    Valid statuses for program registration.

    State machine (valid forward transitions):
        None                  → NOT_REGISTERED
        NOT_REGISTERED        → REGISTRATION_PENDING
        REGISTRATION_PENDING  → REGISTERED | NOT_REGISTERED  (rejection/retry)
        REGISTERED            → REGISTERED  (idempotent re-confirmation)
    """
    NOT_REGISTERED = "Not Registered"
    REGISTRATION_PENDING = "Registration Pending"
    REGISTERED = "Registered"


class DeadlineStatus(str, Enum):
    """
    Urgency bucket for the registration filing deadline.

    Set by deadline_service.py whenever the filing deadline is updated or
    re-evaluated by the daily deadline-alerter Cloud Function.

    Values:
        NOT_SET    — deadline has not been calculated yet
        ACTIVE     — > 90 days remaining, no alert needed
        WARNING_90 — 61–90 days remaining
        WARNING_60 — 31–60 days remaining
        WARNING_30 — 0–30 days remaining
        EXPIRED    — deadline has passed
    """
    NOT_SET = "not_set"
    ACTIVE = "active"
    WARNING_90 = "warning_90"
    WARNING_60 = "warning_60"
    WARNING_30 = "warning_30"
    EXPIRED = "expired"


class RegistrationWorkflowStep(str, Enum):
    """Internal step markers written to Firestore by the Cloud Workflow."""
    CERTIFICATION_CHECK = "certification_check"
    REGISTRATION_INITIATED = "registration_initiated"
    SUBMISSION_PENDING = "submission_pending"
    REGISTERED = "registered"
    DEADLINE_CALCULATED = "deadline_calculated"
    WORKFLOW_COMPLETE = "workflow_complete"


# ---------------------------------------------------------------------------
# Request / response schemas
# ---------------------------------------------------------------------------

class InitiateRegistrationRequest(BaseModel):
    """
    POST /api/v1/enrollment/registration/initiate

    Starts the registration workflow for a case that has completed certification.
    Idempotent: re-initiating an already-registered case returns the existing record.
    """
    case_id: str = Field(..., description="Firestore document ID of the case")
    program: str = Field(
        ...,
        description=(
            "Program identifier, e.g. 'vcf', 'fdny_claims', 'state_fund'. "
            "Should match the certificationProgram used upstream."
        ),
        examples=["vcf"],
    )
    initiated_by: str = Field(..., description="Staff UID who initiated the workflow")
    notes: Optional[str] = None


class UpdateRegistrationStatusRequest(BaseModel):
    """
    PUT /api/v1/enrollment/registration/{case_id}/status

    Advance the registration status along the state machine.
    registration_number is required when transitioning to REGISTERED.
    """
    new_status: RegistrationStatus
    updated_by: str = Field(..., description="Staff UID performing the update")
    registration_number: Optional[str] = Field(
        None,
        description=(
            "Claim/registration number assigned by the program. "
            "Required when new_status == REGISTERED."
        ),
    )
    notes: Optional[str] = None


class RegistrationRecord(BaseModel):
    """
    Full registration record returned by GET endpoints.
    Maps 1-to-1 with the enrollment sub-document in Firestore.
    """
    case_id: str
    program: str
    status: RegistrationStatus
    workflow_step: RegistrationWorkflowStep
    registration_number: Optional[str] = None    # set when REGISTERED
    filing_deadline: Optional[str] = None        # ISO date
    deadline_status: DeadlineStatus = DeadlineStatus.NOT_SET
    last_alert_milestone: Optional[int] = None   # 90 | 60 | 30 | 0
    notes: Optional[str] = None
    updated_at: datetime
    updated_by: str
    created_at: datetime


class RegistrationFormPrefillData(BaseModel):
    """
    GET /api/v1/enrollment/registration/{case_id}/prefill

    Pre-populated form data assembled from the case record.
    Used to auto-fill the registration portal or a DocuSign template.
    All fields are Optional — the caller must validate completeness.
    """
    case_id: str
    program: str
    # Client identity (safe to return — these are never logged)
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    date_of_birth: Optional[str] = None
    # Case metadata
    certification_date: Optional[str] = None
    filing_deadline: Optional[str] = None
    # Existing registration number (if partially filed)
    registration_number: Optional[str] = None


# ---------------------------------------------------------------------------
# Dashboard schemas
# ---------------------------------------------------------------------------

class DeadlineSummaryItem(BaseModel):
    """One row in the deadline dashboard."""
    case_id: str
    client_name: Optional[str] = None     # display-only, never logged
    program: str
    filing_deadline: str                  # ISO date
    deadline_status: DeadlineStatus
    days_remaining: int
    registration_status: RegistrationStatus
    assigned_paralegal: Optional[str] = None


class EnrollmentDashboardRow(BaseModel):
    """One row in the main enrollment pipeline dashboard."""
    case_id: str
    client_name: Optional[str] = None     # display-only
    certification_status: Optional[str] = None
    certification_program: Optional[str] = None
    registration_status: Optional[RegistrationStatus] = None
    registration_program: Optional[str] = None
    filing_deadline: Optional[str] = None
    deadline_status: DeadlineStatus = DeadlineStatus.NOT_SET
    assigned_paralegal: Optional[str] = None
    last_updated: Optional[datetime] = None


class EnrollmentDashboardResponse(BaseModel):
    """
    GET /api/v1/dashboard/enrollment

    Summary counts + per-case rows for the full enrollment pipeline.
    """
    # Summary counters
    total_cases: int
    pending_certification: int
    enrolled: int
    pending_registration: int
    registered: int
    deadlines_warning: int     # cases in WARNING_30 or WARNING_60
    deadlines_critical: int    # cases in WARNING_30 (≤30 days)

    rows: list[EnrollmentDashboardRow]
