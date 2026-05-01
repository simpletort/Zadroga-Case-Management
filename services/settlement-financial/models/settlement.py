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
from collections import defaultdict


# ── Enums ──────────────────────────────────────────────────────────────────────

class ExpenseCategory(str, Enum):
    filing_fee      = "Filing Fee"
    medical_records = "Medical Records"
    expert_witness  = "Expert Witness"
    travel          = "Travel"
    postage         = "Postage"
    other           = "Other"

# All built-in category values — used for API validation
BUILT_IN_EXPENSE_CATEGORIES: set[str] = {e.value for e in ExpenseCategory}


class ExpensePaidStatus(str, Enum):
    pending = "Pending"
    paid    = "Paid"


class LienType(str, Enum):
    medical    = "Medical"     # Medicare, Medicaid, health insurance
    government = "Government"  # IRS, state tax, workers' comp
    private    = "Private"     # private insurer, attorney fee lien


class LienSatisfactionStatus(str, Enum):
    outstanding  = "Outstanding"
    negotiating  = "Negotiating"
    satisfied    = "Satisfied"
    waived       = "Waived"


class LienClaimStatus(str, Enum):
    claimed  = "Claimed"   # asserted but not yet verified
    verified = "Verified"  # amount confirmed
    disputed = "Disputed"  # validity or amount is contested
    paid     = "Paid"      # fully paid off


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

class ExpenseChangeEntry(BaseModel):
    """One audit-trail record written every time an expense is modified."""
    changed_at: datetime
    changed_by: str
    changes:    dict   # e.g. {"amount": {"from": "500.00", "to": "750.00"}}


class ExpenseRequest(BaseModel):
    """Payload for adding a new case expense."""
    description: str              = Field(..., min_length=1, max_length=500)
    amount:      Decimal          = Field(..., gt=Decimal("0"), description="Amount in USD")
    category:    ExpenseCategory
    vendor:      Optional[str]    = Field(None, max_length=300, description="Vendor / payee name")
    date:        datetime         = Field(..., description="Expense date")
    paid_status: ExpensePaidStatus = ExpensePaidStatus.pending
    added_by:    str              = Field(default="", description="UID of staff who added")

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


class ExpenseUpdateRequest(BaseModel):
    """Payload for editing an existing expense. All fields optional."""
    description: Optional[str]              = Field(None, min_length=1, max_length=500)
    amount:      Optional[Decimal]          = Field(None, gt=Decimal("0"))
    category:    Optional[ExpenseCategory]  = None
    vendor:      Optional[str]              = Field(None, max_length=300)
    date:        Optional[datetime]         = None
    paid_status: Optional[ExpensePaidStatus] = None
    updated_by:  str                        = Field(default="")

    @field_validator("amount", mode="before")
    @classmethod
    def coerce_amount(cls, v):
        if v is None:
            return v
        try:
            return Decimal(str(v))
        except Exception:
            raise ValueError("amount must be a valid decimal number")


class ExpenseReceiptRequest(BaseModel):
    """Payload for attaching a receipt to an expense."""
    receipt_url:      str = Field(..., min_length=1, description="GCS / Firebase Storage URL")
    receipt_filename: str = Field(..., min_length=1, max_length=500, description="Original file name")


class Expense(BaseModel):
    """A case expense stored in cases/{caseId}/settlement/expenses (items array)."""
    expense_id:       str
    case_id:          str
    description:      str
    amount:           Decimal
    category:         str
    vendor:           Optional[str]           = None
    date:             datetime
    paid_status:      ExpensePaidStatus        = ExpensePaidStatus.pending
    added_by:         str
    added_at:         datetime
    updated_at:       Optional[datetime]       = None
    updated_by:       Optional[str]            = None
    receipt_url:      Optional[str]            = None
    receipt_filename: Optional[str]            = None
    change_log:       List[ExpenseChangeEntry] = Field(default_factory=list)
    qb_expense_id:    Optional[str]            = None
    qb_sync_status:   Optional[QBSyncStatus]   = None
    qb_synced_at:     Optional[datetime]       = None

    @field_serializer("amount")
    def serialize_amount(self, v: Decimal) -> str:
        return f"{v:.2f}"


