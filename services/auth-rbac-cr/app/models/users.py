from __future__ import annotations

from typing import Optional
from pydantic import BaseModel


class CreateUserRequest(BaseModel):
    email: str
    password: str
    display_name: str
    role: str
    portal_token: Optional[str] = None


class UpdateUserRequest(BaseModel):
    displayName: Optional[str] = None
    googleWorkspaceId: Optional[str] = None
    role: Optional[str] = None
    isActive: Optional[bool] = None
