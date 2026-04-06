from pydantic import BaseModel
from typing import Optional
from datetime import datetime


class PreflightCheck(BaseModel):
    name: str
    passed: bool
    detail: Optional[str] = None


class PreflightResponse(BaseModel):
    case_id: str
    all_passed: bool
    checks: list[PreflightCheck]


class SubmitForReviewResponse(BaseModel):
    case_id: str
    status: str                          # "Pending Attorney Review"
    submitted_at: datetime
    submitted_by: str
    notified_attorney_id: Optional[str] = None
