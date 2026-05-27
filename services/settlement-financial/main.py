"""
main.py — FastAPI application for the Settlement Financial Service.

Schema: Section 2.6 Financial Sub-Collections
  cases/{caseId}/expenses/{expenseId}
  cases/{caseId}/liens/{lienId}
  cases/{caseId}/loans/{loanId}
  cases/{caseId}/disbursements/{disbursementId}
  cases/{caseId}/settlement/inputs        ← gross_award + attorney_fee_pct
  cases/{caseId}/settlement/{uuid}        ← saved calculation results

Endpoints
---------
Settlement Calculator
  POST /api/v1/settlement/calculate
      Preview a distribution without saving.

  POST /api/v1/settlement/cases/{case_id}/calculations
      Calculate + save (body required).

  GET  /api/v1/settlement/cases/{case_id}/calculations
      Full calculation history (newest first).

  GET  /api/v1/settlement/cases/{case_id}/calculations/latest
      Most recent saved calculation.

  GET  /api/v1/settlement/cases/{case_id}/calculations/{calculation_id}
      Single saved calculation by ID.

  DELETE /api/v1/settlement/cases/{case_id}/calculations/{calculation_id}
      Delete a saved calculation.

Expenses (2.6.1)
  POST   /api/v1/settlement/cases/{case_id}/expenses
  GET    /api/v1/settlement/cases/{case_id}/expenses
  DELETE /api/v1/settlement/cases/{case_id}/expenses/{expense_id}

Liens (2.6.2)
  POST   /api/v1/settlement/cases/{case_id}/liens
  GET    /api/v1/settlement/cases/{case_id}/liens
  PATCH  /api/v1/settlement/cases/{case_id}/liens/{lien_id}
  DELETE /api/v1/settlement/cases/{case_id}/liens/{lien_id}

Loans (2.6.3)
  POST   /api/v1/settlement/cases/{case_id}/loans
  GET    /api/v1/settlement/cases/{case_id}/loans
  PATCH  /api/v1/settlement/cases/{case_id}/loans/{loan_id}
  DELETE /api/v1/settlement/cases/{case_id}/loans/{loan_id}

Disbursements (2.6.4)
  POST /api/v1/settlement/cases/{case_id}/disbursements
  GET  /api/v1/settlement/cases/{case_id}/disbursements

Statement PDF
  POST /api/v1/settlement/cases/{case_id}/statement/generate
      Generate & upload a settlement statement PDF; returns signed URL.

GET /health
"""
from __future__ import annotations

import asyncio
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from decimal import Decimal
from typing import List, Optional

from fastapi import FastAPI, File, Form, HTTPException, Path, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from google.cloud import firestore as _fs
from shared.middlewares import (
    AuthMiddleware,
    ErrorHandlerMiddleware,
    LoggingMiddleware,
    get_cors_origins,
)

from config import get_settings
from logging_config import get_logger, setup_logging
from models.settlement import (
    BUILT_IN_EXPENSE_CATEGORIES,
    CalculationHistoryResponse,
    CalculationPreviewResponse,
    CalculationRequest,
    CaseSettlementInputs,
    CaseSettlementInputsRequest,
    CategoryTotal,
    Disbursement,
    DisbursementListResponse,
    DisbursementRequest,
    Expense,
    ExpenseCategoriesRequest,
    ExpenseCategoriesResponse,
    ExpenseChangeEntry,
    ExpenseListResponse,
    ExpensePaidStatus,
    ExpenseReceiptRequest,
    ExpenseTotals,
    ExpenseRequest,
    ExpenseUpdateRequest,
    Lien,
    LienClaimStatus,
    LienListResponse,
    LienRequest,
    LienTotals,
    LienTypeTotal,
    LienUpdateRequest,
    Loan,
    LoanListResponse,
    LoanRequest,
    LoanSatisfactionStatus,
    LoanTotals,
    LoanUpdateRequest,
    SavedCalculation,
)
from models.fee_config import (
    CaseFeeOverride,
    CaseFeeOverrideRequest,
    FeeCalculationDetail,
    FeeConfigAuditEntry,
    FeeConfigAuditResponse,
    FeeConfigData,
    FeePreviewRequest,
    FirmFeeConfig,
    FirmFeeConfigRequest,
)
from services.calculator import run_calculation
from services.fee_calculator import calculate_attorney_fee
from services.firestore_client import get_db
from services.pdf_service import build_and_upload_statement
from services.storage_service import (
    delete_case_file,
    get_signed_url,
    list_case_files,
    stream_case_file,
    upload_case_file,
)
from models.statement import StatementGenerateRequest, StatementGenerateResponse
from models.storage import CaseFileType, FileListResponse, FileUploadResponse, SignedUrlResponse

logger = get_logger(__name__)

# Single settlement subcollection — inputs doc + calculation docs
_SETTLEMENT_SUB = "settlement"
_INPUTS_DOC     = "inputs"

# Documents inside settlement/ that are NOT saved calculations
_SETTLEMENT_RESERVED = {"inputs", "expenses", "liens", "loans", "disbursements", "fee_override"}

def _is_reserved(doc_id: str) -> bool:
    """Return True for any doc that is not a saved calculation UUID."""
    return doc_id in _SETTLEMENT_RESERVED or doc_id.startswith("statement_")


# ── Firestore reference helpers ───────────────────────────────────────────────

def _settlement_ref(db, case_id: str):
    return db.collection("cases").document(case_id).collection(_SETTLEMENT_SUB)

def _calcs_ref(db, case_id: str):
    return _settlement_ref(db, case_id)

def _inputs_ref(db, case_id: str):
    return _settlement_ref(db, case_id).document(_INPUTS_DOC)

def _expenses_ref(db, case_id: str):
    return _settlement_ref(db, case_id).document("expenses")

def _liens_ref(db, case_id: str):
    return _settlement_ref(db, case_id).document("liens")

def _loans_ref(db, case_id: str):
    return _settlement_ref(db, case_id).document("loans")

def _disbursements_ref(db, case_id: str):
    return _settlement_ref(db, case_id).document("disbursements")

def _case_fee_override_ref(db, case_id: str):
    return _settlement_ref(db, case_id).document("fee_override")

def _firm_fee_config_ref(db):
    return db.collection("firmSettings").document("fee_config")

def _fee_audit_ref(db):
    return db.collection("firmSettings").document("fee_config").collection("audit")

def _expense_categories_ref(db):
    return db.collection("firmSettings").document("expense_categories")


# ── Lifespan ──────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    settings = get_settings()
    logger.info("settlement_service_starting", env=settings.app_env, project=settings.gcp_project_id)
    get_db()
    yield
    logger.info("settlement_service_shutdown")


# ── Route → permission map (used by AuthMiddleware) ───────────────────────────

_ROUTE_PERMISSIONS: list[tuple[str, str, str]] = [
    # Settlement preview
    ("POST",   r"^/api/v1/settlement/calculate$",                                    "settlement.read"),
    # Case inputs
    ("PUT",    r"^/api/v1/settlement/cases/[^/]+/inputs$",                           "settlement.write"),
    ("GET",    r"^/api/v1/settlement/cases/[^/]+/inputs$",                           "settlement.read"),
    ("POST",   r"^/api/v1/settlement/cases/[^/]+/calculate$",                        "settlement.write"),
    # Calculations
    ("POST",   r"^/api/v1/settlement/cases/[^/]+/calculations$",                     "settlement.write"),
    ("GET",    r"^/api/v1/settlement/cases/[^/]+/calculations",                      "settlement.read"),
    ("DELETE", r"^/api/v1/settlement/cases/[^/]+/calculations/[^/]+$",               "settlement.delete"),
    # Expenses
    ("POST",   r"^/api/v1/settlement/cases/[^/]+/expenses$",                         "settlement.write"),
    ("GET",    r"^/api/v1/settlement/cases/[^/]+/expenses$",                         "settlement.read"),
    ("PATCH",  r"^/api/v1/settlement/cases/[^/]+/expenses/[^/]+$",                   "settlement.write"),
    ("DELETE", r"^/api/v1/settlement/cases/[^/]+/expenses/[^/]+$",                   "settlement.delete"),
    ("PUT",    r"^/api/v1/settlement/cases/[^/]+/expenses/[^/]+/receipt$",           "settlement.write"),
    ("DELETE", r"^/api/v1/settlement/cases/[^/]+/expenses/[^/]+/receipt$",           "settlement.delete"),
    # Liens
    ("POST",   r"^/api/v1/settlement/cases/[^/]+/liens$",                            "settlement.write"),
    ("GET",    r"^/api/v1/settlement/cases/[^/]+/liens$",                            "settlement.read"),
    ("PATCH",  r"^/api/v1/settlement/cases/[^/]+/liens/[^/]+$",                      "settlement.write"),
    ("DELETE", r"^/api/v1/settlement/cases/[^/]+/liens/[^/]+$",                      "settlement.delete"),
    # Loans
    ("POST",   r"^/api/v1/settlement/cases/[^/]+/loans$",                            "settlement.write"),
    ("GET",    r"^/api/v1/settlement/cases/[^/]+/loans$",                            "settlement.read"),
    ("PATCH",  r"^/api/v1/settlement/cases/[^/]+/loans/[^/]+$",                      "settlement.write"),
    ("DELETE", r"^/api/v1/settlement/cases/[^/]+/loans/[^/]+$",                      "settlement.delete"),
    # Disbursements
    ("POST",   r"^/api/v1/settlement/cases/[^/]+/disbursements$",                    "settlement.write"),
    ("GET",    r"^/api/v1/settlement/cases/[^/]+/disbursements$",                    "settlement.read"),
    # Fee configuration
    ("GET",    r"^/api/v1/fee-config",                                               "feeConfig.read"),
    ("PUT",    r"^/api/v1/fee-config$",                                              "feeConfig.write"),
    ("POST",   r"^/api/v1/fee-config/calculate$",                                    "settlement.read"),
    ("GET",    r"^/api/v1/settlement/cases/[^/]+/fee-override$",                     "feeConfig.read"),
    ("PUT",    r"^/api/v1/settlement/cases/[^/]+/fee-override$",                     "feeConfig.write"),
    ("DELETE", r"^/api/v1/settlement/cases/[^/]+/fee-override$",                     "feeConfig.write"),
    ("POST",   r"^/api/v1/settlement/cases/[^/]+/fee-config/calculate$",             "settlement.read"),
    # Expense categories (admin)
    ("GET",    r"^/api/v1/admin/expense-categories$",                                "feeConfig.read"),
    ("PUT",    r"^/api/v1/admin/expense-categories$",                                "feeConfig.write"),
    # Statement PDF
    ("POST",   r"^/api/v1/settlement/cases/[^/]+/statement/generate$",              "settlement.approve"),
    ("GET",    r"^/api/v1/settlement/cases/[^/]+/statement/[^/]+/download$",        "settlement.read"),
    # File storage
    ("POST",   r"^/api/v1/settlement/cases/[^/]+/files$",                           "storage.write"),
    ("GET",    r"^/api/v1/settlement/cases/[^/]+/files$",                           "storage.read"),
    ("DELETE", r"^/api/v1/settlement/cases/[^/]+/files/[^/]+$",                     "storage.delete"),
    ("GET",    r"^/api/v1/settlement/cases/[^/]+/files/[^/]+/download$",            "storage.read"),
    ("GET",    r"^/api/v1/settlement/cases/[^/]+/files/[^/]+/url$",                 "storage.read"),
]


