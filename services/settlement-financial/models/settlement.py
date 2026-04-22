"""
models/settlement.py — Pydantic models for settlement distribution calculations.

All monetary amounts are represented as Decimal for cent-accurate arithmetic.
Responses serialize amounts as strings (e.g. "12345.67") to avoid JSON float
precision loss.

Schema source: Section 2.6 Financial Sub-Collections
  2.6.1 cases/{caseId}/expenses
  2.6.2 cases/{caseId}/liens
  2.6.3 cases/{caseId}/loans
  2.6.4 cases/{caseId}/disbursements
"""
from __future__ import annotations

from decimal import Decimal
from enum import Enum
from typing import List, Optional
from datetime import datetime

from pydantic import BaseModel, Field, field_validator, field_serializer


# ── Enums ──────────────────────────────────────────────────────────────────────

class ExpenseCategory(str, Enum):
    filing_fee     = "Filing Fee"
    medical_records = "Medical Records"
    expert_witness = "Expert Witness"
    travel         = "Travel"
    other          = "Other"


class LienSatisfactionStatus(str, Enum):
    outstanding  = "Outstanding"
    negotiating  = "Negotiating"
    satisfied    = "Satisfied"
    waived       = "Waived"


class LoanSatisfactionStatus(str, Enum):
    outstanding = "Outstanding"
    satisfied   = "Satisfied"


class PayeeType(str, Enum):
    client      = "Client"
    lienholder  = "Lienholder"
    lender      = "Lender"
    firm        = "Firm"


class PaymentMethod(str, Enum):
    check = "Check"
    wire  = "Wire"
    ach   = "ACH"


class DisbursementStatus(str, Enum):
    pending = "Pending"
    paid    = "Paid"
    cleared = "Cleared"


class QBSyncStatus(str, Enum):
    pending = "Pending"
    synced  = "Synced"
    error   = "Error"


# ── 2.6.1 Expense models ───────────────────────────────────────────────────────

class ExpenseRequest(BaseModel):
    """Payload for adding a new case expense."""
    description: str          = Field(..., min_length=1, max_length=500)
    amount: Decimal           = Field(..., gt=Decimal("0"), description="Amount in USD")
    category: ExpenseCategory
    date: datetime            = Field(..., description="Expense date")
    added_by: str             = Field(default="", description="UID of staff who added")

    @field_validator("amount", mode="before")
    @classmethod
    def coerce_amount(cls, v):
        try:
            return Decimal(str(v))
        except Exception:
            raise ValueError("amount must be a valid decimal number")

    @field_serializer("amount")
    def serialize_amount(self, v: Decimal) -> str:
        return f"{v:.2f}"


class Expense(BaseModel):
    """A case expense stored in cases/{caseId}/expenses/{expenseId}."""
    expense_id:     str
    case_id:        str
    description:    str
    amount:         Decimal
    category:       ExpenseCategory
    date:           datetime
    added_by:       str
    added_at:       datetime
    qb_expense_id:  Optional[str]         = None
    qb_sync_status: Optional[QBSyncStatus] = None
    qb_synced_at:   Optional[datetime]    = None

    @field_serializer("amount")
    def serialize_amount(self, v: Decimal) -> str:
        return f"{v:.2f}"


class ExpenseListResponse(BaseModel):
    case_id:  str
    total:    int
    expenses: List[Expense]


# ── 2.6.2 Lien models ─────────────────────────────────────────────────────────

class LienRequest(BaseModel):
    """Payload for adding a new lien."""
    lienholder:          str                   = Field(..., min_length=1, max_length=300)
    amount:              Decimal               = Field(..., gt=Decimal("0"))
    satisfaction_status: LienSatisfactionStatus = LienSatisfactionStatus.outstanding
    satisfaction_date:   Optional[datetime]    = None
    notes:               Optional[str]         = Field(None, max_length=1000)
    added_by:            str                   = Field(default="")

    @field_validator("amount", mode="before")
    @classmethod
    def coerce_amount(cls, v):
        try:
            return Decimal(str(v))
        except Exception:
            raise ValueError("amount must be a valid decimal number")

    @field_serializer("amount")
    def serialize_amount(self, v: Decimal) -> str:
        return f"{v:.2f}"


class LienUpdateRequest(BaseModel):
    """Payload for updating lien satisfaction status."""
    satisfaction_status: Optional[LienSatisfactionStatus] = None
    satisfaction_date:   Optional[datetime]               = None
    notes:               Optional[str]                    = None
    amount:              Optional[Decimal]                = None

    @field_validator("amount", mode="before")
    @classmethod
    def coerce_amount(cls, v):
        if v is None:
            return v
        try:
            return Decimal(str(v))
        except Exception:
            raise ValueError("amount must be a valid decimal number")


