from pydantic import BaseModel, Field
from typing import Optional, Literal
from datetime import datetime


class CommunicationEntry(BaseModel):
    comm_id: str
    channel: str                          # Email | Call | Letter | Fax | In Person
    direction: str                        # Inbound | Outbound
    subject: str
    body: Optional[str] = None
    from_address: Optional[str] = None    # Firestore field: "from"
    to: Optional[str] = None
    delivery_status: Optional[str] = None # Sent | Failed | Pending
    is_automated: bool = False
    logged_by: Optional[str] = None       # staff UID who manually logged (empty if automated)
    template_id: Optional[str] = None
    external_message_id: Optional[str] = None
    sent_at: Optional[datetime] = None    # Firestore field: "sentAt"


class CommunicationLogRequest(BaseModel):
    channel: Literal["Email", "Call", "Letter", "Fax", "In Person"]
    direction: Literal["Inbound", "Outbound"]
    subject: str
    body: Optional[str] = None
    from_address: Optional[str] = None
    to: Optional[str] = None


class CommunicationListResponse(BaseModel):
    items: list[CommunicationEntry]
    total: int
    page: int
    page_size: int
    total_pages: int
