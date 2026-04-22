"""
Workflow models — execution records and trigger requests.
Workflow definitions live in cloud_workflows/*.yaml and are registered
in Cloud Workflows. This module tracks execution state in Firestore.

Configurable workflow definitions (WorkflowDefinitionConfig) are stored
in Firestore under workflow_definitions/{workflowId} and can be edited
by non-technical users via the admin API.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Optional
from pydantic import BaseModel, Field, field_validator
import uuid


class WorkflowType(str, Enum):
    # Each enum value maps 1-to-1 to:
    # 1. A Cloud Workflows YAML file (e.g. cloud_workflows/client-onboarding.yaml)
    # 2. A key in WORKFLOW_REGISTRY with required arguments and metadata
    """Maps 1-to-1 with a Cloud Workflows YAML definition."""
    LEAD_QUALIFICATION = "lead-qualification"
    CLIENT_ONBOARDING = "client-onboarding"
    MEDICAL_PROCESSING = "medical-processing"
    VCF_ENROLLMENT = "vcf-enrollment"
    SUBSTITUTION_OF_COUNSEL = "substitution-of-counsel"
    CLAIM_SUBMISSION = "claim-submission"
    SETTLEMENT = "settlement"


class WorkflowStatus(str, Enum):
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    WAITING_FOR_CALLBACK = "waiting_for_callback"


class WorkflowTriggerRequest(BaseModel):
    """Payload for POST /api/v1/workflows/trigger"""
    case_id: str
    workflow_type: str           # accepts WorkflowType enum values or dynamic string IDs
    triggered_by: str            # UID of the staff member or system account
    arguments: dict[str, Any] = Field(default_factory=dict)


class WorkflowExecution(BaseModel):
    """
    Firestore record: workflow_executions/{executionId}
    Also referenced from cases/{caseId}/workflow_executions/{executionId}
    """
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    case_id: str
    workflow_type: str           # WorkflowType enum value or dynamic string ID
    triggered_by: str

    # gcp_execution_name: the fully-qualified GCP resource name for this execution
    # Format: projects/{p}/locations/{r}/workflows/{w}/executions/{id}
    # Used for: fetching status, cancelling, querying logs.
    # Populated after trigger() launches the GCP execution; None if GCP call failed.
    gcp_execution_name: Optional[str] = None

    status: WorkflowStatus = WorkflowStatus.RUNNING
    arguments: dict[str, Any] = Field(default_factory=dict)
    result: Optional[dict[str, Any]] = None
    error: Optional[str] = None

    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    completed_at: Optional[datetime] = None

    def to_firestore(self) -> dict[str, Any]:
        data = self.model_dump()
        for key in ("created_at", "updated_at", "completed_at"):
            if data.get(key) is not None:
                data[key] = data[key].isoformat()
        return data

    @classmethod
    def from_firestore(cls, doc_id: str, data: dict[str, Any]) -> "WorkflowExecution":
        data["id"] = doc_id
        for key in ("created_at", "updated_at", "completed_at"):
            if isinstance(data.get(key), str):
                data[key] = datetime.fromisoformat(data[key])
        return cls(**data)


class WorkflowDefinition(BaseModel):
    """
    Static metadata about a workflow type — used for documentation
    and for building the trigger payload for Cloud Workflows.
    """
    workflow_type: WorkflowType
    display_name: str
    gcp_workflow_id: str          # name of the Cloud Workflow resource
    description: str
    required_arguments: list[str] = Field(default_factory=list)
    estimated_duration_hours: Optional[float] = None


# ---------------------------------------------------------------------------
# Firestore-backed configurable workflow definitions
# ---------------------------------------------------------------------------
# These replace WORKFLOW_REGISTRY and WORKFLOW_INITIAL_TASKS as the source of
# truth. Non-technical users edit these via the admin API; they are stored in
# Firestore under workflow_definitions/{workflowId}.

class TaskTemplateConfig(BaseModel):
    """Configurable human task step embedded in a WorkflowDefinitionConfig."""
    step_id: str              # stable identifier e.g. "sign_retainer" — never changes
    display_name: str         # shown in admin UI
    description: str
    # Editable by non-technical users:
    title: str
    priority: str             # validated: low | medium | high | critical
    due_offset_days: int      # days from trigger; engine converts × 24 to hours
    assigned_to_role: str     # validated: paralegal | attorney | client
    # Internal (not editable via admin UI):
    task_type: str = "generic"
    order: int = 1            # creation order, 1-based

    @field_validator("priority")
    @classmethod
    def validate_priority(cls, v: str) -> str:
        allowed = {"low", "medium", "high", "critical"}
        if v not in allowed:
            raise ValueError(f"priority must be one of {allowed}")
        return v

    @field_validator("assigned_to_role")
    @classmethod
    def validate_role(cls, v: str) -> str:
        allowed = {"paralegal", "attorney", "client"}
        if v not in allowed:
            raise ValueError(f"assigned_to_role must be one of {allowed}")
        return v


class ParameterDefinition(BaseModel):
    """Schema definition for one editable parameter of an automated step."""
    name: str                          # key in parameters dict
    label: str                         # human-readable label for admin UI
    description: str
    type: str                          # "number" | "string" | "boolean" | "percent"
    default_value: Any
    min_value: Optional[float] = None
    max_value: Optional[float] = None
    options: Optional[list[str]] = None  # for enum-style string fields


class AutomatedStepConfig(BaseModel):
    """Configurable automated or conditional step embedded in a WorkflowDefinitionConfig."""
    step_id: str
    display_name: str
    description: str
    is_condition: bool = False          # True = this is a branching/condition step
    parameter_schema: list[ParameterDefinition] = Field(default_factory=list)
    parameters: dict[str, Any] = Field(default_factory=dict)  # current editable values


class EventTriggerConfig(BaseModel):
    """Pub/Sub event mapping that auto-triggers a workflow."""
    event_type: str                           # e.g. "lead.qualified"
    arguments_mapping: dict[str, str]         # dot-notation e.g. {"case_id": "data.case_id"}
    description: Optional[str] = None


class WorkflowDefinitionConfig(BaseModel):
    """
    Firestore-backed workflow definition. Stored at workflow_definitions/{id}.
    Replaces the hardcoded WORKFLOW_REGISTRY and WORKFLOW_INITIAL_TASKS dicts.
    """
    id: str
    display_name: str
    description: str
    gcp_workflow_id: str                      # must match a deployed Cloud Workflow YAML name
    required_arguments: list[str] = Field(default_factory=list)
    estimated_duration_hours: Optional[float] = None
    is_active: bool = True
    task_templates: list[TaskTemplateConfig] = Field(default_factory=list)
    automated_steps: list[AutomatedStepConfig] = Field(default_factory=list)
    event_triggers: list[EventTriggerConfig] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    created_by: str = "system"

    def to_firestore(self) -> dict[str, Any]:
        data = self.model_dump()
        # Store datetimes as ISO strings for Firestore compatibility
        data["created_at"] = self.created_at.isoformat()
        data["updated_at"] = self.updated_at.isoformat()
        return data

    @classmethod
    def from_firestore(cls, doc_id: str, data: dict[str, Any]) -> "WorkflowDefinitionConfig":
        data = dict(data)
        data["id"] = doc_id
        # Parse ISO strings back to datetime objects
        for key in ("created_at", "updated_at"):
            if isinstance(data.get(key), str):
                data[key] = datetime.fromisoformat(data[key])
        return cls(**data)


class CreateWorkflowDefinitionRequest(BaseModel):
    """Payload for POST /api/v1/admin/workflows"""
    id: str
    display_name: str
    description: str
    gcp_workflow_id: str
    required_arguments: list[str] = Field(default_factory=list)
    estimated_duration_hours: Optional[float] = None


class UpdateWorkflowDefinitionRequest(BaseModel):
    """Payload for PATCH /api/v1/admin/workflows/{workflow_id}"""
    display_name: Optional[str] = None
    description: Optional[str] = None
    estimated_duration_hours: Optional[float] = None
    is_active: Optional[bool] = None


# WORKFLOW_REGISTRY: single source of truth for workflow metadata.
# Defines: required arguments, GCP resource name, display name, duration estimates.
# Used by API to validate trigger requests before calling GCP and by sync_execution_status
# to map GCP states back to our WorkflowStatus enum.
# IMPORTANT: every WorkflowType enum value MUST have an entry here.
WORKFLOW_REGISTRY: dict[WorkflowType, WorkflowDefinition] = {
    WorkflowType.LEAD_QUALIFICATION: WorkflowDefinition(
        workflow_type=WorkflowType.LEAD_QUALIFICATION,
        gcp_workflow_id="lead-qualification",
        display_name="Lead Qualification",
        description="Screens a new lead against VCF eligibility criteria and initiates client onboarding.",
        required_arguments=["lead_id"],
        estimated_duration_hours=0.5,
    ),
    WorkflowType.CLIENT_ONBOARDING: WorkflowDefinition(
        workflow_type=WorkflowType.CLIENT_ONBOARDING,
        gcp_workflow_id="client-onboarding",
        display_name="Client Onboarding",
        description="Creates client portal account, sends retainer for e-signature, and builds document checklist.",
        required_arguments=["case_id", "client_email"],
        estimated_duration_hours=24.0,
    ),
    WorkflowType.MEDICAL_PROCESSING: WorkflowDefinition(
        workflow_type=WorkflowType.MEDICAL_PROCESSING,
        gcp_workflow_id="medical-processing",
        display_name="Medical Document Processing",
        description="Runs Document AI OCR + MedLM summarisation and qualification scoring.",
        required_arguments=["case_id", "document_ids"],
        estimated_duration_hours=1.0,
    ),
    WorkflowType.VCF_ENROLLMENT: WorkflowDefinition(
        workflow_type=WorkflowType.VCF_ENROLLMENT,
        gcp_workflow_id="vcf-enrollment",
        display_name="WTC / VCF Enrollment",
        description="Tracks WTC Health Program and VCF registration status, schedules deadline alerts.",
        required_arguments=["case_id"],
        estimated_duration_hours=None,
    ),
    WorkflowType.SUBSTITUTION_OF_COUNSEL: WorkflowDefinition(
        workflow_type=WorkflowType.SUBSTITUTION_OF_COUNSEL,
        gcp_workflow_id="substitution-of-counsel",
        display_name="Substitution of Counsel",
        description="Generates substitution form, collects e-signature via DocuSign, requests prior attorney files.",
        required_arguments=["case_id", "prior_attorney_id"],
        estimated_duration_hours=72.0,
    ),
    WorkflowType.CLAIM_SUBMISSION: WorkflowDefinition(
        workflow_type=WorkflowType.CLAIM_SUBMISSION,
        gcp_workflow_id="claim-submission",
        display_name="VCF Claim Submission",
        description="Assembles claim package, submits to VCF, and begins post-filing status tracking.",
        required_arguments=["case_id"],
        estimated_duration_hours=2.0,
    ),
    WorkflowType.SETTLEMENT: WorkflowDefinition(
        workflow_type=WorkflowType.SETTLEMENT,
        gcp_workflow_id="settlement",
        display_name="Settlement & Disbursement",
        description="Calculates settlement, generates settlement statement, obtains signatures, disburses funds via QuickBooks.",
        required_arguments=["case_id", "award_amount"],
        estimated_duration_hours=48.0,
    ),
}
