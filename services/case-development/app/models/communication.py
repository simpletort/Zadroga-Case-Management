from pydantic import BaseModel
from typing import Optional, Literal
from datetime import datetime


class CommunicationEntry(BaseModel):
    comm_id: str
    type: str                         # call | email | letter | fax | in_person
    direction: str                    # inbound | outbound
    subject: str
    notes: Optional[str] = None
    contact_name: Optional[str] = None
    contact_method: Optional[str] = None   # phone number / email address / etc.
    created_by: str                   # staff UID
    created_by_name: Optional[str] = None
    created_at: datetime


class CommunicationLogRequest(BaseModel):
    type: Literal["call", "email", "letter", "fax", "in_person"]
    direction: Literal["inbound", "outbound"]
    subject: str
    notes: Optional[str] = None
    contact_name: Optional[str] = None
    contact_method: Optional[str] = None


class CommunicationListResponse(BaseModel):
    items: list[CommunicationEntry]
    total: int
    page: int
    page_size: int
    total_pages: int
