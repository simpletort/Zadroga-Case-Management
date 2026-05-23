from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Optional
from pydantic import BaseModel, Field, model_validator
import uuid


class TaskStatus(str, Enum):
    PENDING     = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED   = "completed"
    SKIPPED     = "skipped"
    OVERDUE     = "overdue"


class TaskPriority(str, Enum):
    LOW      = "low"
    MEDIUM   = "medium"
    HIGH     = "high"
    CRITICAL = "critical"


class TaskType(str, Enum):
    # Lead & onboarding
    COMPLETE_QUESTIONNAIRE    = "complete_questionnaire"
    UPLOAD_DOCUMENTS          = "upload_documents"
    SIGN_RETAINER             = "sign_retainer"

    # Medical processing
    REVIEW_MEDICAL_SUMMARY    = "review_medical_summary"
    VERIFY_QUALIFICATION_SCORE = "verify_qualification_score"

    # Enrollment
    CONFIRM_WTC_ENROLLMENT    = "confirm_wtc_enrollment"
    SUBMIT_VCF_REGISTRATION   = "submit_vcf_registration"
    CHECK_ENROLLMENT_DEADLINE = "check_enrollment_deadline"

    # Case development
    ASSIGN_PARALEGAL          = "assign_paralegal"
    REVIEW_CASE_FILE          = "review_case_file"
    ATTORNEY_APPROVAL         = "attorney_approval"

    # Substitution of counsel
    GENERATE_SUBSTITUTION_FORM = "generate_substitution_form"
    REQUEST_PRIOR_FILES        = "request_prior_files"
    OBTAIN_SIGNATURE           = "obtain_signature"

    # Claim & settlement
    SUBMIT_VCF_CLAIM           = "submit_vcf_claim"
    TRACK_CLAIM_STATUS         = "track_claim_status"
    PROCESS_AWARD_LETTER       = "process_award_letter"
    PREPARE_SETTLEMENT_STATEMENT = "prepare_settlement_statement"
    DISBURSE_FUNDS             = "disburse_funds"

    # Generic / admin
    GENERIC           = "generic"
    DEADLINE_REMINDER = "deadline_reminder"


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------

class CreateTaskRequest(BaseModel):
    caseId: str
    title: str
    description: Optional[str] = None
    taskType: TaskType = TaskType.GENERIC
    priority: TaskPriority = TaskPriority.MEDIUM
    assignedTo: Optional[str] = None
    assignedToRole: Optional[str] = None
    dueAt: Optional[datetime] = None
    workflowExecutionId: Optional[str] = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class UpdateTaskRequest(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    priority: Optional[TaskPriority] = None
    dueAt: Optional[datetime] = None
    metadata: Optional[dict[str, Any]] = None


class CompleteTaskRequest(BaseModel):
    completedBy: str
    completionNotes: Optional[str] = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class AssignTaskRequest(BaseModel):
    assignedTo: Optional[str] = None
    assignedToRole: Optional[str] = None

    @model_validator(mode="after")
    def at_least_one_set(self) -> "AssignTaskRequest":
        if self.assignedTo is None and self.assignedToRole is None:
            raise ValueError("At least one of assignedTo or assignedToRole must be provided.")
        return self


class SkipTaskRequest(BaseModel):
    reason: str


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------

class TaskResponse(BaseModel):
    taskId: str
    caseId: str
    workflowExecutionId: Optional[str] = None
    title: str
    description: Optional[str] = None
    taskType: TaskType
    status: TaskStatus
    priority: TaskPriority
    assignedTo: Optional[str] = None
    assignedToRole: Optional[str] = None
    dueAt: Optional[datetime] = None
    reminderSentAt: Optional[datetime] = None
    createdAt: datetime
    updatedAt: datetime
    completedAt: Optional[datetime] = None
    completedBy: Optional[str] = None
    completionNotes: Optional[str] = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def from_firestore(cls, doc_id: str, data: dict[str, Any]) -> "TaskResponse":
        data = dict(data)
        data["taskId"] = doc_id
        # Firestore Python client returns Timestamps as tz-aware datetimes via to_dict().
        # Pydantic handles datetime natively so no conversion is needed here.
        return cls(**data)


class TaskListResponse(BaseModel):
    tasks: list[TaskResponse]
    count: int