class CategoryTotal(BaseModel):
    """Aggregate total for one expense category."""
    category: str
    count:    int
    total:    Decimal

    @field_serializer("total")
    def serialize_total(self, v: Decimal) -> str:
        return f"{v:.2f}"


class ExpenseTotals(BaseModel):
    """Summary totals computed from the full expense list."""
    total_amount:  Decimal
    total_paid:    Decimal
    total_unpaid:  Decimal
    by_category:   List[CategoryTotal]

    @field_serializer("total_amount", "total_paid", "total_unpaid")
    def serialize_money(self, v: Decimal) -> str:
        return f"{v:.2f}"


class ExpenseListResponse(BaseModel):
    case_id:  str
    total:    int
    expenses: List[Expense]
    totals:   ExpenseTotals


class ExpenseCategoriesRequest(BaseModel):
    """Admin payload to manage custom expense categories."""
    custom_categories: List[str] = Field(
        ..., description="Additional categories beyond the built-in set."
    )
    updated_by: str = Field(default="")


class ExpenseCategoriesResponse(BaseModel):
    """Full list of expense categories (built-in + admin-configured custom)."""
    built_in:       List[str]
    custom:         List[str]
    all_categories: List[str]
    updated_at:     Optional[datetime] = None
    updated_by:     Optional[str]      = None


# ── 2.6.2 Lien models ─────────────────────────────────────────────────────────

class LienRequest(BaseModel):
    """Payload for adding a new lien."""
    lienholder:          str                    = Field(..., min_length=1, max_length=300)
    amount:              Decimal                = Field(..., gt=Decimal("0"))
    lien_type:           LienType               = LienType.private
    claim_status:        LienClaimStatus         = LienClaimStatus.claimed
    satisfaction_status: LienSatisfactionStatus  = LienSatisfactionStatus.outstanding
    satisfaction_date:   Optional[datetime]     = None
    notes:               Optional[str]          = Field(None, max_length=1000)
    added_by:            str                    = Field(default="")

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
    """Payload for updating a lien — all fields optional."""
    lien_type:           Optional[LienType]              = None
    claim_status:        Optional[LienClaimStatus]        = None
    satisfaction_status: Optional[LienSatisfactionStatus] = None
    satisfaction_date:   Optional[datetime]              = None
    notes:               Optional[str]                   = None
    amount:              Optional[Decimal]               = None

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
    """A lien stored in cases/{caseId}/settlement/liens (items array)."""
    lien_id:             str
    case_id:             str
    lienholder:          str
    amount:              Decimal
    lien_type:           LienType               = LienType.private
    claim_status:        LienClaimStatus         = LienClaimStatus.claimed
    is_disputed:         bool                   = False
    satisfaction_status: LienSatisfactionStatus
    satisfaction_date:   Optional[datetime]     = None
    notes:               Optional[str]          = None
    added_by:            str
    added_at:            datetime
    updated_at:          Optional[datetime]     = None
    updated_by:          Optional[str]          = None

    @field_serializer("amount")
    def serialize_amount(self, v: Decimal) -> str:
        return f"{v:.2f}"


class LienTypeTotal(BaseModel):
    """Aggregate for one lien type."""
    lien_type: str
    count:     int
    total:     Decimal

    @field_serializer("total")
    def serialize_total(self, v: Decimal) -> str:
        return f"{v:.2f}"


class LienTotals(BaseModel):
    """Summary totals for a case's lien list."""
    total_amount:      Decimal
    total_outstanding: Decimal   # Outstanding + Negotiating
    total_disputed:    Decimal   # where claim_status == Disputed
    total_satisfied:   Decimal   # Satisfied + Waived
    disputed_count:    int
    by_type:           List[LienTypeTotal]

    @field_serializer("total_amount", "total_outstanding", "total_disputed", "total_satisfied")
    def serialize_money(self, v: Decimal) -> str:
        return f"{v:.2f}"


class LienListResponse(BaseModel):
    case_id: str
    total:   int
    liens:   List[Lien]
    totals:  LienTotals


# ── 2.6.3 Loan models ─────────────────────────────────────────────────────────

