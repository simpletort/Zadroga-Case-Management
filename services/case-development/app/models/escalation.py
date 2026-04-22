from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field, model_validator

# ── Enums ──────────────────────────────────────────────────────────────────────

EscalationReason = Literal[
    "high_value_claim",
    "unusual_medical_condition",
    "prior_attorney_conflict",
    "other",
]

EscalationDecision = Literal["approve", "reject", "return_to_paralegal"]


# ── Escalate Request / Response ────────────────────────────────────────────────

class EscalateRequest(BaseModel):
    reason: EscalationReason = Field(
        ...,
        description=(
            "Reason for escalation: 'high_value_claim', 'unusual_medical_condition', "
            "'prior_attorney_conflict', or 'other' (notes required when 'other')."
        ),
    )
    notes: Optional[str] = Field(
        default=None,
        description="Additional context. Required when reason is 'other'.",
    )

    @model_validator(mode="after")
    def notes_required_for_other(self) -> "EscalateRequest":
        if self.reason == "other" and not (self.notes or "").strip():
            raise ValueError("notes are required when reason is 'other'.")
        return self


class EscalateResponse(BaseModel):
    case_id: str
    status: str                  # "Pending Senior Review"
    escalated_at: datetime
    escalation_id: str
    notified_count: int          # number of senior partners notified


# ── Escalation Queue ───────────────────────────────────────────────────────────

class EscalationQueueItem(BaseModel):
    case_id: str
    first_name: str
    last_name: str
    case_type: Optional[str] = None
    vcf_deadline: Optional[datetime] = None
    qual_score: Optional[float] = None
    days_until_deadline: Optional[int] = None   # negative = overdue
    escalation_id: str
    escalation_reason: str
    escalated_at: Optional[datetime] = None
    escalated_by_name: Optional[str] = None
    original_attorney_id: Optional[str] = None
    escalation_notes: Optional[str] = None


class EscalationQueuePage(BaseModel):
    items: list[EscalationQueueItem]
    total: int
    page: int
    page_size: int
    total_pages: int


class EscalationQueueResponse(BaseModel):
    total_pending: int
    overdue_count: int
    page: EscalationQueuePage


# ── Escalation Decision ────────────────────────────────────────────────────────

class EscalationDecideRequest(BaseModel):
    decision: EscalationDecision = Field(
        ...,
        description=(
            "'approve' → Approved for Filing; "
            "'reject' → back to attorney queue; "
            "'return_to_paralegal' → back to paralegal."
        ),
    )
    notes: Optional[str] = Field(
        default=None,
        description="Decision notes. Required when decision is 'reject' or 'return_to_paralegal'.",
    )

    @model_validator(mode="after")
    def notes_required_for_non_approve(self) -> "EscalationDecideRequest":
        if self.decision in ("reject", "return_to_paralegal") and not (self.notes or "").strip():
            raise ValueError("notes are required when decision is 'reject' or 'return_to_paralegal'.")
        return self


class EscalationDecideResponse(BaseModel):
    case_id: str
    decision: str
    resolved_at: datetime
    resolved_by: str
    notes: Optional[str] = None
    task_ids: list[str] = []     # populated on approve
    new_status: str
