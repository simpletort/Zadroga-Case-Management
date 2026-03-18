"""
api/models/partner.py — Partner management models.
"""
from __future__ import annotations
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field


class ApiKeyEntry(BaseModel):
    keyId: str
    label: str = ""
    keyHash: str  # SHA-256 of raw key
    createdAt: datetime
    expiresAt: Optional[datetime] = None
    active: bool = True


class ApiKeyResponse(BaseModel):
    """Returned once on key creation — never again (key not stored in plaintext)."""
    keyId: str
    apiKey: str  # Raw key — shown once only
    label: str
    createdAt: datetime
    expiresAt: Optional[datetime] = None


class PartnerDocument(BaseModel):
    partnerId: str
    name: str
    active: bool = True
    allowedIps: list[str] = Field(default_factory=list)
    requireHmac: bool = False
    hmacSecretName: Optional[str] = None
    apiKeys: list[ApiKeyEntry] = Field(default_factory=list)
    requestCount: int = 0
    lastRequestAt: Optional[datetime] = None
    createdAt: datetime
    updatedAt: datetime


class CreatePartnerRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    allowedIps: list[str] = Field(default_factory=list)
    requireHmac: bool = False


class CreateApiKeyRequest(BaseModel):
    label: str = Field(..., min_length=1, max_length=100)
    expiresAt: Optional[datetime] = None


class PartnerStatsResponse(BaseModel):
    partnerId: str
    name: str
    requestCount: int
    lastRequestAt: Optional[datetime]
    activeKeys: int