class LoanRequest(BaseModel):
    """Payload for adding a new case-advance loan."""
    lender:              str                    = Field(..., min_length=1, max_length=300)
    amount:              Decimal                = Field(..., gt=Decimal("0"), description="Principal disbursed")
    interest_rate:       Optional[Decimal]      = Field(None, ge=Decimal("0"), le=Decimal("100"),
                                                        description="Annual interest rate %")
    disbursement_date:   Optional[datetime]     = Field(None, description="Date funds were disbursed")
    payoff_amount:       Optional[Decimal]      = Field(None, gt=Decimal("0"),
                                                        description="Total amount to fully pay off (principal + interest)")
    satisfaction_status: LoanSatisfactionStatus  = LoanSatisfactionStatus.outstanding
    satisfaction_date:   Optional[datetime]     = None
    notes:               Optional[str]          = Field(None, max_length=1000)
    added_by:            str                    = Field(default="")

    @field_validator("amount", "interest_rate", "payoff_amount", mode="before")
    @classmethod
    def coerce_decimal(cls, v):
        if v is None:
            return v
        try:
            return Decimal(str(v))
        except Exception:
            raise ValueError("value must be a valid decimal number")

    @field_serializer("amount")
    def serialize_amount(self, v: Decimal) -> str:
        return f"{v:.2f}"

    @field_serializer("interest_rate")
    def serialize_rate(self, v: Optional[Decimal]) -> Optional[str]:
        return f"{v:.4f}" if v is not None else None

    @field_serializer("payoff_amount")
    def serialize_payoff(self, v: Optional[Decimal]) -> Optional[str]:
        return f"{v:.2f}" if v is not None else None


class LoanUpdateRequest(BaseModel):
    """Payload for updating a loan — all fields optional."""
    satisfaction_status: Optional[LoanSatisfactionStatus] = None
    satisfaction_date:   Optional[datetime]               = None
    amount:              Optional[Decimal]                = None
    interest_rate:       Optional[Decimal]                = Field(None, ge=Decimal("0"), le=Decimal("100"))
    disbursement_date:   Optional[datetime]               = None
    payoff_amount:       Optional[Decimal]                = Field(None, gt=Decimal("0"))
    notes:               Optional[str]                   = None

    @field_validator("amount", "interest_rate", "payoff_amount", mode="before")
    @classmethod
    def coerce_decimal(cls, v):
        if v is None:
            return v
        try:
            return Decimal(str(v))
        except Exception:
            raise ValueError("value must be a valid decimal number")


class Loan(BaseModel):
    """A loan stored in cases/{caseId}/settlement/loans (items array)."""
    loan_id:             str
    case_id:             str
    lender:              str
    amount:              Decimal
    interest_rate:       Optional[Decimal]      = None
    disbursement_date:   Optional[datetime]     = None
    payoff_amount:       Optional[Decimal]      = None
    satisfaction_status: LoanSatisfactionStatus
    satisfaction_date:   Optional[datetime]     = None
    notes:               Optional[str]          = None
    added_by:            str
    added_at:            datetime
    updated_at:          Optional[datetime]     = None
    updated_by:          Optional[str]          = None

    @field_serializer("amount")
    def serialize_amount(self, v: Decimal) -> str:
        return f"{v:.2f}"

    @field_serializer("interest_rate")
    def serialize_rate(self, v: Optional[Decimal]) -> Optional[str]:
        return f"{v:.4f}" if v is not None else None

    @field_serializer("payoff_amount")
    def serialize_payoff(self, v: Optional[Decimal]) -> Optional[str]:
        return f"{v:.2f}" if v is not None else None


class LoanTotals(BaseModel):
    """Summary totals for a case's loan list."""
    total_amount:       Decimal   # sum of all principal amounts
    total_payoff:       Decimal   # sum of payoff_amount (falls back to amount)
    outstanding_amount: Decimal   # principal still outstanding
    outstanding_payoff: Decimal   # payoff total still outstanding

    @field_serializer("total_amount", "total_payoff", "outstanding_amount", "outstanding_payoff")
    def serialize_money(self, v: Decimal) -> str:
        return f"{v:.2f}"


class LoanListResponse(BaseModel):
    case_id: str
    total:   int
    loans:   List[Loan]
    totals:  LoanTotals


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
