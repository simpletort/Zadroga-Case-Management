from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, field_validator


class CreateUpdateRequest(BaseModel):
    text: str

    @field_validator("text")
    @classmethod
    def text_not_blank(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("text must not be empty or whitespace")
        return v


class EditUpdateRequest(BaseModel):
    text: str

    @field_validator("text")
    @classmethod
    def text_not_blank(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("text must not be empty or whitespace")
        return v


class EditHistoryEntry(BaseModel):
    text: str
    edited_at: datetime


class CaseUpdateResponse(BaseModel):
    update_id: str
    case_id: str
    text: str
    author_id: str
    author_name: str
    author_role: str
    created_at: datetime
    updated_at: datetime
    is_edited: bool
    original_text: Optional[str]
    edit_history: list[dict[str, Any]]


class CaseUpdateListResponse(BaseModel):
    items: list[CaseUpdateResponse]
    total: int
    page: int
    page_size: int
    total_pages: int


class DeleteUpdateResponse(BaseModel):
    update_id: str
    deleted: bool = True
