from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class FeatureFlagsResponse(BaseModel):
    require_ai_summary: bool
    updated_at: Optional[datetime] = None
    updated_by: Optional[str]      = None


class UpdateFeatureFlagsRequest(BaseModel):
    require_ai_summary: Optional[bool] = None