class Lien(BaseModel):
    """A lien stored in cases/{caseId}/liens/{lienId}."""
    lien_id:             str
    case_id:             str
    lienholder:          str
    amount:              Decimal
    satisfaction_status: LienSatisfactionStatus
    satisfaction_date:   Optional[datetime] = None
    notes:               Optional[str]      = None
    added_by:            str
    added_at:            datetime

    @field_serializer("amount")
    def serialize_amount(self, v: Decimal) -> str:
        return f"{v:.2f}"


class LienListResponse(BaseModel):
    case_id: str
    total:   int
    liens:   List[Lien]


# ── 2.6.3 Loan models ─────────────────────────────────────────────────────────

class LoanRequest(BaseModel):
    """Payload for adding a new case-advance loan."""
    lender:              str                   = Field(..., min_length=1, max_length=300)
    amount:              Decimal               = Field(..., gt=Decimal("0"))
    satisfaction_status: LoanSatisfactionStatus = LoanSatisfactionStatus.outstanding
    satisfaction_date:   Optional[datetime]    = None
    added_by:            str                   = Field(default="")

    @field_validator("amount", mode="before")
    @classmethod
    def coerce_amount(cls, v):
        try:
            return Decimal(str(v))
        except Exception:
            raise ValueError("amount must be a valid decimal number")

    @field_serializer("amount")
    def serialize_amount(self, v: Decimal) -> str:
        return f"{v:.2f}"


class LoanUpdateRequest(BaseModel):
    """Payload for updating loan satisfaction status."""
    satisfaction_status: Optional[LoanSatisfactionStatus] = None
    satisfaction_date:   Optional[datetime]               = None
    amount:              Optional[Decimal]                = None

    @field_validator("amount", mode="before")
    @classmethod
    def coerce_amount(cls, v):
        if v is None:
            return v
        try:
            return Decimal(str(v))
        except Exception:
            raise ValueError("amount must be a valid decimal number")


class Loan(BaseModel):
    """A loan stored in cases/{caseId}/loans/{loanId}."""
    loan_id:             str
    case_id:             str
    lender:              str
    amount:              Decimal
    satisfaction_status: LoanSatisfactionStatus
    satisfaction_date:   Optional[datetime] = None
    added_by:            str
    added_at:            datetime

    @field_serializer("amount")
    def serialize_amount(self, v: Decimal) -> str:
        return f"{v:.2f}"


class LoanListResponse(BaseModel):
    case_id: str
    total:   int
    loans:   List[Loan]


# ── 2.6.4 Disbursement models ─────────────────────────────────────────────────

class DisbursementRequest(BaseModel):
    """Payload for adding a disbursement record."""
    payee:            str               = Field(..., min_length=1, max_length=300)
    payee_type:       PayeeType
    amount:           Decimal           = Field(..., gt=Decimal("0"))
    date:             datetime
    method:           Optional[PaymentMethod]   = None
    reference_number: Optional[str]             = None
    status:           DisbursementStatus        = DisbursementStatus.pending
    processed_by:     str                       = Field(default="")

    @field_validator("amount", mode="before")
    @classmethod
    def coerce_amount(cls, v):
        try:
            return Decimal(str(v))
        except Exception:
            raise ValueError("amount must be a valid decimal number")

    @field_serializer("amount")
    def serialize_amount(self, v: Decimal) -> str:
        return f"{v:.2f}"


class Disbursement(BaseModel):
    """A disbursement stored in cases/{caseId}/disbursements/{disbursementId}."""
    disbursement_id:  str
    case_id:          str
    payee:            str
    payee_type:       PayeeType
    amount:           Decimal
    date:             datetime
    method:           Optional[PaymentMethod]   = None
    reference_number: Optional[str]             = None
    status:           DisbursementStatus
    qb_payment_id:    Optional[str]             = None
    qb_sync_status:   Optional[QBSyncStatus]    = None
    processed_by:     str
    processed_at:     datetime

    @field_serializer("amount")
    def serialize_amount(self, v: Decimal) -> str:
        return f"{v:.2f}"


class DisbursementListResponse(BaseModel):
    case_id:       str
    total:         int
    disbursements: List[Disbursement]


# ── Case settlement inputs ─────────────────────────────────────────────────────
# Stored at cases/{caseId}/settlement/inputs
# Only gross_award and attorney_fee_pct — expenses/liens/loans live in
# their own subcollections (2.6.1–2.6.3).

class CaseSettlementInputs(BaseModel):
    """
    All settlement calculator inputs stored for a case.
    Stored at cases/{caseId}/settlement/inputs.
    """
    case_id:          str
    gross_award:      str
    attorney_fee_pct: str
    case_expenses:    List[LineItem] = Field(default_factory=list)
    liens:            List[LineItem] = Field(default_factory=list)
    client_loans:     List[LineItem] = Field(default_factory=list)
    notes:            Optional[str]      = None
    updated_at:       Optional[datetime] = None