# ── App ───────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="ZAD Settlement Financial Service",
    version="1.0.0",
    description=(
        "REST API for settlement distribution calculations. "
        "Expenses, liens, loans and disbursements stored as proper Firestore subcollections "
        "under cases/{caseId} per schema sections 2.6.1–2.6.4."
    ),
    openapi_url="/openapi.json",
    docs_url="/docs",
    lifespan=lifespan,
    swagger_ui_init_oauth={},
    openapi_tags=[],
)

# Bearer token security scheme — enables the Authorize button in Swagger UI
from fastapi.openapi.utils import get_openapi

def _custom_openapi():
    if app.openapi_schema:
        return app.openapi_schema
    schema = get_openapi(
        title=app.title,
        version=app.version,
        description=app.description,
        routes=app.routes,
    )
    schema.setdefault("components", {})
    schema["components"]["securitySchemes"] = {
        "BearerAuth": {"type": "http", "scheme": "bearer"}
    }
    schema["security"] = [{"BearerAuth": []}]
    app.openapi_schema = schema
    return schema

app.openapi = _custom_openapi

_settings = get_settings()

app.add_middleware(ErrorHandlerMiddleware)
app.add_middleware(LoggingMiddleware)
if not _settings.is_development:
    app.add_middleware(
        AuthMiddleware,
        route_permissions=_ROUTE_PERMISSIONS,
        roles_firestore_project=_settings.gcp_project_id,
        roles_firestore_database=_settings.roles_firestore_database_id,
        trusted_service_accounts=[
            e.strip() for e in _settings.trusted_service_accounts.split(",") if e.strip()
        ],
        skip_paths=["/health", "/docs", "/openapi.json", "/redoc"],
    )
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_cors_origins(_settings.environment),
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers=["Authorization", "Content-Type", "x-apigateway-api-userinfo"],
)


# ── Timestamp helper ──────────────────────────────────────────────────────────

def _to_dt(val) -> Optional[datetime]:
    if val is None:
        return None
    if hasattr(val, "timestamp"):
        return datetime.fromtimestamp(val.timestamp(), tz=timezone.utc)
    if isinstance(val, datetime):
        return val
    return None


# ── Firestore doc converters ──────────────────────────────────────────────────

def _doc_to_expense(doc_id: str, data: dict) -> Expense:
    from models.settlement import ExpensePaidStatus, QBSyncStatus
    raw_log = data.get("changeLog", [])
    change_log = [
        ExpenseChangeEntry(
            changed_at=_to_dt(e.get("changedAt")) or datetime.now(tz=timezone.utc),
            changed_by=e.get("changedBy", ""),
            changes=e.get("changes", {}),
        )
        for e in raw_log
    ]
    return Expense(
        expense_id       = doc_id,
        case_id          = data["caseId"],
        description      = data["description"],
        amount           = Decimal(str(data["amount"])),
        category         = data["category"],
        vendor           = data.get("vendor"),
        date             = _to_dt(data.get("date")) or datetime.now(tz=timezone.utc),
        paid_status      = ExpensePaidStatus(data.get("paidStatus", "Pending")),
        added_by         = data.get("addedBy", ""),
        added_at         = _to_dt(data.get("addedAt")) or datetime.now(tz=timezone.utc),
        updated_at       = _to_dt(data.get("updatedAt")),
        updated_by       = data.get("updatedBy"),
        receipt_url      = data.get("receiptUrl"),
        receipt_filename = data.get("receiptFilename"),
        change_log       = change_log,
        qb_expense_id    = data.get("qbExpenseId"),
        qb_sync_status   = QBSyncStatus(data["qbSyncStatus"]) if data.get("qbSyncStatus") else None,
        qb_synced_at     = _to_dt(data.get("qbSyncedAt")),
    )


def _doc_to_lien(doc_id: str, data: dict) -> Lien:
    from models.settlement import LienSatisfactionStatus, LienType, LienClaimStatus
    claim_status = LienClaimStatus(data.get("claimStatus", "Claimed"))
    return Lien(
        lien_id             = doc_id,
        case_id             = data["caseId"],
        lienholder          = data["lienholder"],
        amount              = Decimal(str(data["amount"])),
        lien_type           = LienType(data.get("lienType", "Private")),
        claim_status        = claim_status,
        is_disputed         = claim_status == LienClaimStatus.disputed,
        satisfaction_status = LienSatisfactionStatus(data["satisfactionStatus"]),
        satisfaction_date   = _to_dt(data.get("satisfactionDate")),
        notes               = data.get("notes"),
        added_by            = data.get("addedBy", ""),
        added_at            = _to_dt(data.get("addedAt")) or datetime.now(tz=timezone.utc),
        updated_at          = _to_dt(data.get("updatedAt")),
        updated_by          = data.get("updatedBy"),
    )


def _doc_to_loan(doc_id: str, data: dict) -> Loan:
    from models.settlement import LoanSatisfactionStatus
    return Loan(
        loan_id             = doc_id,
        case_id             = data["caseId"],
        lender              = data["lender"],
        amount              = Decimal(str(data["amount"])),
        interest_rate       = Decimal(str(data["interestRate"])) if data.get("interestRate") is not None else None,
        disbursement_date   = _to_dt(data.get("disbursementDate")),
        payoff_amount       = Decimal(str(data["payoffAmount"])) if data.get("payoffAmount") is not None else None,
        satisfaction_status = LoanSatisfactionStatus(data["satisfactionStatus"]),
        satisfaction_date   = _to_dt(data.get("satisfactionDate")),
        notes               = data.get("notes"),
        added_by            = data.get("addedBy", ""),
        added_at            = _to_dt(data.get("addedAt")) or datetime.now(tz=timezone.utc),
        updated_at          = _to_dt(data.get("updatedAt")),
        updated_by          = data.get("updatedBy"),
    )


def _doc_to_disbursement(doc_id: str, data: dict) -> Disbursement:
    from models.settlement import DisbursementStatus, PayeeType, PaymentMethod, QBSyncStatus
    return Disbursement(
        disbursement_id=doc_id,
        case_id=data["caseId"],
        payee=data["payee"],
        payee_type=PayeeType(data["payeeType"]),
        amount=Decimal(str(data["amount"])),
        date=_to_dt(data.get("date")) or datetime.now(tz=timezone.utc),
        method=PaymentMethod(data["method"]) if data.get("method") else None,
        reference_number=data.get("referenceNumber"),
        status=DisbursementStatus(data["status"]),
        qb_payment_id=data.get("qbPaymentId"),
        qb_sync_status=QBSyncStatus(data["qbSyncStatus"]) if data.get("qbSyncStatus") else None,
        processed_by=data.get("processedBy", ""),
        processed_at=_to_dt(data.get("processedAt")) or datetime.now(tz=timezone.utc),
    )


def _doc_to_inputs(case_id: str, data: dict) -> CaseSettlementInputs:
    from models.settlement import LineItem

    def _items(raw: list) -> list:
        return [LineItem(description=i["description"], amount=Decimal(i["amount"])) for i in (raw or [])]

    return CaseSettlementInputs(
        case_id=case_id,
        gross_award=data["gross_award"],
        attorney_fee_pct=data["attorney_fee_pct"],
        case_expenses=_items(data.get("case_expenses", [])),
        liens=_items(data.get("liens", [])),
        client_loans=_items(data.get("client_loans", [])),
        notes=data.get("notes"),
        updated_at=_to_dt(data.get("updated_at")),
    )


