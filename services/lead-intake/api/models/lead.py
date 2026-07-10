"""
api/models/lead.py — Pydantic v2 models for the Lead Intake API.

PHI NOTE: These models hold PII/PHI. Never log full model instances.
          Use .model_dump(include={"caseId", "status"}) for safe log payloads.
"""
from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Optional

import phonenumbers
from pydantic import BaseModel, EmailStr, Field, field_validator, model_validator


# ── Enums ─────────────────────────────────────────────────────────────────────

class WTCHealthProgramStatus(str, Enum):
    ENROLLED    = "enrolled"
    APPLIED     = "applied"
    NOT_APPLIED = "not_applied"
    UNKNOWN     = "unknown"


class CaseStatus(str, Enum):
    NEW_LEAD     = "New Lead"
    SCREENED     = "Screened"
    QUALIFIED    = "Qualified"
    DISQUALIFIED = "Disqualified"
    NEEDS_REVIEW = "Needs Review"
    ACTIVE       = "Active"
    CLOSED       = "Closed"


class VCFEligibility(str, Enum):
    PENDING      = "pending"
    ELIGIBLE     = "eligible"
    INELIGIBLE   = "ineligible"
    NEEDS_REVIEW = "needs_review"


# ── Sub-models ────────────────────────────────────────────────────────────────

class Address(BaseModel):
    street: Optional[str] = Field(None, max_length=200)
    city:   Optional[str] = Field(None, max_length=100)
    state:  Optional[str] = Field(None, max_length=2, pattern=r'^[A-Z]{2}$')
    zip:    Optional[str] = Field(None, pattern=r'^\d{5}(-\d{4})?$')


class ExposureDates(BaseModel):
    start: date = Field(..., description="Exposure start date")
    end:   date = Field(..., description="Exposure end date")

    @model_validator(mode="after")
    def end_not_before_start(self) -> "ExposureDates":
        if self.end < self.start:
            raise ValueError("exposureDates.end must be >= exposureDates.start")
        return self


class StatusHistoryEntry(BaseModel):
    status:    CaseStatus
    timestamp: datetime
    updatedBy: str = "system"
    note:      Optional[str] = None


# ── VCF covered condition categories (full list in docs/vcf_rules.md) ─────────

VCF_COVERED_CONDITION_CATEGORIES: frozenset[str] = frozenset({
    "aerodigestive", "cancer", "mental health", "musculoskeletal",
    "sleep disorder", "respiratory", "gastrointestinal", "neurological",
})


# ── Request model ─────────────────────────────────────────────────────────────