class CaseSettlementInputsRequest(BaseModel):
    """Payload for saving all settlement inputs for a case."""
    gross_award:      Decimal        = Field(..., gt=Decimal("0"), description="Gross settlement award in USD")
    attorney_fee_pct: Decimal        = Field(..., ge=Decimal("0"), le=Decimal("100"), description="Attorney fee percentage")
    case_expenses:    List[LineItem] = Field(default_factory=list, description="Itemized case expenses")
    liens:            List[LineItem] = Field(default_factory=list, description="Itemized liens")
    client_loans:     List[LineItem] = Field(default_factory=list, description="Itemized client loans / case advances")
    notes:            Optional[str]  = Field(None, max_length=1000)

    @field_validator("gross_award", "attorney_fee_pct", mode="before")
    @classmethod
    def coerce_decimal(cls, v):
        try:
            return Decimal(str(v))
        except Exception:
            raise ValueError("value must be a valid decimal number")

    @field_serializer("gross_award", "attorney_fee_pct")
    def serialize_decimal(self, v: Decimal) -> str:
        return f"{v:.2f}"


# ── Calculation models (preview + manual save) ────────────────────────────────

class LineItem(BaseModel):
    """A single expense, lien, or loan line item (used for preview endpoint)."""
    description: str     = Field(..., min_length=1, max_length=200, examples=["Medical records fee"])
    amount:      Decimal = Field(..., gt=Decimal("0"), examples=["1250.00"])

    @field_validator("amount", mode="before")
    @classmethod
    def coerce_amount(cls, v):
        try:
            return Decimal(str(v))
        except Exception:
            raise ValueError("amount must be a valid decimal number")

    @field_serializer("amount")
    def serialize_amount(self, v: Decimal) -> str:
        return f"{v:.2f}"


class CalculationRequest(BaseModel):
    """Inputs for a manual / preview settlement calculation."""
    gross_award:      Decimal         = Field(..., gt=Decimal("0"))
    attorney_fee_pct: Decimal         = Field(..., ge=Decimal("0"), le=Decimal("100"))
    case_expenses:    List[LineItem]  = Field(default_factory=list)
    liens:            List[LineItem]  = Field(default_factory=list)
    client_loans:     List[LineItem]  = Field(default_factory=list)
    notes:            Optional[str]   = Field(None, max_length=1000)

    @field_validator("gross_award", "attorney_fee_pct", mode="before")
    @classmethod
    def coerce_decimal(cls, v):
        try:
            return Decimal(str(v))
        except Exception:
            raise ValueError("value must be a valid decimal number")

    @field_serializer("gross_award", "attorney_fee_pct")
    def serialize_decimal(self, v: Decimal) -> str:
        return f"{v:.2f}"


class CalculationResult(BaseModel):
    """
    Computed breakdown of how the gross award is distributed.

    Formula
    -------
    attorney_fee_amount  = gross_award × (attorney_fee_pct / 100)
    total_expenses       = sum(case_expenses)
    total_liens          = sum(outstanding + negotiating liens)
    total_loans          = sum(outstanding loans)
    total_deductions     = attorney_fee_amount + total_expenses + total_liens + total_loans
    net_to_client        = gross_award − total_deductions
    """
    attorney_fee_amount: Decimal
    total_expenses:      Decimal
    total_liens:         Decimal
    total_loans:         Decimal
    total_deductions:    Decimal
    net_to_client:       Decimal

    @field_serializer("attorney_fee_amount", "total_expenses", "total_liens",
                      "total_loans", "total_deductions", "net_to_client")
    def serialize_money(self, v: Decimal) -> str:
        return f"{v:.2f}"


class CalculationPreviewResponse(BaseModel):
    """Response for the preview (not saved) endpoint."""
    gross_award:      str
    attorney_fee_pct: str
    case_expenses:    List[LineItem]
    liens:            List[LineItem]
    client_loans:     List[LineItem]
    result:           CalculationResult
    notes:            Optional[str] = None


class SavedCalculation(BaseModel):
    """A calculation persisted to cases/{caseId}/settlement/{uuid}."""
    calculation_id:   str
    case_id:          str
    created_at:       datetime
    created_by:       str
    gross_award:      str
    attorney_fee_pct: str
    case_expenses:    List[LineItem]
    liens:            List[LineItem]
    client_loans:     List[LineItem]
    notes:            Optional[str] = None
    result:           CalculationResult


class CalculationHistoryResponse(BaseModel):
    """Paginated list of saved calculations for a case."""
    case_id:      str
    total:        int
    calculations: List[SavedCalculation]
