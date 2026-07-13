from pydantic import BaseModel
from typing import Optional
from datetime import datetime


class AssignRequest(BaseModel):
    paralegal_id: str
    reason: Optional[str] = None


class AssignmentInfo(BaseModel):
    assigned_paralegal: Optional[str] = None
    assigned_paralegal_name: Optional[str] = None
    assigned_by: Optional[str] = None
    assignment_date: Optional[datetime] = None


class AssignmentResponse(BaseModel):
    case_id: str
    assignment: AssignmentInfo
    overridden_from: Optional[str] = None


class WorkloadEntry(BaseModel):
    user_id: str
    display_name: str
    active_case_count: int
    max_caseload: Optional[int] = None
    is_active: bool


class WorkloadResponse(BaseModel):
    paralegals: list[WorkloadEntry]
