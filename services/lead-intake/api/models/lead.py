"""
models/lead.py — Pydantic v2 models.

PHI NOTE: These models hold PII. Never log full model instances.
Use .model_dump(include={'caseId', 'status'}) for safe log payloads.
"""
from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Optional

import phonenumbers
from pydantic import (
    BaseModel,
    EmailStr,
    Field,
    field_validator,
    model_validator,
)


# ── Enums ─────────────────────────────────────────────────────────────────────

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
    NEEDS_REVIEW = "Needs Review"
    ACTIVE = "Active"
    CLOSED = "Closed"


class VCFEligibility(str, Enum):
    PENDING = "pending"
    ELIGIBLE = "eligible"
    INELIGIBLE = "ineligible"
    NEEDS_REVIEW = "needs_review"


# ── Sub-models ────────────────────────────────────────────────────────────────

class Address(BaseModel):
    street: Optional[str] = Field(None, max_length=200)
    city: Optional[str] = Field(None, max_length=100)
    state: Optional[str] = Field(
        None,
        max_length=2,
        pattern=r'^[A-Z]{2}$',
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


class StatusHistoryEntry(BaseModel):
    status: CaseStatus
    timestamp: datetime
    updatedBy: str = "system"
    note: Optional[str] = None


# ── VCF Covered Conditions (subset used for intake screening) ─────────────────
# Full list defined in infrastructure/vcf_rules.md
VCF_COVERED_CONDITION_CATEGORIES = {
    "aerodigestive",
    "cancer",
    "mental health",
    "musculoskeletal",
    "sleep disorder",
    "respiratory",
    "gastrointestinal",
    "neurological",
}


# ── Request ───────────────────────────────────────────────────────────────────

class LeadRequest(BaseModel):
    """Inbound lead from a marketing partner."""

    firstName: str = Field(..., min_length=1, max_length=100)
    lastName: str = Field(..., min_length=1, max_length=100)
    email: EmailStr
    phone: str = Field(..., examples=["+12125551234"])
    address: Optional[Address] = None
    exposureLocation: str = Field(..., min_length=1, max_length=500)
    exposureDates: ExposureDates
    wtcHealthProgramStatus: WTCHealthProgramStatus
    priorAttorney: bool
    conditions: list[str] = Field(
        default_factory=list,
        description="List of claimed medical conditions (free text, matched against VCF categories)",
        max_length=20,
    )
    marketingSource: str = Field(..., max_length=100)
    referralCode: Optional[str] = Field(None, max_length=100)

    @field_validator("firstName", "lastName", "exposureLocation", "marketingSource", mode="before")
    @classmethod
    def strip_strings(cls, v: str) -> str:
        return v.strip() if isinstance(v, str) else v

    @field_validator("email", mode="before")
    @classmethod
    def normalise_email(cls, v: str) -> str:
        return v.strip().lower() if isinstance(v, str) else v

    @field_validator("phone", mode="before")
    @classmethod
    def normalise_phone(cls, v: str) -> str:
        if not isinstance(v, str):
            raise ValueError("Phone must be a string")
        raw = v.strip()
        try:
            parsed = phonenumbers.parse(raw, "US")
        except phonenumbers.NumberParseException:
            raise ValueError(f"Invalid phone number: {raw!r}")
        if not phonenumbers.is_valid_number(parsed):
            raise ValueError(f"Phone number is not valid: {raw!r}")
        return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)

    @field_validator("conditions", mode="before")
    @classmethod
    def normalise_conditions(cls, v) -> list[str]:
        if not v:
            return []
        return [c.strip().lower() for c in v if isinstance(c, str) and c.strip()]


# ── Response models ───────────────────────────────────────────────────────────

class LeadCreatedResponse(BaseModel):
    leadId: str = Field(..., pattern=r'^ZAD-\d{4}-\d{2}-\d{4}$')
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


# ── Firestore case document ───────────────────────────────────────────────────

class CaseDocument(BaseModel):
    caseId: str
    status: CaseStatus = CaseStatus.NEW_LEAD
    vcfEligibility: VCFEligibility = VCFEligibility.PENDING

    # Claimant data
    firstName: str
    lastName: str
    email: str
    phone: str
    address: Optional[Address] = None
    exposureLocation: str
    exposureDateStart: date
    exposureDateEnd: date
    wtcHealthProgramStatus: WTCHealthProgramStatus
    priorAttorney: bool
    conditions: list[str] = Field(default_factory=list)

    # Source tracking
    marketingSource: str
    referralCode: Optional[str] = None
    partnerId: str

    # Assignment & workflow
    assignedTo: Optional[str] = None
    portalLoginAt: Optional[datetime] = None
    followupTaskCreated: bool = False
    followupTaskId: Optional[str] = None

    # Status history timeline
    statusHistory: list[StatusHistoryEntry] = Field(default_factory=list)

    # System fields
    createdAt: datetime
    updatedAt: datetime
    requestId: str

    # VCF screening
    vcfScreeningDetails: Optional[dict] = None

    def to_firestore_dict(self) -> dict:
        data = self.model_dump()
        for key, val in data.items():
            if isinstance(val, (date, datetime)):
                data[key] = val.isoformat()
            elif isinstance(val, Enum):
                data[key] = val.value
        if "statusHistory" in data:
            for entry in data["statusHistory"]:
                if isinstance(entry.get("timestamp"), datetime):
                    entry["timestamp"] = entry["timestamp"].isoformat()
                if isinstance(entry.get("status"), Enum):
                    entry["status"] = entry["status"].value
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
            conditions=lead.conditions,
            marketingSource=lead.marketingSource,
            referralCode=lead.referralCode,
            partnerId=partner_id,
            createdAt=now,
            updatedAt=now,
            requestId=request_id,
            statusHistory=[
                StatusHistoryEntry(
                    status=CaseStatus.NEW_LEAD,
                    timestamp=now,
                    updatedBy="system",
                    note="Lead created via API",
                )
            ],
        )