def _doc_to_saved(doc_id: str, data: dict) -> SavedCalculation:
    from models.settlement import CalculationResult, LineItem

    def _items(raw: list) -> List[LineItem]:
        return [LineItem(description=i["description"], amount=Decimal(i["amount"])) for i in (raw or [])]

    result = CalculationResult(
        attorney_fee_amount=Decimal(data["attorney_fee_amount"]),
        total_expenses=Decimal(data["total_expenses"]),
        total_liens=Decimal(data["total_liens"]),
        total_loans=Decimal(data["total_loans"]),
        total_deductions=Decimal(data["total_deductions"]),
        net_to_client=Decimal(data["net_to_client"]),
    )

    return SavedCalculation(
        calculation_id=doc_id,
        case_id=data["case_id"],
        created_at=_to_dt(data.get("created_at")) or datetime.now(tz=timezone.utc),
        created_by=data.get("created_by", ""),
        gross_award=data["gross_award"],
        attorney_fee_pct=data["attorney_fee_pct"],
        case_expenses=_items(data.get("case_expenses", [])),
        liens=_items(data.get("liens", [])),
        client_loans=_items(data.get("client_loans", [])),
        notes=data.get("notes"),
        result=result,
    )


def _request_to_doc(calc_id: str, case_id: str, request: CalculationRequest, result) -> dict:
    def _items(items) -> list:
        return [{"description": i.description, "amount": f"{i.amount:.2f}"} for i in items]

    return {
        "calculation_id":    calc_id,
        "case_id":           case_id,
        "created_at":        _fs.SERVER_TIMESTAMP,
        "created_by":        "",
        "gross_award":       f"{request.gross_award:.2f}",
        "attorney_fee_pct":  f"{request.attorney_fee_pct:.2f}",
        "case_expenses":     _items(request.case_expenses),
        "liens":             _items(request.liens),
        "client_loans":      _items(request.client_loans),
        "notes":             request.notes,
        "attorney_fee_amount": f"{result.attorney_fee_amount:.2f}",
        "total_expenses":    f"{result.total_expenses:.2f}",
        "total_liens":       f"{result.total_liens:.2f}",
        "total_loans":       f"{result.total_loans:.2f}",
        "total_deductions":  f"{result.total_deductions:.2f}",
        "net_to_client":     f"{result.net_to_client:.2f}",
    }


# ═══════════════════════════════════════════════════════════════════════════════
# ROUTES
# ═══════════════════════════════════════════════════════════════════════════════

# ── Preview ───────────────────────────────────────────────────────────────────

@app.post(
    "/api/v1/settlement/calculate",
    response_model=CalculationPreviewResponse,
    status_code=status.HTTP_200_OK,
    summary="Preview settlement distribution (not saved)",
    tags=["Settlement Calculator"],
)
async def calculate_preview(request: CalculationRequest):
    """
    Compute a settlement distribution without saving.  Use for scenario testing.

    Returns **422** if total deductions exceed the gross award.
    """
    logger.info("calculate_preview_requested", gross_award=str(request.gross_award))
    try:
        result = run_calculation(request)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))

    return CalculationPreviewResponse(
        gross_award=f"{request.gross_award:.2f}",
        attorney_fee_pct=f"{request.attorney_fee_pct:.2f}",
        case_expenses=request.case_expenses,
        liens=request.liens,
        client_loans=request.client_loans,
        result=result,
        notes=request.notes,
    )


# ── Case inputs ───────────────────────────────────────────────────────────────

@app.put(
    "/api/v1/settlement/cases/{case_id}/inputs",
    response_model=CaseSettlementInputs,
    status_code=status.HTTP_200_OK,
    summary="Save gross award and attorney fee % for a case",
    tags=["Case Inputs"],
)
async def upsert_case_inputs(
    case_id: str = Path(..., description="Case ID, e.g. ZAD-2026-04-0001"),
    request: CaseSettlementInputsRequest = ...,
):
    """
    Store (or update) the gross award and attorney fee percentage for a case.
    Stored at ``cases/{caseId}/settlement/inputs``.
    """
    logger.info("upsert_case_inputs_requested", case_id=case_id)

    def _items(items) -> list:
        return [{"description": i.description, "amount": f"{i.amount:.2f}"} for i in items]

    doc_data = {
        "case_id":          case_id,
        "gross_award":      f"{request.gross_award:.2f}",
        "attorney_fee_pct": f"{request.attorney_fee_pct:.2f}",
        "case_expenses":    _items(request.case_expenses),
        "liens":            _items(request.liens),
        "client_loans":     _items(request.client_loans),
        "notes":            request.notes,
        "updated_at":       _fs.SERVER_TIMESTAMP,
    }

    db = get_db()
    await _inputs_ref(db, case_id).set(doc_data)
    logger.info("case_inputs_saved", case_id=case_id)

    snap = await _inputs_ref(db, case_id).get()
    return _doc_to_inputs(case_id, snap.to_dict())


@app.get(
    "/api/v1/settlement/cases/{case_id}/inputs",
    response_model=CaseSettlementInputs,
    status_code=status.HTTP_200_OK,
    summary="Get stored gross award and attorney fee % for a case",
    tags=["Case Inputs"],
)
async def get_case_inputs(case_id: str = Path(..., description="Case ID")):
    """Returns **404** if no inputs have been saved for this case."""
    db = get_db()
    doc = await _inputs_ref(db, case_id).get()
    if not doc.exists:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No settlement inputs found for case '{case_id}'.",
        )
    return _doc_to_inputs(case_id, doc.to_dict())


@app.post(
    "/api/v1/settlement/cases/{case_id}/calculate",
    response_model=SavedCalculation,
    status_code=status.HTTP_201_CREATED,
    summary="Auto-calculate using stored inputs",
    tags=["Case Inputs"],
)
async def calculate_from_inputs(case_id: str = Path(..., description="Case ID")):
    """
    Reads gross_award and attorney_fee_pct from ``cases/{caseId}/settlement/inputs``,
    then pulls live line items from the expenses, liens, and loans subcollection docs.

    Returns **404** if inputs have not been saved yet.
    Returns **422** if net-to-client would be negative.
    """
    from models.settlement import LineItem

    db = get_db()
    inputs_doc = await _inputs_ref(db, case_id).get()
    if not inputs_doc.exists:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No settlement inputs found for case '{case_id}'. "
                   f"Use PUT /api/v1/settlement/cases/{case_id}/inputs first.",
        )
    inputs_data = inputs_doc.to_dict()

    # Fetch live line items from the dedicated subcollection docs
    expenses_doc, liens_doc, loans_doc = await asyncio.gather(
        _expenses_ref(db, case_id).get(),
        _liens_ref(db, case_id).get(),
        _loans_ref(db, case_id).get(),
    )

    def _expense_items(raw: list) -> list:
        return [LineItem(description=i.get("description", ""), amount=Decimal(str(i["amount"]))) for i in (raw or [])]

    def _lien_items(raw: list) -> list:
        return [LineItem(description=i.get("lienholder", i.get("description", "")), amount=Decimal(str(i["amount"]))) for i in (raw or [])]

    def _loan_items(raw: list) -> list:
        return [LineItem(description=i.get("lender", i.get("description", "")), amount=Decimal(str(i["amount"]))) for i in (raw or [])]

    case_expenses = _expense_items((expenses_doc.to_dict() or {}).get("items", []) if expenses_doc.exists else [])
    liens         = _lien_items((liens_doc.to_dict() or {}).get("items", []) if liens_doc.exists else [])
    client_loans  = _loan_items((loans_doc.to_dict() or {}).get("items", []) if loans_doc.exists else [])

    calc_request = CalculationRequest(
        gross_award=Decimal(inputs_data["gross_award"]),
        attorney_fee_pct=Decimal(inputs_data["attorney_fee_pct"]),
        case_expenses=case_expenses,
        liens=liens,
        client_loans=client_loans,
        notes=inputs_data.get("notes"),
    )

    logger.info("calculate_from_inputs_requested", case_id=case_id,
                gross_award=inputs_data["gross_award"])

    try:
        result = run_calculation(calc_request)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))

    calc_id  = str(uuid.uuid4())
    doc_data = _request_to_doc(calc_id, case_id, calc_request, result)
    await _calcs_ref(db, case_id).document(calc_id).set(doc_data)
    logger.info("calculation_saved_from_inputs", calculation_id=calc_id, case_id=case_id,
                net_to_client=str(result.net_to_client))

    snap = await _calcs_ref(db, case_id).document(calc_id).get()
    return _doc_to_saved(calc_id, snap.to_dict())


# ── Calculations (manual) ─────────────────────────────────────────────────────

@app.post(
    "/api/v1/settlement/cases/{case_id}/calculations",
    response_model=SavedCalculation,
    status_code=status.HTTP_201_CREATED,
    summary="Manual calculate and save (body required)",
    tags=["Settlement Calculator"],
)
async def save_calculation(
    case_id: str = Path(..., description="Case ID"),
    request: CalculationRequest = ...,
):
    """Calculate and save with a manually supplied request body."""
    logger.info("save_calculation_requested", case_id=case_id, gross_award=str(request.gross_award))
    try:
        result = run_calculation(request)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))

    calc_id  = str(uuid.uuid4())
    doc_data = _request_to_doc(calc_id, case_id, request, result)

    db = get_db()
    await _calcs_ref(db, case_id).document(calc_id).set(doc_data)
    logger.info("calculation_saved", calculation_id=calc_id, case_id=case_id,
                net_to_client=str(result.net_to_client))

    snap = await _calcs_ref(db, case_id).document(calc_id).get()
    return _doc_to_saved(calc_id, snap.to_dict())


