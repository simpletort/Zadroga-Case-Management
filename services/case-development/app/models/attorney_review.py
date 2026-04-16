from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime


class ReviewQueueItem(BaseModel):
    case_id: str
    first_name: str
    last_name: str
    case_type: Optional[str] = None
    vcf_deadline: Optional[datetime] = None
    qual_score: Optional[float] = None
    submitted_for_review_at: Optional[datetime] = None
    assigned_paralegal: Optional[str] = None
    assigned_paralegal_name: Optional[str] = None
    days_until_deadline: Optional[int] = None   # negative = overdue


class ReviewQueuePage(BaseModel):
    items: list[ReviewQueueItem]
    total: int
    page: int
    page_size: int
    total_pages: int


class ReviewQueueResponse(BaseModel):
    total_pending: int
    overdue_count: int
    page: ReviewQueuePage


# ── Approve for Filing ─────────────────────────────────────────────────────────

class ApproveForFilingRequest(BaseModel):
    notes: Optional[str] = Field(
        default=None,
        description="Optional attorney notes recorded with the approval.",
    )


class ApprovalResult(BaseModel):
    case_id: str
    success: bool
    status: Optional[str] = None          # "Approved for Filing" on success
    approved_at: Optional[datetime] = None
    task_ids: list[str] = []              # filing-prep tasks created
    error: Optional[str] = None           # populated on failure


class ApproveForFilingResponse(BaseModel):
    case_id: str
    status: str                            # "Approved for Filing"
    approved_at: datetime
    approved_by: str
    notes: Optional[str] = None
    task_ids: list[str] = []              # filing-prep tasks created


class BulkApproveRequest(BaseModel):
    case_ids: list[str] = Field(
        ...,
        min_length=1,
        description="List of case IDs to approve for filing.",
    )
    notes: Optional[str] = Field(
        default=None,
        description="Optional notes applied to all approved cases.",
    )


class BulkApproveResponse(BaseModel):
    requested: int
    approved: int
    failed: int
    results: list[ApprovalResult]
