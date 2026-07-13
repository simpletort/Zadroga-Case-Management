"""
models/fee_config.py — Pydantic models for attorney fee configuration.

Supports:
  - Flat percentage (e.g. 33.33% of gross award)
  - Graduated / tiered percentages (e.g. 33% on first $250k, 25% on next $250k)
  - Fee caps (fixed dollar amount or percentage ceiling)
  - Per-case overrides over firm default
  - Audit trail entries

Firestore paths
---------------
  firm_settings/fee_config                ← current firm-wide default
  firm_settings/fee_config/audit/{uuid}   ← change log
  cases/{caseId}/settlement/fee_override  ← per-case override
"""
from __future__ import annotations

from decimal import Decimal
from enum import Enum
from typing import List, Optional
from datetime import datetime

from pydantic import BaseModel, Field, field_validator, field_serializer, model_validator


# ── Enums ──────────────────────────────────────────────────────────────────────

class FeeStructureType(str, Enum):
    flat       = "flat"        # single percentage of gross award
    graduated  = "graduated"   # tiered percentages


class FeeCapType(str, Enum):
    none       = "none"        # no cap
    amount     = "amount"      # cap at a fixed dollar amount
    percentage = "percentage"  # cap at a percentage of gross award


# ── Graduated tier ─────────────────────────────────────────────────────────────

class GraduatedTier(BaseModel):
    """
    One band in a graduated fee schedule.

    Example tiers for a 3-band schedule:
      {"up_to": "250000.00", "percentage": "33.33"}   ← first $250 k
      {"up_to": "500000.00", "percentage": "25.00"}   ← next  $250 k
      {"up_to": null,        "percentage": "20.00"}   ← above $500 k
    """
    up_to:      Optional[Decimal] = Field(
        None,
        description="Upper bound (inclusive) in USD. null = no upper limit (must be the last tier)."
    )
    percentage: Decimal = Field(
        ...,
        ge=Decimal("0"),
        le=Decimal("100"),
        description="Fee percentage applied to the portion of the award within this tier.",
    )

    @field_validator("up_to", "percentage", mode="before")
    @classmethod
    def coerce_decimal(cls, v):
        if v is None:
            return v
        try:
            return Decimal(str(v))
        except Exception:
            raise ValueError("value must be a valid decimal number")

    @field_serializer("up_to")
    def serialize_up_to(self, v: Optional[Decimal]) -> Optional[str]:
        return f"{v:.2f}" if v is not None else None

    @field_serializer("percentage")
    def serialize_percentage(self, v: Decimal) -> str:
        return f"{v:.4f}"


# ── Core fee configuration ─────────────────────────────────────────────────────

class FeeConfigData(BaseModel):
    """
    The fee structure definition.  Used both for the firm default and per-case
    overrides so the shape is always identical.
    """
    structure_type:   FeeStructureType  = FeeStructureType.flat
    flat_percentage:  Optional[Decimal] = Field(
        None, ge=Decimal("0"), le=Decimal("100"),
        description="Required when structure_type='flat'."
    )
    graduated_tiers:  List[GraduatedTier] = Field(
        default_factory=list,
        description="Required (non-empty) when structure_type='graduated'. "
                    "Must end with a tier whose up_to is null.",
    )
    cap_type:         FeeCapType         = FeeCapType.none
    cap_amount:       Optional[Decimal]  = Field(
        None, gt=Decimal("0"),
        description="Maximum fee in USD. Required when cap_type='amount'."
    )
    cap_percentage:   Optional[Decimal]  = Field(
        None, gt=Decimal("0"), le=Decimal("100"),
        description="Maximum fee as % of gross award. Required when cap_type='percentage'."
    )

    @field_validator("flat_percentage", "cap_amount", "cap_percentage", mode="before")
    @classmethod
    def coerce_decimal(cls, v):
        if v is None:
            return v
        try:
            return Decimal(str(v))
        except Exception:
            raise ValueError("value must be a valid decimal number")

    @model_validator(mode="after")
    def validate_structure(self) -> "FeeConfigData":
        if self.structure_type == FeeStructureType.flat:
            if self.flat_percentage is None:
                raise ValueError("flat_percentage is required when structure_type is 'flat'")
        else:  # graduated
            if not self.graduated_tiers:
                raise ValueError(
                    "graduated_tiers must not be empty when structure_type is 'graduated'"
                )
            unlimited = [t for t in self.graduated_tiers if t.up_to is None]
            if len(unlimited) != 1:
                raise ValueError(
                    "Exactly one graduated tier must have up_to=null (the final unlimited tier)"
                )
            if self.graduated_tiers[-1].up_to is not None:
                raise ValueError(
                    "The last graduated tier must have up_to=null (it covers all remaining award)"
                )
            # Tiers must be in strictly ascending order
            limits = [t.up_to for t in self.graduated_tiers if t.up_to is not None]
            if limits != sorted(limits):
                raise ValueError("Graduated tier up_to values must be in ascending order")

        if self.cap_type == FeeCapType.amount and self.cap_amount is None:
            raise ValueError("cap_amount is required when cap_type is 'amount'")
        if self.cap_type == FeeCapType.percentage and self.cap_percentage is None:
            raise ValueError("cap_percentage is required when cap_type is 'percentage'")

        return self

    @field_serializer("flat_percentage", "cap_amount", "cap_percentage")
    def serialize_decimal(self, v: Optional[Decimal]) -> Optional[str]:
        return f"{v:.4f}" if v is not None else None