@app.get(
    "/api/v1/settlement/cases/{case_id}/calculations",
    response_model=CalculationHistoryResponse,
    status_code=status.HTTP_200_OK,
    summary="List all saved calculations for a case",
    tags=["Settlement Calculator"],
)
async def list_calculations(
    case_id: str = Path(..., description="Case ID"),
    limit: int = 20,
):
    limit = min(limit, 100)
    db    = get_db()

    docs = []
    async for doc in _calcs_ref(db, case_id).stream():
        if _is_reserved(doc.id):
            continue
        docs.append(_doc_to_saved(doc.id, doc.to_dict()))

    docs.sort(key=lambda d: d.created_at, reverse=True)
    total = len(docs)
    return CalculationHistoryResponse(case_id=case_id, total=total, calculations=docs[:limit])


@app.get(
    "/api/v1/settlement/cases/{case_id}/calculations/latest",
    response_model=SavedCalculation,
    status_code=status.HTTP_200_OK,
    summary="Get the most recent saved calculation for a case",
    tags=["Settlement Calculator"],
)
async def get_latest_calculation(case_id: str = Path(..., description="Case ID")):
    db   = get_db()
    docs = []
    async for doc in _calcs_ref(db, case_id).stream():
        if _is_reserved(doc.id):
            continue
        docs.append(_doc_to_saved(doc.id, doc.to_dict()))

    if not docs:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail=f"No calculations found for case '{case_id}'")

    docs.sort(key=lambda d: d.created_at, reverse=True)
    return docs[0]


@app.get(
    "/api/v1/settlement/cases/{case_id}/calculations/{calculation_id}",
    response_model=SavedCalculation,
    status_code=status.HTTP_200_OK,
    summary="Get a saved calculation by ID",
    tags=["Settlement Calculator"],
)
async def get_calculation(
    case_id:        str = Path(..., description="Case ID"),
    calculation_id: str = Path(..., description="Calculation UUID"),
):
    db  = get_db()
    doc = await _calcs_ref(db, case_id).document(calculation_id).get()
    if not doc.exists:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail=f"Calculation '{calculation_id}' not found for case '{case_id}'")
    return _doc_to_saved(doc.id, doc.to_dict())


@app.delete(
    "/api/v1/settlement/cases/{case_id}/calculations/{calculation_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a saved calculation",
    tags=["Settlement Calculator"],
)
async def delete_calculation(
    case_id:        str = Path(..., description="Case ID"),
    calculation_id: str = Path(..., description="Calculation UUID"),
):
    db      = get_db()
    doc_ref = _calcs_ref(db, case_id).document(calculation_id)
    doc     = await doc_ref.get()
    if not doc.exists:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail=f"Calculation '{calculation_id}' not found for case '{case_id}'")
    await doc_ref.delete()
    logger.info("calculation_deleted", calculation_id=calculation_id, case_id=case_id)


# ── 2.6.1 Expenses ───────────────────────────────────────────────────────────

@app.post(
    "/api/v1/settlement/cases/{case_id}/expenses",
    response_model=Expense,
    status_code=status.HTTP_201_CREATED,
    summary="Add a case expense",
    tags=["Expenses (2.6.1)"],
)
async def add_expense(
    case_id: str = Path(..., description="Case ID"),
    request: ExpenseRequest = ...,
):
    """Add an expense item to the ``settlement/expenses`` document array."""
    db         = get_db()
    expense_id = str(uuid.uuid4())
    now        = datetime.now(tz=timezone.utc)
    new_item   = {
        "expenseId":       expense_id,
        "caseId":          case_id,
        "description":     request.description,
        "amount":          float(request.amount),
        "category":        request.category.value,
        "vendor":          request.vendor,
        "date":            request.date,
        "paidStatus":      request.paid_status.value,
        "addedBy":         request.added_by,
        "addedAt":         now,
        "updatedAt":       None,
        "updatedBy":       None,
        "receiptUrl":      None,
        "receiptFilename": None,
        "changeLog":       [],
        "qbExpenseId":     None,
        "qbSyncStatus":    None,
        "qbSyncedAt":      None,
    }
    await _expenses_ref(db, case_id).set(
        {"items": _fs.ArrayUnion([new_item])}, merge=True
    )
    logger.info("expense_added", expense_id=expense_id, case_id=case_id)
    return _doc_to_expense(expense_id, new_item)


@app.get(
    "/api/v1/settlement/cases/{case_id}/expenses",
    response_model=ExpenseListResponse,
    status_code=status.HTTP_200_OK,
    summary="List all expenses for a case",
    tags=["Expenses (2.6.1)"],
)
async def list_expenses(case_id: str = Path(..., description="Case ID")):
    db   = get_db()
    snap = await _expenses_ref(db, case_id).get()
    if not snap.exists:
        empty_totals = ExpenseTotals(
            total_amount=Decimal("0"), total_paid=Decimal("0"),
            total_unpaid=Decimal("0"), by_category=[],
        )
        return ExpenseListResponse(case_id=case_id, total=0, expenses=[], totals=empty_totals)

    items    = snap.to_dict().get("items", [])
    expenses = [_doc_to_expense(i["expenseId"], i) for i in items]

    # ── Compute totals ────────────────────────────────────────────────────────
    from collections import defaultdict
    total_amount = sum(e.amount for e in expenses) if expenses else Decimal("0")
    total_paid   = sum(e.amount for e in expenses if e.paid_status == ExpensePaidStatus.paid)
    total_unpaid = total_amount - total_paid

    cat_map: dict = defaultdict(lambda: {"total": Decimal("0"), "count": 0})
    for e in expenses:
        cat_map[e.category]["total"] += e.amount
        cat_map[e.category]["count"] += 1
    by_category = [
        CategoryTotal(category=cat, total=vals["total"], count=vals["count"])
        for cat, vals in cat_map.items()
    ]

    totals = ExpenseTotals(
        total_amount=total_amount, total_paid=total_paid,
        total_unpaid=total_unpaid, by_category=by_category,
    )
    return ExpenseListResponse(case_id=case_id, total=len(expenses), expenses=expenses, totals=totals)


@app.delete(
    "/api/v1/settlement/cases/{case_id}/expenses/{expense_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a case expense",
    tags=["Expenses (2.6.1)"],
)
async def delete_expense(
    case_id:    str = Path(..., description="Case ID"),
    expense_id: str = Path(..., description="Expense ID"),
):
    db      = get_db()
    doc_ref = _expenses_ref(db, case_id)
    snap    = await doc_ref.get()
    items   = snap.to_dict().get("items", []) if snap.exists else []
    new_items = [i for i in items if i["expenseId"] != expense_id]
    if len(new_items) == len(items):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail=f"Expense '{expense_id}' not found for case '{case_id}'")
    await doc_ref.set({"items": new_items})
    logger.info("expense_deleted", expense_id=expense_id, case_id=case_id)


@app.patch(
    "/api/v1/settlement/cases/{case_id}/expenses/{expense_id}",
    response_model=Expense,
    status_code=status.HTTP_200_OK,
    summary="Update a case expense",
    tags=["Expenses (2.6.1)"],
)
async def update_expense(
    case_id:    str = Path(..., description="Case ID"),
    expense_id: str = Path(..., description="Expense ID"),
    request:    ExpenseUpdateRequest = ...,
):
    """
    Update any combination of fields on an existing expense.
    Every change is appended to the expense's ``change_log`` for audit purposes.
    """
    db      = get_db()
    doc_ref = _expenses_ref(db, case_id)
    snap    = await doc_ref.get()
    items   = snap.to_dict().get("items", []) if snap.exists else []

    updated_item = None
    new_items    = []
    now          = datetime.now(tz=timezone.utc)

    for item in items:
        if item["expenseId"] == expense_id:
            changes: dict = {}
            if request.description is not None and request.description != item["description"]:
                changes["description"] = {"from": item["description"], "to": request.description}
                item["description"] = request.description
            if request.amount is not None and float(request.amount) != item["amount"]:
                changes["amount"] = {"from": str(item["amount"]), "to": f"{request.amount:.2f}"}
                item["amount"] = float(request.amount)
            if request.category is not None and request.category.value != item["category"]:
                changes["category"] = {"from": item["category"], "to": request.category.value}
                item["category"] = request.category.value
            if request.vendor is not None and request.vendor != item.get("vendor"):
                changes["vendor"] = {"from": item.get("vendor"), "to": request.vendor}
                item["vendor"] = request.vendor
            if request.date is not None:
                changes["date"] = {"from": str(item.get("date")), "to": str(request.date)}
                item["date"] = request.date
            if request.paid_status is not None and request.paid_status.value != item.get("paidStatus"):
                changes["paidStatus"] = {"from": item.get("paidStatus"), "to": request.paid_status.value}
                item["paidStatus"] = request.paid_status.value

            if changes:
                log_entry = {
                    "changedAt": now,
                    "changedBy": request.updated_by,
                    "changes":   changes,
                }
                item.setdefault("changeLog", []).append(log_entry)
                item["updatedAt"] = now
                item["updatedBy"] = request.updated_by

            updated_item = item
        new_items.append(item)

    if updated_item is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Expense '{expense_id}' not found for case '{case_id}'",
        )

    await doc_ref.set({"items": new_items})
    logger.info("expense_updated", expense_id=expense_id, case_id=case_id)
    return _doc_to_expense(expense_id, updated_item)