class LeadRequest(BaseModel):
    """Inbound lead submitted by a marketing partner."""

    firstName:             str                    = Field(..., min_length=1, max_length=100)
    lastName:              str                    = Field(..., min_length=1, max_length=100)
    email:                 EmailStr
    phone:                 str                    = Field(..., examples=["+12125551234"])
    ssn:                   Optional[str]          = Field(None, description= "Client SSN")
    dateOfBirth:           Optional[date]         = Field(None, description="Client date of birth (YYYY-MM-DD)")
    address:               Optional[Address]      = None
    exposureLocation:      str                    = Field(..., min_length=1, max_length=500)
    exposureDates:         ExposureDates
    wtcHealthProgramStatus: WTCHealthProgramStatus
    priorAttorney:         bool
    conditions:            list[str]              = Field(
        default_factory=list,
        description="Claimed medical conditions — matched against VCF covered categories.",
        max_length=20,
    )
    marketingSource:       str                    = Field(..., max_length=100)
    referralCode:          Optional[str]          = Field(None, max_length=100)

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
            raise ValueError("phone must be a string")
        raw = v.strip()
        try:
            parsed = phonenumbers.parse(raw, "US")
        except phonenumbers.NumberParseException:
            raise ValueError(f"invalid phone number: {raw!r}")
        if not phonenumbers.is_valid_number(parsed):
            raise ValueError(f"phone number not valid: {raw!r}")
        return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)

    @field_validator("ssn")
    @classmethod
    def normalize_ssn_field(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        digits = "".join(c for c in v if c.isdigit())
        if len(digits) != 9:
            raise ValueError("ssn must contain exactly 9 digits")
        return digits

    @field_validator("conditions", mode="before")
    @classmethod
    def normalise_conditions(cls, v) -> list[str]:
        if not v:
            return []
        return [c.strip().lower() for c in v if isinstance(c, str) and c.strip()]


# ── Request body for status updates ──────────────────────────────────────────

class UpdateStatusRequest(BaseModel):
    """Body for PATCH /leads/{lead_id}/status."""
    status:    CaseStatus
    note:      str = ""
    updatedBy: Optional[str] = None


# ── Response models ───────────────────────────────────────────────────────────

class LeadCreatedResponse(BaseModel):
    leadId:             str           = Field(..., pattern=r'^[A-Z]+-\d{4}-\d{2}-\d{4}$')
    status:             CaseStatus
    vcfScreeningStatus: VCFEligibility
    requestId:          str
    timestamp:          datetime


class ErrorDetail(BaseModel):
    field:   str
    code:    str
    message: str


class ErrorResponse(BaseModel):
    error:     str
    message:   str
    details:   list[ErrorDetail] = []
    requestId: str
    timestamp: datetime


# ── Firestore document model ──────────────────────────────────────────────────


class Assignment(BaseModel):
    assignedAdmin : Optional[str] = None,
    assignedAttorney : Optional[str] = None,
    assignedParalegal : Optional[str] = None,
    assignmentDate : Optional[datetime] = None
        
class CaseDocument(BaseModel):
    """
    Mirrors a Firestore /cases/{caseId} document.
    Created by case_service.create_case(); read back by get_case().

    status / wtcHealthProgramStatus are plain str, not the CaseStatus /
    WTCHealthProgramStatus enums: once a case leaves the lead-intake stage,
    case-development advances `status` through its own admin-configurable
    registry (firmSettings/case_statuses — e.g. "Pending Paralegal Review",
    "Approved for Filing"), and external intake integrations (e.g.
    google-forms/apps-script/Code.gs) patch `wtcHealthProgramStatus` directly
    in Firestore. get_case() must be able to deserialize those values; the
    enums remain authoritative for lead-intake's own writes (LeadRequest,
    UpdateStatusRequest).
    """
    caseId:       str
    status:       str    = CaseStatus.NEW_LEAD.value
    vcfEligibility: VCFEligibility = VCFEligibility.PENDING

    # True = still a lead; False = converted to an active case (flipped by update_case_status when status → Active)
    isLead: bool = True

    # Claimant
    firstName:             str
    lastName:              str
    email:                 str
    phone:                 str
    ssn:                   Optional[str] = None
    ssn_encrypted:         Optional[str] = None
    ssn_hash:              Optional[str] = None   # SHA-256 for duplicate detection queries
    dateOfBirth:           Optional[date]    = None  # optional — not always provided at intake
    address:               Optional[Address] = None
    exposureLocation:      str
    exposureDateStart:     date
    exposureDateEnd:       date
    wtcHealthProgramStatus: str
    priorAttorney:         bool
    conditions:            list[str] = Field(default_factory=list)

    # Source
    marketingSource: str
    referralCode:    Optional[str] = None
    partnerId:       str

    #Assignment
    assignment: Optional[Assignment] = None

    # Workflow
    #assignedTo:          Optional[str]      = None
    portalLoginAt:       Optional[datetime] = None
    followupTaskCreated: bool               = False
    followupTaskId:      Optional[str]      = None

    # History
    statusHistory: list[StatusHistoryEntry] = Field(default_factory=list)

    # Audit
    createdAt: datetime
    updatedAt: datetime
    requestId: str

    # VCF screening output (written by vcf_screener Cloud Function)
    vcfScreeningDetails: Optional[dict] = None

    def to_firestore_dict(self) -> dict:
        """
        Serialize to a Firestore-safe plain dict (dates/enums → strings).

        SECURITY: plaintext `ssn` is NEVER written to Firestore.
        If ssn is present, it is encrypted into `ssn_encrypted` via Cloud KMS CMEK.
        """
        # Exclude plaintext ssn from Firestore payload — always.
        data = self.model_dump(exclude={"ssn"})

        # Encrypt SSN → ssn_encrypted if plaintext was provided
        if self.ssn:
            from shared.crypto import encrypt_ssn, compute_ssn_hash
            data["ssn_encrypted"] = encrypt_ssn(self.ssn)
            data["ssn_hash"] = compute_ssn_hash(self.ssn)

        for key, val in data.items():
            if isinstance(val, (date, datetime)):
                data[key] = val.isoformat()
            elif isinstance(val, Enum):
                data[key] = val.value
        for entry in data.get("statusHistory", []):
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
            ssn=lead.ssn,  # plaintext; to_firestore_dict() encrypts before write
            dateOfBirth=lead.dateOfBirth,
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