# ── Firm-wide fee config ───────────────────────────────────────────────────────

class FirmFeeConfigRequest(BaseModel):
    """Payload to create or update the firm-wide fee configuration."""
    config:         FeeConfigData
    effective_date: Optional[datetime] = Field(
        None, description="When this config takes effect. Defaults to now."
    )
    notes:          Optional[str]      = Field(None, max_length=1000)
    updated_by:     str                = Field(default="")


class FirmFeeConfig(BaseModel):
    """
    Current firm-wide fee configuration.
    Stored at firm_settings/fee_config.
    """
    config_id:      str
    config:         FeeConfigData
    effective_date: datetime
    notes:          Optional[str] = None
    updated_by:     str
    updated_at:     datetime


# ── Audit trail ────────────────────────────────────────────────────────────────

class FeeConfigAuditEntry(BaseModel):
    """
    One entry in the fee configuration audit log.
    Stored at firm_settings/fee_config/audit/{uuid}.
    """
    audit_id:        str
    changed_at:      datetime
    changed_by:      str
    previous_config: Optional[FeeConfigData] = None
    new_config:      FeeConfigData
    notes:           Optional[str]           = None


class FeeConfigAuditResponse(BaseModel):
    total:   int
    entries: List[FeeConfigAuditEntry]


# ── Per-case override ──────────────────────────────────────────────────────────

class CaseFeeOverrideRequest(BaseModel):
    """Payload to set or update a per-case fee override."""
    config:  FeeConfigData
    reason:  str = Field(..., min_length=1, max_length=500,
                         description="Business reason for overriding the firm default.")
    set_by:  str = Field(default="")


class CaseFeeOverride(BaseModel):
    """
    Per-case fee override.
    Stored at cases/{caseId}/settlement/fee_override.
    """
    case_id: str
    config:  FeeConfigData
    reason:  str
    set_by:  str
    set_at:  datetime


# ── Fee calculation detail ─────────────────────────────────────────────────────

class TierBreakdown(BaseModel):
    """Contribution of one tier to the total fee."""
    description:   str
    award_portion: Decimal
    percentage:    Decimal
    fee_amount:    Decimal

    @field_serializer("award_portion", "fee_amount")
    def serialize_money(self, v: Decimal) -> str:
        return f"{v:.2f}"

    @field_serializer("percentage")
    def serialize_pct(self, v: Decimal) -> str:
        return f"{v:.4f}"


class FeeCalculationDetail(BaseModel):
    """
    Full detail of an attorney fee calculation.
    Returned by the preview/calculate endpoints.
    """
    gross_award:          Decimal
    fee_amount:           Decimal
    effective_percentage: Decimal
    structure_used:       str              # "firm_default" | "case_override" | "manual"
    structure_type:       FeeStructureType
    tier_breakdown:       List[TierBreakdown]
    capped:               bool
    cap_applied:          Optional[Decimal] = None

    @field_serializer("gross_award", "fee_amount")
    def serialize_money(self, v: Decimal) -> str:
        return f"{v:.2f}"

    @field_serializer("effective_percentage")
    def serialize_pct(self, v: Decimal) -> str:
        return f"{v:.4f}"

    @field_serializer("cap_applied")
    def serialize_cap(self, v: Optional[Decimal]) -> Optional[str]:
        return f"{v:.2f}" if v is not None else None


class FeePreviewRequest(BaseModel):
    """Payload for the ad-hoc fee preview endpoint."""
    gross_award: Decimal = Field(..., gt=Decimal("0"), description="Gross settlement award in USD")
    config:      Optional[FeeConfigData] = Field(
        None,
        description="Fee config to use. If omitted, the firm default is used."
    )

    @field_validator("gross_award", mode="before")
    @classmethod
    def coerce_decimal(cls, v):
        try:
            return Decimal(str(v))
        except Exception:
            raise ValueError("value must be a valid decimal number")
