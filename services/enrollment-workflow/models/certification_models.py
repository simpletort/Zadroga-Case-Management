"""
Generic Certification Enrollment Models.

Represents enrollment in any program that requires a medical or eligibility
certification (e.g. WTC Health Program, VA benefits, state health programs).

Replaces the WTC-specific wtc_models.py — field names and enums are now
program-agnostic so the same workflow engine handles any certification program.

Firestore field names (on cases/{caseId}):
  enrollment.certificationStatus       — CertificationStatus enum value
  enrollment.certificationProgram      — program identifier string
  enrollment.certificationDate         — ISO date string when cert was confirmed
  enrollment.certificationWorkflowStep — CertificationWorkflowStep enum value
  enrollment.certificationNotes        — free-text notes
  enrollment.certificationUpdatedAt    — ISO datetime of last change
  enrollment.certificationUpdatedBy    — staff UID who made last change
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Status enum — valid states in the certification state machine
# ---------------------------------------------------------------------------

class CertificationStatus(str, Enum):
    """
    Valid statuses for program certification enrollment.

    State machine (valid forward transitions):
        None            → NOT_ENROLLED
        NOT_ENROLLED    → APPLICATION_PENDING | ALREADY_ENROLLED | DECEASED
        APPLICATION_PENDING → ENROLLED | NOT_ENROLLED | DECEASED
        ENROLLED        → ENROLLED  (idempotent re-confirmation allowed)
        ALREADY_ENROLLED → (terminal — no further transitions)
        DECEASED        → (terminal — no further transitions)
    """
    NOT_ENROLLED = "Not Enrolled"
    APPLICATION_PENDING = "Application Pending"
    ENROLLED = "Enrolled"
    ALREADY_ENROLLED = "Already Enrolled"
    DECEASED = "Deceased"


# ---------------------------------------------------------------------------
# Workflow step enum — tracks which step the Cloud Workflow is currently on
# ---------------------------------------------------------------------------

class CertificationWorkflowStep(str, Enum):
    """Internal step markers written to Firestore by the Cloud Workflow."""
    INITIAL_ASSESSMENT = "initial_assessment"
    PARALEGAL_TASK_CREATED = "paralegal_task_created"
    APPLICATION_SUBMITTED = "application_submitted"
    APPLICATION_PENDING = "application_pending"
    ENROLLMENT_CONFIRMED = "enrollment_confirmed"
    WORKFLOW_COMPLETE = "workflow_complete"
    WORKFLOW_SKIPPED = "workflow_skipped"       # used when ALREADY_ENROLLED or DECEASED


# ---------------------------------------------------------------------------
# Request / response schemas
# ---------------------------------------------------------------------------

class TriggerCertificationWorkflowRequest(BaseModel):
    """
    POST /api/v1/enrollment/certification/trigger

    Kicks off the certification enrollment workflow for a case.
    Idempotent: re-triggering an already-enrolled case returns the existing record.
    """
    case_id: str = Field(..., description="Firestore document ID of the case")
    program: str = Field(
        ...,
        description="Program identifier, e.g. 'wtc', 'va_benefits', 'state_health'",
        examples=["wtc"],
    )
    triggered_by: str = Field(..., description="Staff UID who initiated the workflow")
    notes: Optional[str] = Field(None, description="Optional context notes")


class UpdateCertificationStatusRequest(BaseModel):
    """
    PUT /api/v1/enrollment/certification/{case_id}/status

    Advance the certification status along the state machine.
    Invalid transitions return HTTP 422 with a descriptive error.
    """
    new_status: CertificationStatus
    updated_by: str = Field(..., description="Staff UID performing the update")
    certification_date: Optional[str] = Field(
        None,
        description=(
            "ISO date (YYYY-MM-DD) when program confirmed enrollment. "
            "Required when new_status == ENROLLED."
        ),
    )
    notes: Optional[str] = None


class CertificationEnrollmentRecord(BaseModel):
    """
    Full enrollment record returned by GET endpoints.
    Maps 1-to-1 with the enrollment sub-document in Firestore.
    """
    case_id: str
    program: str
    status: CertificationStatus
    workflow_step: CertificationWorkflowStep
    certification_date: Optional[str] = None       # ISO date; set when ENROLLED
    notes: Optional[str] = None
    updated_at: datetime
    updated_by: str
    created_at: datetime


class CertificationWorkflowTriggerResponse(BaseModel):
    """Response from POST /trigger."""
    case_id: str
    program: str
    status: CertificationStatus
    workflow_step: CertificationWorkflowStep
    task_id: Optional[str] = Field(
        None,
        description="ID of the paralegal task created, if any",
    )
    message: str


class CertificationStatusUpdateResponse(BaseModel):
    """Response from PUT /status."""
    case_id: str
    previous_status: CertificationStatus
    new_status: CertificationStatus
    workflow_step: CertificationWorkflowStep
    task_id: Optional[str] = Field(
        None,
        description="ID of the next-step paralegal task created, if any",
    )
    registration_triggered: bool = Field(
        False,
        description=(
            "True when transitioning to ENROLLED triggers the downstream "
            "registration workflow automatically."
        ),
    )
    message: str


class CertificationParalegalTask(BaseModel):
    """
    Shape of a paralegal task returned in dashboard responses.
    This is a read-only projection — task writes go through task_service.py.
    """
    task_id: str
    case_id: str
    title: str
    instructions: str
    due_date: datetime
    priority: str         # "low" | "medium" | "high" | "critical"
    assigned_to: Optional[str] = None
    assigned_to_role: str = "paralegal"
    status: str           # TaskStatus value
