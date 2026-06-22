from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class CaseStatusEntry(BaseModel):
    value:    str
    label:    str
    category: str   # e.g. "active" | "closed" | "terminal"
    order:    int
    color:    str   # hex or named color, e.g. "#6B7280"


class CaseStatusRegistryResponse(BaseModel):
    statuses:   list[CaseStatusEntry]
    updated_at: Optional[datetime] = None
    updated_by: Optional[str]      = None


class CreateCaseStatusRequest(BaseModel):
    value:    str
    label:    str
    category: str
    order:    int
    color:    str


class UpdateCaseStatusRequest(BaseModel):
    label:    Optional[str] = None
    category: Optional[str] = None
    order:    Optional[int] = None
    color:    Optional[str] = None