@app.put(
    "/api/v1/settlement/cases/{case_id}/expenses/{expense_id}/receipt",
    response_model=Expense,
    status_code=status.HTTP_200_OK,
    summary="Attach a receipt to an expense",
    tags=["Expenses (2.6.1)"],
)
async def attach_receipt(
    case_id:    str = Path(..., description="Case ID"),
    expense_id: str = Path(..., description="Expense ID"),
    request:    ExpenseReceiptRequest = ...,
):
    """
    Store the receipt URL and filename on an expense record.
    Upload the file to Firebase Storage first and pass the resulting URL here.
    """
    db      = get_db()
    doc_ref = _expenses_ref(db, case_id)
    snap    = await doc_ref.get()
    items   = snap.to_dict().get("items", []) if snap.exists else []

    updated_item = None
    new_items    = []
    now          = datetime.now(tz=timezone.utc)

    for item in items:
        if item["expenseId"] == expense_id:
            item["receiptUrl"]      = request.receipt_url
            item["receiptFilename"] = request.receipt_filename
            item["updatedAt"]       = now
            updated_item = item
        new_items.append(item)

    if updated_item is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Expense '{expense_id}' not found for case '{case_id}'",
        )

    await doc_ref.set({"items": new_items})
    logger.info("receipt_attached", expense_id=expense_id, case_id=case_id)
    return _doc_to_expense(expense_id, updated_item)


@app.delete(
    "/api/v1/settlement/cases/{case_id}/expenses/{expense_id}/receipt",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove the receipt from an expense",
    tags=["Expenses (2.6.1)"],
)
async def remove_receipt(
    case_id:    str = Path(..., description="Case ID"),
    expense_id: str = Path(..., description="Expense ID"),
):
    """Clears the receipt URL and filename from an expense record."""
    db      = get_db()
    doc_ref = _expenses_ref(db, case_id)
    snap    = await doc_ref.get()
    items   = snap.to_dict().get("items", []) if snap.exists else []

    found     = False
    new_items = []
    for item in items:
        if item["expenseId"] == expense_id:
            item["receiptUrl"]      = None
            item["receiptFilename"] = None
            item["updatedAt"]       = datetime.now(tz=timezone.utc)
            found = True
        new_items.append(item)

    if not found:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Expense '{expense_id}' not found for case '{case_id}'",
        )

    await doc_ref.set({"items": new_items})
    logger.info("receipt_removed", expense_id=expense_id, case_id=case_id)


# ── Admin: expense categories ─────────────────────────────────────────────────

@app.get(
    "/api/v1/admin/expense-categories",
    response_model=ExpenseCategoriesResponse,
    status_code=status.HTTP_200_OK,
    summary="Get all expense categories (built-in + admin-configured)",
    tags=["Admin – Expense Categories"],
)
async def get_expense_categories():
    """
    Returns the full list of valid expense categories:
    built-in defaults plus any custom categories added by an admin.
    """
    db  = get_db()
    doc = await _expense_categories_ref(db).get()

    custom     = []
    updated_at = None
    updated_by = None

    if doc.exists:
        data       = doc.to_dict()
        custom     = data.get("custom_categories", [])
        updated_at = _to_dt(data.get("updated_at"))
        updated_by = data.get("updated_by")

    built_in = sorted(BUILT_IN_EXPENSE_CATEGORIES)
    all_cats = sorted(set(built_in) | set(custom))

    return ExpenseCategoriesResponse(
        built_in=built_in,
        custom=custom,
        all_categories=all_cats,
        updated_at=updated_at,
        updated_by=updated_by,
    )


@app.put(
    "/api/v1/admin/expense-categories",
    response_model=ExpenseCategoriesResponse,
    status_code=status.HTTP_200_OK,
    summary="Set admin-configured custom expense categories",
    tags=["Admin – Expense Categories"],
)
async def upsert_expense_categories(request: ExpenseCategoriesRequest):
    """
    Replace the custom expense category list.  Built-in categories are always
    included and cannot be removed.
    """
    db = get_db()
    await _expense_categories_ref(db).set({
        "custom_categories": request.custom_categories,
        "updated_by":        request.updated_by,
        "updated_at":        _fs.SERVER_TIMESTAMP,
    })
    logger.info("expense_categories_updated", updated_by=request.updated_by,
                count=len(request.custom_categories))

    built_in = sorted(BUILT_IN_EXPENSE_CATEGORIES)
    all_cats = sorted(set(built_in) | set(request.custom_categories))
    return ExpenseCategoriesResponse(
        built_in=built_in,
        custom=request.custom_categories,
        all_categories=all_cats,
        updated_at=datetime.now(tz=timezone.utc),
        updated_by=request.updated_by,
    )


# ── 2.6.2 Liens ───────────────────────────────────────────────────────────────

@app.post(
    "/api/v1/settlement/cases/{case_id}/liens",
    response_model=Lien,
    status_code=status.HTTP_201_CREATED,
    summary="Add a lien to a case",
    tags=["Liens (2.6.2)"],
)
async def add_lien(
    case_id: str = Path(..., description="Case ID"),
    request: LienRequest = ...,
):
    db      = get_db()
    lien_id = str(uuid.uuid4())
    now     = datetime.now(tz=timezone.utc)
    new_item = {
        "lienId":             lien_id,
        "caseId":             case_id,
        "lienholder":         request.lienholder,
        "amount":             float(request.amount),
        "lienType":           request.lien_type.value,
        "claimStatus":        request.claim_status.value,
        "satisfactionStatus": request.satisfaction_status.value,
        "satisfactionDate":   request.satisfaction_date,
        "notes":              request.notes,
        "addedBy":            request.added_by,
        "addedAt":            now,
        "updatedAt":          None,
        "updatedBy":          None,
    }
    await _liens_ref(db, case_id).set(
        {"items": _fs.ArrayUnion([new_item])}, merge=True
    )
    logger.info("lien_added", lien_id=lien_id, case_id=case_id)
    return _doc_to_lien(lien_id, new_item)


@app.get(
    "/api/v1/settlement/cases/{case_id}/liens",
    response_model=LienListResponse,
    status_code=status.HTTP_200_OK,
    summary="List all liens for a case",
    tags=["Liens (2.6.2)"],
)
async def list_liens(case_id: str = Path(..., description="Case ID")):
    from collections import defaultdict
    db   = get_db()
    snap = await _liens_ref(db, case_id).get()
    if not snap.exists:
        empty_totals = LienTotals(
            total_amount=Decimal("0"), total_outstanding=Decimal("0"),
            total_disputed=Decimal("0"), total_satisfied=Decimal("0"),
            disputed_count=0, by_type=[],
        )
        return LienListResponse(case_id=case_id, total=0, liens=[], totals=empty_totals)

    items = snap.to_dict().get("items", [])
    liens = [_doc_to_lien(i["lienId"], i) for i in items]

    # ── Compute totals ────────────────────────────────────────────────────────
    _ACTIVE    = {"Outstanding", "Negotiating"}
    _SATISFIED = {"Satisfied", "Waived"}
    total_amount      = sum(l.amount for l in liens) if liens else Decimal("0")
    total_outstanding = sum(l.amount for l in liens if l.satisfaction_status.value in _ACTIVE)
    total_satisfied   = sum(l.amount for l in liens if l.satisfaction_status.value in _SATISFIED)
    total_disputed    = sum(l.amount for l in liens if l.is_disputed)
    disputed_count    = sum(1 for l in liens if l.is_disputed)

    type_map: dict = defaultdict(lambda: {"total": Decimal("0"), "count": 0})
    for l in liens:
        type_map[l.lien_type.value]["total"] += l.amount
        type_map[l.lien_type.value]["count"] += 1
    by_type = [LienTypeTotal(lien_type=k, count=v["count"], total=v["total"])
               for k, v in type_map.items()]

    totals = LienTotals(
        total_amount=total_amount, total_outstanding=total_outstanding,
        total_disputed=total_disputed, total_satisfied=total_satisfied,
        disputed_count=disputed_count, by_type=by_type,
    )
    return LienListResponse(case_id=case_id, total=len(liens), liens=liens, totals=totals)


@app.patch(
    "/api/v1/settlement/cases/{case_id}/liens/{lien_id}",
    response_model=Lien,
    status_code=status.HTTP_200_OK,
    summary="Update lien satisfaction status",
    tags=["Liens (2.6.2)"],
)
async def update_lien(
    case_id: str = Path(..., description="Case ID"),
    lien_id: str = Path(..., description="Lien ID"),
    request: LienUpdateRequest = ...,
):
    db      = get_db()
    doc_ref = _liens_ref(db, case_id)
    snap    = await doc_ref.get()
    items   = snap.to_dict().get("items", []) if snap.exists else []

    now          = datetime.now(tz=timezone.utc)
    updated_item = None
    new_items    = []
    for item in items:
        if item["lienId"] == lien_id:
            changed = False
            if request.lien_type is not None:
                item["lienType"]  = request.lien_type.value;  changed = True
            if request.claim_status is not None:
                item["claimStatus"] = request.claim_status.value;  changed = True
            if request.satisfaction_status is not None:
                item["satisfactionStatus"] = request.satisfaction_status.value;  changed = True
            if request.satisfaction_date is not None:
                item["satisfactionDate"] = request.satisfaction_date;  changed = True
            if request.notes is not None:
                item["notes"] = request.notes;  changed = True
            if request.amount is not None:
                item["amount"] = float(request.amount);  changed = True
            if changed:
                item["updatedAt"] = now
            updated_item = item
        new_items.append(item)

    if updated_item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail=f"Lien '{lien_id}' not found for case '{case_id}'")
    await doc_ref.set({"items": new_items})
    logger.info("lien_updated", lien_id=lien_id, case_id=case_id)
    return _doc_to_lien(lien_id, updated_item)


