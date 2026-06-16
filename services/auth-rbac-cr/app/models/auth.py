from __future__ import annotations

from typing import Optional
from pydantic import BaseModel, EmailStr


class RegisterRequest(BaseModel):
    email: str
    password: str
    display_name: str
    role: str = "client"
    portal_token: Optional[str] = None


class SessionRequest(BaseModel):
    id_token: str


class PasswordResetRequest(BaseModel):
    email: str


class InviteRequest(BaseModel):
    email: str
