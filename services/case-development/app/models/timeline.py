from pydantic import BaseModel
from typing import Optional
from datetime import datetime


class TimelineEvent(BaseModel):
    event_id: str
    event_type: str
    description: str
    performed_by: Optional[str] = None
    timestamp: Optional[datetime] = None


class TimelineListResponse(BaseModel):
    items: list[TimelineEvent]
    total: int
    page: int
    page_size: int
    total_pages: int