@app.delete(
    "/api/v1/settlement/cases/{case_id}/liens/{lien_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a lien",
    tags=["Liens (2.6.2)"],
)
async def delete_lien(
    case_id: str = Path(..., description="Case ID"),
    lien_id: str = Path(..., description="Lien ID"),
):
    db      = get_db()
    doc_ref = _liens_ref(db, case_id)
    snap    = await doc_ref.get()
    items   = snap.to_dict().get("items", []) if snap.exists else []
    new_items = [i for i in items if i["lienId"] != lien_id]
    if len(new_items) == len(items):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail=f"Lien '{lien_id}' not found for case '{case_id}'")
    await doc_ref.set({"items": new_items})
    logger.info("lien_deleted", lien_id=lien_id, case_id=case_id)


# ── 2.6.3 Loans ───────────────────────────────────────────────────────────────

@app.post(
    "/api/v1/settlement/cases/{case_id}/loans",
    response_model=Loan,
    status_code=status.HTTP_201_CREATED,
    summary="Add a case-advance loan to a case",
    tags=["Loans (2.6.3)"],
)
async def add_loan(
    case_id: str = Path(..., description="Case ID"),
    request: LoanRequest = ...,
):
    db      = get_db()
    loan_id = str(uuid.uuid4())
    now     = datetime.now(tz=timezone.utc)
    new_item = {
        "loanId":             loan_id,
        "caseId":             case_id,
        "lender":             request.lender,
        "amount":             float(request.amount),
        "interestRate":       float(request.interest_rate) if request.interest_rate is not None else None,
        "disbursementDate":   request.disbursement_date,
        "payoffAmount":       float(request.payoff_amount) if request.payoff_amount is not None else None,
        "satisfactionStatus": request.satisfaction_status.value,
        "satisfactionDate":   request.satisfaction_date,
        "notes":              request.notes,
        "addedBy":            request.added_by,
        "addedAt":            now,
        "updatedAt":          None,
        "updatedBy":          None,
    }
    await _loans_ref(db, case_id).set(
        {"items": _fs.ArrayUnion([new_item])}, merge=True
    )
    logger.info("loan_added", loan_id=loan_id, case_id=case_id)
    return _doc_to_loan(loan_id, new_item)


@app.get(
    "/api/v1/settlement/cases/{case_id}/loans",
    response_model=LoanListResponse,
    status_code=status.HTTP_200_OK,
    summary="List all loans for a case",
    tags=["Loans (2.6.3)"],
)
async def list_loans(case_id: str = Path(..., description="Case ID")):
    db   = get_db()
    snap = await _loans_ref(db, case_id).get()
    if not snap.exists:
        empty_totals = LoanTotals(
            total_amount=Decimal("0"), total_payoff=Decimal("0"),
            outstanding_amount=Decimal("0"), outstanding_payoff=Decimal("0"),
        )
        return LoanListResponse(case_id=case_id, total=0, loans=[], totals=empty_totals)

    items = snap.to_dict().get("items", [])
    loans = [_doc_to_loan(i["loanId"], i) for i in items]

    # ── Compute totals ────────────────────────────────────────────────────────
    def _effective_payoff(loan: Loan) -> Decimal:
        return loan.payoff_amount if loan.payoff_amount is not None else loan.amount

    total_amount       = sum(l.amount for l in loans) if loans else Decimal("0")
    total_payoff       = sum(_effective_payoff(l) for l in loans) if loans else Decimal("0")
    outstanding        = [l for l in loans if l.satisfaction_status == LoanSatisfactionStatus.outstanding]
    outstanding_amount = sum(l.amount for l in outstanding)
    outstanding_payoff = sum(_effective_payoff(l) for l in outstanding)

    totals = LoanTotals(
        total_amount=total_amount, total_payoff=total_payoff,
        outstanding_amount=outstanding_amount, outstanding_payoff=outstanding_payoff,
    )
    return LoanListResponse(case_id=case_id, total=len(loans), loans=loans, totals=totals)


@app.patch(
    "/api/v1/settlement/cases/{case_id}/loans/{loan_id}",
    response_model=Loan,
    status_code=status.HTTP_200_OK,
    summary="Update loan satisfaction status",
    tags=["Loans (2.6.3)"],
)
async def update_loan(
    case_id: str = Path(..., description="Case ID"),
    loan_id: str = Path(..., description="Loan ID"),
    request: LoanUpdateRequest = ...,
):
    db      = get_db()
    doc_ref = _loans_ref(db, case_id)
    snap    = await doc_ref.get()
    items   = snap.to_dict().get("items", []) if snap.exists else []

    now          = datetime.now(tz=timezone.utc)
    updated_item = None
    new_items    = []
    for item in items:
        if item["loanId"] == loan_id:
            changed = False
            if request.satisfaction_status is not None:
                item["satisfactionStatus"] = request.satisfaction_status.value;  changed = True
            if request.satisfaction_date is not None:
                item["satisfactionDate"] = request.satisfaction_date;  changed = True
            if request.amount is not None:
                item["amount"] = float(request.amount);  changed = True
            if request.interest_rate is not None:
                item["interestRate"] = float(request.interest_rate);  changed = True
            if request.disbursement_date is not None:
                item["disbursementDate"] = request.disbursement_date;  changed = True
            if request.payoff_amount is not None:
                item["payoffAmount"] = float(request.payoff_amount);  changed = True
            if request.notes is not None:
                item["notes"] = request.notes;  changed = True
            if changed:
                item["updatedAt"] = now
            updated_item = item
        new_items.append(item)

    if updated_item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail=f"Loan '{loan_id}' not found for case '{case_id}'")
    await doc_ref.set({"items": new_items})
    return _doc_to_loan(loan_id, updated_item)


@app.delete(
    "/api/v1/settlement/cases/{case_id}/loans/{loan_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a loan",
    tags=["Loans (2.6.3)"],
)
async def delete_loan(
    case_id: str = Path(..., description="Case ID"),
    loan_id: str = Path(..., description="Loan ID"),
):
    db      = get_db()
    doc_ref = _loans_ref(db, case_id)
    snap    = await doc_ref.get()
    items   = snap.to_dict().get("items", []) if snap.exists else []
    new_items = [i for i in items if i["loanId"] != loan_id]
    if len(new_items) == len(items):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail=f"Loan '{loan_id}' not found for case '{case_id}'")
    await doc_ref.set({"items": new_items})
    logger.info("loan_deleted", loan_id=loan_id, case_id=case_id)


# ── 2.6.4 Disbursements ───────────────────────────────────────────────────────

@app.post(
    "/api/v1/settlement/cases/{case_id}/disbursements",
    response_model=Disbursement,
    status_code=status.HTTP_201_CREATED,
    summary="Add a disbursement record",
    tags=["Disbursements (2.6.4)"],
)
async def add_disbursement(
    case_id: str = Path(..., description="Case ID"),
    request: DisbursementRequest = ...,
):
    db              = get_db()
    disbursement_id = str(uuid.uuid4())
    now             = datetime.now(tz=timezone.utc)
    new_item = {
        "disbursementId":  disbursement_id,
        "caseId":          case_id,
        "payee":           request.payee,
        "payeeType":       request.payee_type.value,
        "amount":          float(request.amount),
        "date":            request.date,
        "method":          request.method.value if request.method else None,
        "referenceNumber": request.reference_number,
        "status":          request.status.value,
        "qbPaymentId":     None,
        "qbSyncStatus":    None,
        "processedBy":     request.processed_by,
        "processedAt":     now,
    }
    await _disbursements_ref(db, case_id).set(
        {"items": _fs.ArrayUnion([new_item])}, merge=True
    )
    logger.info("disbursement_added", disbursement_id=disbursement_id, case_id=case_id)
    return _doc_to_disbursement(disbursement_id, new_item)


@app.get(
    "/api/v1/settlement/cases/{case_id}/disbursements",
    response_model=DisbursementListResponse,
    status_code=status.HTTP_200_OK,
    summary="List all disbursements for a case",
    tags=["Disbursements (2.6.4)"],
)
async def list_disbursements(case_id: str = Path(..., description="Case ID")):
    db   = get_db()
    snap = await _disbursements_ref(db, case_id).get()
    if not snap.exists:
        return DisbursementListResponse(case_id=case_id, total=0, disbursements=[])
    items         = snap.to_dict().get("items", [])
    disbursements = [_doc_to_disbursement(i["disbursementId"], i) for i in items]
    return DisbursementListResponse(case_id=case_id, total=len(disbursements), disbursements=disbursements)


# ── Fee config Firestore converters ──────────────────────────────────────────

def _doc_to_fee_config_data(data: dict) -> FeeConfigData:
    from models.fee_config import FeeStructureType, FeeCapType, GraduatedTier
    tiers = [
        GraduatedTier(
            up_to=Decimal(t["up_to"]) if t.get("up_to") else None,
            percentage=Decimal(t["percentage"]),
        )
        for t in data.get("graduated_tiers", [])
    ]
    return FeeConfigData(
        structure_type  = FeeStructureType(data.get("structure_type", "flat")),
        flat_percentage = Decimal(data["flat_percentage"]) if data.get("flat_percentage") else None,
        graduated_tiers = tiers,
        cap_type        = FeeCapType(data.get("cap_type", "none")),
        cap_amount      = Decimal(data["cap_amount"]) if data.get("cap_amount") else None,
        cap_percentage  = Decimal(data["cap_percentage"]) if data.get("cap_percentage") else None,
    )


