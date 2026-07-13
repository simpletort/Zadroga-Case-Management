"""
wtc_models.py — Pydantic models for WTC Health Program enrollment workflow.

WTC Status Flow:
  Not Enrolled → Application Pending → Enrolled
  (Edge cases: Already Enrolled, Deceased — bypasses workflow)
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class WTCEnrollmentStatus(str, Enum):
    NOT_ENROLLED = "Not Enrolled"
    APPLICATION_PENDING = "Application Pending"
    ENROLLED = "Enrolled"
    ALREADY_ENROLLED = "Already Enrolled"   # idempotency: skip workflow
    DECEASED = "Deceased"                   # edge case: deceased claimant


class WTCWorkflowStep(str, Enum):
    INITIAL_ASSESSMENT = "initial_assessment"
    PARALEGAL_TASK_CREATED = "paralegal_task_created"
    APPLICATION_SUBMITTED = "application_submitted"
    APPLICATION_PENDING = "application_pending"
    ENROLLMENT_CONFIRMED = "enrollment_confirmed"
    WORKFLOW_COMPLETE = "workflow_complete"
    WORKFLOW_SKIPPED = "workflow_skipped"   # already enrolled or deceased


# ── Request models ────────────────────────────────────────────────────────────

class TriggerWTCWorkflowRequest(BaseModel):
    """Request to trigger WTC enrollment workflow for a case."""
    case_id: str = Field(..., description="Firestore case document ID")
    force: bool = Field(
        False,
        description="Force workflow even if already enrolled (admin override)",
    )


class UpdateWTCStatusRequest(BaseModel):
    """Request to update WTC enrollment status."""
    status: WTCEnrollmentStatus = Field(..., description="New WTC enrollment status")
    notes: Optional[str] = Field(None, max_length=1000)
    application_date: Optional[datetime] = Field(
        None, description="Date application was submitted to WTC program"
    )
    enrollment_date: Optional[datetime] = Field(
        None, description="Date enrollment was confirmed (only when status=Enrolled)"
    )
    wtc_member_id: Optional[str] = Field(
        None, description="WTC program member ID assigned on enrollment"
    )
    performed_by: str = Field(..., description="Staff user ID making the update")


# ── Response models ───────────────────────────────────────────────────────────

class WTCEnrollmentRecord(BaseModel):
    """WTC enrollment data stored in the case document."""
    case_id: str
    status: WTCEnrollmentStatus
    workflow_step: WTCWorkflowStep
    workflow_triggered_at: Optional[datetime] = None
    application_date: Optional[datetime] = None
    enrollment_date: Optional[datetime] = None
    wtc_member_id: Optional[str] = None
    notes: Optional[str] = None
    last_updated_at: Optional[datetime] = None
    last_updated_by: Optional[str] = None


class WTCWorkflowTriggerResponse(BaseModel):
    """Response after triggering WTC enrollment workflow."""
    case_id: str
    triggered: bool
    workflow_step: WTCWorkflowStep
    task_id: Optional[str] = None
    message: str


class WTCStatusUpdateResponse(BaseModel):
    """Response after updating WTC enrollment status."""
    case_id: str
    old_status: str
    new_status: WTCEnrollmentStatus
    timeline_event_id: str
    next_task_id: Optional[str] = None
    message: str


# ── Task definitions ──────────────────────────────────────────────────────────

class WTCParalegalTask(BaseModel):
    """Auto-created paralegal task for a WTC workflow step."""
    title: str
    instructions: str
    due_days: int          # Days from now to set due date
    priority: str          # high | medium | low
    step: WTCWorkflowStep
