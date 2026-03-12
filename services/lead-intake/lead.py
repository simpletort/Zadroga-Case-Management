"""
models/lead.py — Pydantic v2 models.

These are the single source of truth for:
  - Request/response validation
  - OpenAPI schema generation
  - Firestore document structure

PHI NOTE: These models hold PII. Never log full model instances.
Use .model_dump(include={'caseId', 'status'}) for safe log payloads.
"""
from __future__ import annotations

import re
from datetime import date, datetime
from enum import Enum
from typing import Optional
from uuid import uuid4

import phonenumbers
from pydantic import (
    BaseModel,
    EmailStr,
    Field,
    field_validator,
    model_validator,
)


# ── Enums ────────────────────────────────────────────────────────────────────

class WTCHealthProgramStatus(str, Enum):
    ENROLLED = "enrolled"
    APPLIED = "applied"
    NOT_APPLIED = "not_applied"
    UNKNOWN = "unknown"


class CaseStatus(str, Enum):
    NEW_LEAD = "New Lead"
    SCREENED = "Screened"
    QUALIFIED = "Qualified"
    DISQUALIFIED = "Disqualified"
    ACTIVE = "Active"
    CLOSED = "Closed"


class VCFEligibility(str, Enum):
    PENDING = "pending"
    ELIGIBLE = "eligible"
    INELIGIBLE = "ineligible"
    NEEDS_REVIEW = "needs_review"


# ── Sub-models ───────────────────────────────────────────────────────────────

class Address(BaseModel):
    street: Optional[str] = Field(None, max_length=200)
    city: Optional[str] = Field(None, max_length=100)
    state: Optional[str] = Field(
        None,
        max_length=2,
        pattern=r'^[A-Z]{2}$',
        description="Two-letter US state code (uppercase)",
    )
    zip: Optional[str] = Field(
        None,
        pattern=r'^\d{5}(-\d{4})?$',
    )


class ExposureDates(BaseModel):
    start: date = Field(..., description="Exposure start date")
    end: date = Field(..., description="Exposure end date")

    @model_validator(mode="after")
    def end_must_be_gte_start(self) -> "ExposureDates":
        if self.end < self.start:
            raise ValueError("exposureDates.end must be >= exposureDates.start")
        return self


# ── Request ──────────────────────────────────────────────────────────────────

class LeadRequest(BaseModel):
    """
    Inbound lead from a marketing partner.
    All string fields are stripped of leading/trailing whitespace on input.
    """

    firstName: str = Field(..., min_length=1, max_length=100, examples=["John"])
    lastName: str = Field(..., min_length=1, max_length=100, examples=["Doe"])
    email: EmailStr = Field(..., description="Primary contact email")
    phone: str = Field(
        ...,
        description="Phone in E.164 or US local format. Normalized on ingestion.",
        examples=["+12125551234", "212-555-1234"],
    )
    address: Optional[Address] = None
    exposureLocation: str = Field(
        ...,
        min_length=1,
        max_length=500,
        examples=["World Trade Center"],
    )
    exposureDates: ExposureDates
    wtcHealthProgramStatus: WTCHealthProgramStatus
    priorAttorney: bool = Field(
        ...,
        description="True if claimant has/had prior attorney for this claim",
    )
    marketingSource: str = Field(..., max_length=100, examples=["google_ads"])
    referralCode: Optional[str] = Field(None, max_length=100)

    # ── Field validators ─────────────────────────────────────────────────

    @field_validator("firstName", "lastName", "exposureLocation", "marketingSource", mode="before")
    @classmethod
    def strip_strings(cls, v: str) -> str:
        return v.strip() if isinstance(v, str) else v

    @field_validator("email", mode="before")
    @classmethod
    def normalise_email(cls, v: str) -> str:
        """Lowercase + strip email before pydantic EmailStr validation."""
        return v.strip().lower() if isinstance(v, str) else v

    @field_validator("phone", mode="before")
    @classmethod
    def normalise_phone(cls, v: str) -> str:
        """
        Normalise any plausible US/international number to E.164.
        Raises ValueError on unparseable input.
        """
        if not isinstance(v, str):
            raise ValueError("Phone must be a string")
        raw = v.strip()
        try:
            parsed = phonenumbers.parse(raw, "US")  # default region US
        except phonenumbers.NumberParseException:
            raise ValueError(f"Invalid phone number: {raw!r}")
        if not phonenumbers.is_valid_number(parsed):
            raise ValueError(f"Phone number is not valid: {raw!r}")
        return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)


# ── Response models ──────────────────────────────────────────────────────────

class LeadCreatedResponse(BaseModel):
    leadId: str = Field(..., pattern=r'^ZAD-\d{4}-\d{2}-\d{4}$', examples=["ZAD-2025-03-0001"])
    status: CaseStatus
    vcfScreeningStatus: VCFEligibility
    requestId: str
    timestamp: datetime


class ErrorDetail(BaseModel):
    field: str
    code: str
    message: str


class ErrorResponse(BaseModel):
    error: str
    message: str
    details: list[ErrorDetail] = []
    requestId: str
    timestamp: datetime


# ── Firestore case document ──────────────────────────────────────────────────

class CaseDocument(BaseModel):
    """
    Represents a Firestore case document.
    Generated by case_service.py; stored under /cases/{caseId}.
    """
    caseId: str
    status: CaseStatus = CaseStatus.NEW_LEAD
    vcfEligibility: VCFEligibility = VCFEligibility.PENDING

    # Claimant data (from LeadRequest)
    firstName: str
    lastName: str
    email: str          # normalised E.164 / lowercase
    phone: str          # normalised E.164
    address: Optional[Address] = None
    exposureLocation: str
    exposureDateStart: date
    exposureDateEnd: date
    wtcHealthProgramStatus: WTCHealthProgramStatus
    priorAttorney: bool

    # Source tracking
    marketingSource: str
    referralCode: Optional[str] = None
    partnerId: str      # extracted from JWT claim

    # System fields
    createdAt: datetime
    updatedAt: datetime
    requestId: str      # idempotency / trace key

    # VCF screening details (populated by Cloud Function)
    vcfScreeningDetails: Optional[dict] = None
    followupTaskId: Optional[str] = None

    def to_firestore_dict(self) -> dict:
        """
        Convert to a plain dict safe for Firestore.
        Dates serialised to ISO strings; datetimes to ISO strings.
        """
        data = self.model_dump()
        for key, val in data.items():
            if isinstance(val, (date, datetime)):
                data[key] = val.isoformat()
            elif isinstance(val, Enum):
                data[key] = val.value
        return data

    @classmethod
    def from_lead(
        cls,
        lead: LeadRequest,
        case_id: str,
        partner_id: str,
        request_id: str,
    ) -> "CaseDocument":
        now = datetime.utcnow()
        return cls(
            caseId=case_id,
            firstName=lead.firstName,
            lastName=lead.lastName,
            email=str(lead.email),
            phone=lead.phone,
            address=lead.address,
            exposureLocation=lead.exposureLocation,
            exposureDateStart=lead.exposureDates.start,
            exposureDateEnd=lead.exposureDates.end,
            wtcHealthProgramStatus=lead.wtcHealthProgramStatus,
            priorAttorney=lead.priorAttorney,
            marketingSource=lead.marketingSource,
            referralCode=lead.referralCode,
            partnerId=partner_id,
            createdAt=now,
            updatedAt=now,
            requestId=request_id,
        )