def _fee_config_data_to_doc(config: FeeConfigData) -> dict:
    return {
        "structure_type":  config.structure_type.value,
        "flat_percentage": str(config.flat_percentage) if config.flat_percentage is not None else None,
        "graduated_tiers": [
            {"up_to": str(t.up_to) if t.up_to is not None else None, "percentage": str(t.percentage)}
            for t in config.graduated_tiers
        ],
        "cap_type":        config.cap_type.value,
        "cap_amount":      str(config.cap_amount)    if config.cap_amount    is not None else None,
        "cap_percentage":  str(config.cap_percentage) if config.cap_percentage is not None else None,
    }


def _doc_to_firm_fee_config(data: dict) -> FirmFeeConfig:
    return FirmFeeConfig(
        config_id      = data["config_id"],
        config         = _doc_to_fee_config_data(data),
        effective_date = _to_dt(data.get("effective_date")) or datetime.now(tz=timezone.utc),
        notes          = data.get("notes"),
        updated_by     = data.get("updated_by", ""),
        updated_at     = _to_dt(data.get("updated_at")) or datetime.now(tz=timezone.utc),
    )


def _doc_to_audit_entry(doc_id: str, data: dict) -> FeeConfigAuditEntry:
    return FeeConfigAuditEntry(
        audit_id        = doc_id,
        changed_at      = _to_dt(data.get("changed_at")) or datetime.now(tz=timezone.utc),
        changed_by      = data.get("changed_by", ""),
        previous_config = _doc_to_fee_config_data(data["previous_config"]) if data.get("previous_config") else None,
        new_config      = _doc_to_fee_config_data(data["new_config"]),
        notes           = data.get("notes"),
    )


def _doc_to_case_fee_override(case_id: str, data: dict) -> CaseFeeOverride:
    return CaseFeeOverride(
        case_id = case_id,
        config  = _doc_to_fee_config_data(data),
        reason  = data.get("reason", ""),
        set_by  = data.get("set_by", ""),
        set_at  = _to_dt(data.get("set_at")) or datetime.now(tz=timezone.utc),
    )


# ═══════════════════════════════════════════════════════════════════════════════
# FEE CONFIGURATION ROUTES
# ═══════════════════════════════════════════════════════════════════════════════

# ── Firm-wide fee config ──────────────────────────────────────────────────────

@app.get(
    "/api/v1/fee-config",
    response_model=FirmFeeConfig,
    status_code=status.HTTP_200_OK,
    summary="Get current firm-wide fee configuration",
    tags=["Fee Configuration"],
)
async def get_firm_fee_config():
    """
    Returns the current firm-wide attorney fee configuration.
    Returns **404** if no configuration has been set yet.
    """
    db  = get_db()
    doc = await _firm_fee_config_ref(db).get()
    if not doc.exists:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No firm fee configuration found. Use PUT /api/v1/fee-config to create one.",
        )
    return _doc_to_firm_fee_config(doc.to_dict())


@app.put(
    "/api/v1/fee-config",
    response_model=FirmFeeConfig,
    status_code=status.HTTP_200_OK,
    summary="Create or update firm-wide fee configuration",
    tags=["Fee Configuration"],
)
async def upsert_firm_fee_config(request: FirmFeeConfigRequest):
    """
    Set the firm-wide default attorney fee structure.  Supports flat percentage,
    graduated tiers, and optional fee caps.  Every change is written to the
    audit log at ``firm_settings/fee_config/audit/{uuid}``.
    """
    db         = get_db()
    config_ref = _firm_fee_config_ref(db)
    audit_ref  = _fee_audit_ref(db)

    # Read existing config for audit trail
    existing_doc  = await config_ref.get()
    previous_data = existing_doc.to_dict() if existing_doc.exists else None

    config_id      = str(uuid.uuid4())
    effective_date = request.effective_date or datetime.now(tz=timezone.utc)

    doc_data = {
        "config_id":      config_id,
        "effective_date": effective_date,
        "notes":          request.notes,
        "updated_by":     request.updated_by,
        "updated_at":     _fs.SERVER_TIMESTAMP,
        **_fee_config_data_to_doc(request.config),
    }
    await config_ref.set(doc_data)

    # Write audit entry
    audit_id   = str(uuid.uuid4())
    audit_data = {
        "audit_id":        audit_id,
        "changed_at":      _fs.SERVER_TIMESTAMP,
        "changed_by":      request.updated_by,
        "previous_config": _fee_config_data_to_doc(_doc_to_fee_config_data(previous_data))
                           if previous_data else None,
        "new_config":      _fee_config_data_to_doc(request.config),
        "notes":           request.notes,
    }
    await audit_ref.document(audit_id).set(audit_data)
    logger.info("firm_fee_config_updated", config_id=config_id, updated_by=request.updated_by)

    snap = await config_ref.get()
    return _doc_to_firm_fee_config(snap.to_dict())


@app.get(
    "/api/v1/fee-config/audit",
    response_model=FeeConfigAuditResponse,
    status_code=status.HTTP_200_OK,
    summary="Get fee configuration audit trail",
    tags=["Fee Configuration"],
)
async def get_fee_config_audit(limit: int = 20):
    """
    Returns the history of all firm-wide fee configuration changes,
    newest first.  Useful for compliance and change tracking.
    """
    limit = min(limit, 100)
    db    = get_db()

    entries = []
    async for doc in _fee_audit_ref(db).stream():
        entries.append(_doc_to_audit_entry(doc.id, doc.to_dict()))

    entries.sort(key=lambda e: e.changed_at, reverse=True)
    return FeeConfigAuditResponse(total=len(entries), entries=entries[:limit])


# ── Real-time fee preview ─────────────────────────────────────────────────────

@app.post(
    "/api/v1/fee-config/calculate",
    response_model=FeeCalculationDetail,
    status_code=status.HTTP_200_OK,
    summary="Preview attorney fee for a given award (not saved)",
    tags=["Fee Configuration"],
)
async def preview_fee(request: FeePreviewRequest):
    """
    Instantly compute the attorney fee for *gross_award*.

    - If **config** is supplied in the body, that config is used directly
      (labelled ``manual``).
    - Otherwise, the firm-wide default is fetched and applied
      (labelled ``firm_default``).

    Returns **404** if no config supplied and no firm default has been set.
    Returns **422** if *gross_award* ≤ 0.
    """
    db = get_db()

    if request.config is not None:
        config = request.config
        label  = "manual"
    else:
        doc = await _firm_fee_config_ref(db).get()
        if not doc.exists:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No firm fee configuration found. "
                       "Pass a 'config' in the request body or set a firm default first.",
            )
        config = _doc_to_fee_config_data(doc.to_dict())
        label  = "firm_default"

    try:
        result = calculate_attorney_fee(request.gross_award, config, structure_label=label)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))

    logger.info("fee_preview_computed", gross_award=str(request.gross_award), label=label)
    return result


# ── Per-case fee override ─────────────────────────────────────────────────────

@app.get(
    "/api/v1/settlement/cases/{case_id}/fee-override",
    response_model=CaseFeeOverride,
    status_code=status.HTTP_200_OK,
    summary="Get per-case fee override",
    tags=["Case Fee Override"],
)
async def get_case_fee_override(case_id: str = Path(..., description="Case ID")):
    """
    Returns the per-case fee override for *case_id*.
    Returns **404** if no override has been set (case uses firm default).
    """
    db  = get_db()
    doc = await _case_fee_override_ref(db, case_id).get()
    if not doc.exists:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No fee override found for case '{case_id}'. "
                   "The firm default applies.",
        )
    return _doc_to_case_fee_override(case_id, doc.to_dict())


@app.put(
    "/api/v1/settlement/cases/{case_id}/fee-override",
    response_model=CaseFeeOverride,
    status_code=status.HTTP_200_OK,
    summary="Set or update per-case fee override",
    tags=["Case Fee Override"],
)
async def upsert_case_fee_override(
    case_id: str = Path(..., description="Case ID"),
    request: CaseFeeOverrideRequest = ...,
):
    """
    Override the firm-wide fee structure for a specific case.
    Requires a *reason* explaining the business justification.
    """
    db      = get_db()
    doc_ref = _case_fee_override_ref(db, case_id)

    doc_data = {
        "case_id": case_id,
        "reason":  request.reason,
        "set_by":  request.set_by,
        "set_at":  _fs.SERVER_TIMESTAMP,
        **_fee_config_data_to_doc(request.config),
    }
    await doc_ref.set(doc_data)
    logger.info("case_fee_override_set", case_id=case_id, set_by=request.set_by)

    snap = await doc_ref.get()
    return _doc_to_case_fee_override(case_id, snap.to_dict())


@app.delete(
    "/api/v1/settlement/cases/{case_id}/fee-override",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove per-case fee override (revert to firm default)",
    tags=["Case Fee Override"],
)
async def delete_case_fee_override(case_id: str = Path(..., description="Case ID")):
    """
    Removes the per-case fee override.  The case will then use the firm default.
    Returns **404** if no override exists.
    """
    db      = get_db()
    doc_ref = _case_fee_override_ref(db, case_id)
    doc     = await doc_ref.get()
    if not doc.exists:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No fee override found for case '{case_id}'.",
        )
    await doc_ref.delete()
    logger.info("case_fee_override_deleted", case_id=case_id)


