"""
Task model — maps to Firestore: cases/{caseId}/tasks/{taskId}
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Optional
from pydantic import BaseModel, Field
import uuid


class TaskStatus(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    SKIPPED = "skipped"
    OVERDUE = "overdue"


class TaskPriority(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class TaskType(str, Enum):
    # Lead & onboarding
    COMPLETE_QUESTIONNAIRE = "complete_questionnaire"
    UPLOAD_DOCUMENTS = "upload_documents"
    SIGN_RETAINER = "sign_retainer"

    # Medical processing
    REVIEW_MEDICAL_SUMMARY = "review_medical_summary"
    VERIFY_QUALIFICATION_SCORE = "verify_qualification_score"

    # Enrollment
    CONFIRM_WTC_ENROLLMENT = "confirm_wtc_enrollment"
    SUBMIT_VCF_REGISTRATION = "submit_vcf_registration"
    CHECK_ENROLLMENT_DEADLINE = "check_enrollment_deadline"

    # Case development
    ASSIGN_PARALEGAL = "assign_paralegal"
    REVIEW_CASE_FILE = "review_case_file"
    ATTORNEY_APPROVAL = "attorney_approval"

    # Substitution of counsel
    GENERATE_SUBSTITUTION_FORM = "generate_substitution_form"
    REQUEST_PRIOR_FILES = "request_prior_files"
    OBTAIN_SIGNATURE = "obtain_signature"

    # Claim & settlement
    SUBMIT_VCF_CLAIM = "submit_vcf_claim"
    TRACK_CLAIM_STATUS = "track_claim_status"
    PROCESS_AWARD_LETTER = "process_award_letter"
    PREPARE_SETTLEMENT_STATEMENT = "prepare_settlement_statement"
    DISBURSE_FUNDS = "disburse_funds"

    # Generic / admin
    GENERIC = "generic"
    DEADLINE_REMINDER = "deadline_reminder"


class Task(BaseModel):
    """Canonical Task entity stored in Firestore."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    case_id: str
    workflow_execution_id: Optional[str] = None

    title: str
    description: Optional[str] = None
    task_type: TaskType = TaskType.GENERIC

    status: TaskStatus = TaskStatus.PENDING
    priority: TaskPriority = TaskPriority.MEDIUM

    # assigned_to: specific staff member (UID) — direct assignment.
    # assigned_to_role: role name — any staff member in that role can pick it up (team queue).
    # Only one should be set; dashboard queries filter on role; direct assignment uses UID.
    assigned_to: Optional[str] = None        # staff UID (direct assignment)
    assigned_to_role: Optional[str] = None   # "paralegal" | "attorney" | "client" (team queue)

    due_date: Optional[datetime] = None
    # reminder_sent_at: timestamp of when the reminder was sent; prevents duplicate reminder notifications
    # if the Cloud Tasks job fires multiple times or is retried.
    reminder_sent_at: Optional[datetime] = None

    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    completed_at: Optional[datetime] = None
    completed_by: Optional[str] = None
    completion_notes: Optional[str] = None

    # metadata: intentionally untyped dict for workflow-specific context (e.g., VCF IDs, award amounts).
    # Avoids schema changes when new workflows need to store additional data.
    metadata: dict[str, Any] = Field(default_factory=dict)

    def to_firestore(self) -> dict[str, Any]:
        # Serialise datetimes as ISO strings instead of Firestore's native Timestamp type.
        # ISO strings are portable (work across languages), consistent with Cloud Workflows YAML,
        # and human-readable in Firestore console for debugging.
        """Serialise for Firestore (ISO strings, no None keys omitted)."""
        data = self.model_dump()
        for key in ("created_at", "updated_at", "due_date",
                    "completed_at", "reminder_sent_at"):
            if data.get(key) is not None:
                data[key] = data[key].isoformat()
        return data

    @classmethod
    def from_firestore(cls, doc_id: str, data: dict[str, Any]) -> "Task":
        # Deserialise ISO string datetimes back to Python datetime objects.
        # Handles both already-parsed datetimes (from memory) and string datetimes (from Firestore).
        """Deserialise from a Firestore document snapshot."""
        data["id"] = doc_id
        for key in ("created_at", "updated_at", "due_date",
                    "completed_at", "reminder_sent_at"):
            if isinstance(data.get(key), str):
                data[key] = datetime.fromisoformat(data[key])
        return cls(**data)


class CreateTaskRequest(BaseModel):
    case_id: str
    title: str
    description: Optional[str] = None
    task_type: TaskType = TaskType.GENERIC
    priority: TaskPriority = TaskPriority.MEDIUM
    assigned_to: Optional[str] = None
    assigned_to_role: Optional[str] = None
    due_date: Optional[datetime] = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class CompleteTaskRequest(BaseModel):
    completed_by: str
    completion_notes: Optional[str] = None
    metadata: dict[str, Any] = Field(default_factory=dict)
