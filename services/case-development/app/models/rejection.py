from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field, model_validator

# ── Enums ──────────────────────────────────────────────────────────────────────

RejectionReason = Literal[
    "insufficient_medical_evidence",
    "does_not_meet_vcf_criteria",
    "incomplete_documentation",
    "client_unresponsive",
    "other",
]


# ── Reject Case ────────────────────────────────────────────────────────────────

class RejectCaseRequest(BaseModel):
    reason: RejectionReason = Field(
        ...,
        description=(
            "Reason for rejection: 'insufficient_medical_evidence', "
            "'does_not_meet_vcf_criteria', 'incomplete_documentation', "
            "'client_unresponsive', or 'other' (notes required when 'other')."
        ),
    )
    notes: Optional[str] = Field(
        default=None,
        description="Additional context. Required when reason is 'other'.",
    )

    @model_validator(mode="after")
    def notes_required_for_other(self) -> "RejectCaseRequest":
        if self.reason == "other" and not (self.notes or "").strip():
            raise ValueError("notes are required when reason is 'other'.")
        return self


class RejectCaseResponse(BaseModel):
    case_id: str
    status: str                  # "Rejected"
    rejected_at: datetime
    rejection_id: str
    notified_paralegal: bool


# ── Resubmit Case ──────────────────────────────────────────────────────────────

class ResubmitCaseRequest(BaseModel):
    notes: Optional[str] = Field(
        default=None,
        description="What was addressed or fixed. Optional.",
    )


class ResubmitCaseResponse(BaseModel):
    case_id: str
    status: str                  # "Pending Paralegal Review"
    resubmitted_at: datetime
    notified_attorney: bool