@app.post(
    "/api/v1/settlement/cases/{case_id}/fee-config/calculate",
    response_model=FeeCalculationDetail,
    status_code=status.HTTP_200_OK,
    summary="Preview fee for a case using its effective config (override or firm default)",
    tags=["Case Fee Override"],
)
async def preview_case_fee(
    case_id: str = Path(..., description="Case ID"),
    request: FeePreviewRequest = ...,
):
    """
    Compute the attorney fee for *gross_award* using the **effective** config
    for this case:

    1. If the case has a fee override → use it (labelled ``case_override``).
    2. Else if the firm has a default  → use it (labelled ``firm_default``).
    3. Else if *config* is in the body → use it (labelled ``manual``).
    4. Otherwise → **404**.
    """
    db = get_db()

    override_doc = await _case_fee_override_ref(db, case_id).get()
    if override_doc.exists:
        config = _doc_to_fee_config_data(override_doc.to_dict())
        label  = "case_override"
    else:
        firm_doc = await _firm_fee_config_ref(db).get()
        if firm_doc.exists:
            config = _doc_to_fee_config_data(firm_doc.to_dict())
            label  = "firm_default"
        elif request.config is not None:
            config = request.config
            label  = "manual"
        else:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"No fee configuration found for case '{case_id}' "
                       "and no firm default is set.",
            )

    try:
        result = calculate_attorney_fee(request.gross_award, config, structure_label=label)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))

    logger.info("case_fee_preview_computed",
                case_id=case_id, gross_award=str(request.gross_award), label=label)
    return result


# ── Settlement Statement PDF ──────────────────────────────────────────────────

@app.post(
    "/api/v1/settlement/cases/{case_id}/statement/generate",
    response_model=StatementGenerateResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Generate settlement statement PDF",
    tags=["Statement"],
)
async def generate_statement(
    case_id: str = Path(..., description="Case ID"),
    request: StatementGenerateRequest = StatementGenerateRequest(),
):
    """
    Assembles all settlement data for the case (firm info, gross award, expenses,
    liens, loans), renders a one-page PDF, uploads it to Cloud Storage, and
    returns a signed 60-minute download URL.

    Saves statement metadata to Firestore at:
        cases/{caseId}/settlement/statements/records/{statementId}
    """
    from config import get_settings
    db       = get_db()
    settings = get_settings()

    try:
        result = await build_and_upload_statement(db, case_id, request, settings)
    except Exception as exc:
        logger.error("statement_generation_failed", case_id=case_id, error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to generate statement: {exc}",
        )

    # Persist statement metadata in Firestore
    # Path: cases/{caseId}/settlement/statements/{statementId}
    stmt_ref = (
        db.collection("cases").document(case_id)
          .collection("settlement").document(f"statement_{result.statement_id}")
    )
    await stmt_ref.set({
        "statementId":   result.statement_id,
        "caseId":        case_id,
        "gcsPath":       result.gcs_path,
        "pdfUrl":        result.pdf_url,
        "generatedAt":   result.generated_at,
        "preparedBy":    result.prepared_by,
        "statementDate": result.statement_date,
    })

    logger.info("statement_generated",
                case_id=case_id, statement_id=result.statement_id,
                gcs_path=result.gcs_path)
    return result


# ── Download statement PDF ────────────────────────────────────────────────────

@app.get(
    "/api/v1/settlement/cases/{case_id}/statement/{statement_id}/download",
    summary="Download a generated settlement statement PDF",
    tags=["Statement"],
)
async def download_statement(
    case_id:      str = Path(..., description="Case ID"),
    statement_id: str = Path(..., description="Statement ID"),
):
    """
    Streams the PDF directly from Cloud Storage.
    Works locally (ADC) and in Cloud Run (service account).
    """
    from config import get_settings
    import asyncio, io
    from functools import partial
    from google.cloud import storage as gcs

    settings   = get_settings()
    gcs_object = f"settlements/{case_id}/{statement_id}.pdf"

    def _download() -> bytes:
        client = gcs.Client()
        bucket = client.bucket(settings.gcs_bucket)
        blob   = bucket.blob(gcs_object)
        if not blob.exists():
            return b""
        return blob.download_as_bytes()

    loop  = asyncio.get_event_loop()
    data  = await loop.run_in_executor(None, _download)

    if not data:
        raise HTTPException(status_code=404, detail="Statement PDF not found in storage.")

    filename = f"settlement_{case_id}_{statement_id[:8]}.pdf"
    return StreamingResponse(
        io.BytesIO(data),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ══════════════════════════════════════════════════════════════════════════════
# STORAGE GATEWAY
# ══════════════════════════════════════════════════════════════════════════════

@app.post(
    "/api/v1/settlement/cases/{case_id}/files",
    response_model=FileUploadResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Upload a file to Cloud Storage for a case",
    tags=["Storage"],
)
async def upload_file(
    case_id:        str = Path(..., description="Case ID"),
    file:           UploadFile = File(..., description="File to upload (max 50 MB)"),
    file_type:      CaseFileType = Form(CaseFileType.case_document, description="Category of the file"),
    description:    Optional[str] = Form(None, description="Optional description"),
    uploaded_by:    str = Form("", description="UID of the user uploading"),
    linked_to_type: Optional[str] = Form(None, description="Record type this file belongs to: expense | lien | loan"),
    linked_to_id:   Optional[str] = Form(None, description="ID of the linked record"),
):
    """
    Upload any case-related file (PDF, image, Word doc, spreadsheet) to
    Google Cloud Storage.

    - Files are stored at ``cases/{caseId}/files/{fileType}/{fileId}_{filename}``
    - Metadata is persisted in Firestore at ``settlement/files``
    - Returns a 60-minute signed download URL (or gs:// URI in dev)
    - Max file size: **50 MB**
    - Allowed types: PDF, PNG, JPG, DOCX, XLSX, CSV, TXT
    """
    db       = get_db()
    settings = get_settings()
    try:
        result = await upload_case_file(
            db, case_id, file, file_type, description,
            uploaded_by, settings, linked_to_type, linked_to_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
    except Exception as exc:
        logger.error("file_upload_failed", case_id=case_id, error=str(exc))
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                            detail=f"Upload failed: {exc}")
    logger.info("file_uploaded", case_id=case_id, file_id=result.file_id,
                filename=result.original_filename, size=result.size_bytes)
    return result


@app.get(
    "/api/v1/settlement/cases/{case_id}/files",
    response_model=FileListResponse,
    status_code=status.HTTP_200_OK,
    summary="List all uploaded files for a case",
    tags=["Storage"],
)
async def list_files(case_id: str = Path(..., description="Case ID")):
    """
    Returns metadata for every file uploaded for *case_id*.
    Does not stream file content — use the ``/download`` or ``/url`` endpoints for that.
    """
    db = get_db()
    return await list_case_files(db, case_id)


@app.delete(
    "/api/v1/settlement/cases/{case_id}/files/{file_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a case file from Cloud Storage",
    tags=["Storage"],
)
async def delete_file(
    case_id: str = Path(..., description="Case ID"),
    file_id: str = Path(..., description="File ID"),
):
    """
    Permanently deletes the file from GCS **and** removes its Firestore metadata.
    Returns **404** if the file ID is not found.
    """
    db       = get_db()
    settings = get_settings()
    try:
        await delete_case_file(db, case_id, file_id, settings)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except Exception as exc:
        logger.error("file_delete_failed", case_id=case_id, file_id=file_id, error=str(exc))
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                            detail=f"Delete failed: {exc}")
    logger.info("file_deleted", case_id=case_id, file_id=file_id)


@app.get(
    "/api/v1/settlement/cases/{case_id}/files/{file_id}/download",
    summary="Download a case file (streamed)",
    tags=["Storage"],
)
async def download_file(
    case_id: str = Path(..., description="Case ID"),
    file_id: str = Path(..., description="File ID"),
):
    """
    Streams the raw file bytes directly from Cloud Storage.
    Sets ``Content-Disposition: attachment`` so browsers trigger a download.
    Returns **404** if not found in storage.
    """
    import io
    db       = get_db()
    settings = get_settings()
    try:
        data, content_type, filename = await stream_case_file(db, case_id, file_id, settings)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except Exception as exc:
        logger.error("file_download_failed", case_id=case_id, file_id=file_id, error=str(exc))
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                            detail=f"Download failed: {exc}")
    return StreamingResponse(
        io.BytesIO(data),
        media_type=content_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get(
    "/api/v1/settlement/cases/{case_id}/files/{file_id}/url",
    response_model=SignedUrlResponse,
    status_code=status.HTTP_200_OK,
    summary="Get a 60-minute signed download URL for a case file",
    tags=["Storage"],
)
async def get_file_url(
    case_id: str = Path(..., description="Case ID"),
    file_id: str = Path(..., description="File ID"),
):
    """
    Returns a v4 signed GCS URL valid for **60 minutes**.
    Use this when the client needs to display or link to the file directly
    without proxying through this service.

    Falls back to ``gs://`` URI when no service-account key is configured.
    Returns **404** if the file ID is not found.
    """
    db       = get_db()
    settings = get_settings()
    try:
        return await get_signed_url(db, case_id, file_id, settings)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except Exception as exc:
        logger.error("signed_url_failed", case_id=case_id, file_id=file_id, error=str(exc))
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                            detail=f"Could not generate signed URL: {exc}")


# ── Health ────────────────────────────────────────────────────────────────────

@app.get("/health", include_in_schema=False)
async def health():
    return {"status": "healthy", "service": "settlement-financial", "version": "1.0.0"}


@app.get("/", include_in_schema=False)
async def root():
    return {"service": "ZAD Settlement Financial Service", "version": "1.0.0"}


# ── Local dev entrypoint ──────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8080, reload=True, log_level="debug")
