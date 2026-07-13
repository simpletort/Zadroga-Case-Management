from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class StatusUpdateRequest(BaseModel):
    status: str
    notes: Optional[str] = None


class StatusUpdateResponse(BaseModel):
    case_id: str
    previous_status: str
    new_status: str
    updated_at: datetime
    updated_by: str
