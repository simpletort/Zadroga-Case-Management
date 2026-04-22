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

GET /health
"""
from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from decimal import Decimal
from typing import List, Optional

from fastapi import FastAPI, HTTPException, Path, status
from google.cloud import firestore as _fs

from config import get_settings
from logging_config import get_logger, setup_logging
from models.settlement import (
    CalculationHistoryResponse,
    CalculationPreviewResponse,
    CalculationRequest,
    CaseSettlementInputs,
    CaseSettlementInputsRequest,
    Disbursement,
    DisbursementListResponse,
    DisbursementRequest,
    Expense,
    ExpenseListResponse,
    ExpenseRequest,
    Lien,
    LienListResponse,
    LienRequest,
    LienUpdateRequest,
    Loan,
    LoanListResponse,
    LoanRequest,
    LoanUpdateRequest,
    SavedCalculation,
)
from services.calculator import run_calculation
from services.firestore_client import get_db

logger = get_logger(__name__)

# Single settlement subcollection — inputs doc + calculation docs
_SETTLEMENT_SUB = "settlement"
_INPUTS_DOC     = "inputs"


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


# ── Lifespan ──────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    settings = get_settings()
    logger.info("settlement_service_starting", env=settings.app_env, project=settings.gcp_project_id)
    get_db()
    yield
    logger.info("settlement_service_shutdown")


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
    from models.settlement import ExpenseCategory, QBSyncStatus
    return Expense(
        expense_id=doc_id,
        case_id=data["caseId"],
        description=data["description"],
        amount=Decimal(str(data["amount"])),
        category=ExpenseCategory(data["category"]),
        date=_to_dt(data.get("date")) or datetime.now(tz=timezone.utc),
        added_by=data.get("addedBy", ""),
        added_at=_to_dt(data.get("addedAt")) or datetime.now(tz=timezone.utc),
        qb_expense_id=data.get("qbExpenseId"),
        qb_sync_status=QBSyncStatus(data["qbSyncStatus"]) if data.get("qbSyncStatus") else None,
        qb_synced_at=_to_dt(data.get("qbSyncedAt")),
    )


def _doc_to_lien(doc_id: str, data: dict) -> Lien:
    from models.settlement import LienSatisfactionStatus
    return Lien(
        lien_id=doc_id,
        case_id=data["caseId"],
        lienholder=data["lienholder"],
        amount=Decimal(str(data["amount"])),
        satisfaction_status=LienSatisfactionStatus(data["satisfactionStatus"]),
        satisfaction_date=_to_dt(data.get("satisfactionDate")),
        notes=data.get("notes"),
        added_by=data.get("addedBy", ""),
        added_at=_to_dt(data.get("addedAt")) or datetime.now(tz=timezone.utc),
    )


def _doc_to_loan(doc_id: str, data: dict) -> Loan:
    from models.settlement import LoanSatisfactionStatus
    return Loan(
        loan_id=doc_id,
        case_id=data["caseId"],
        lender=data["lender"],
        amount=Decimal(str(data["amount"])),
        satisfaction_status=LoanSatisfactionStatus(data["satisfactionStatus"]),
        satisfaction_date=_to_dt(data.get("satisfactionDate")),
        added_by=data.get("addedBy", ""),
        added_at=_to_dt(data.get("addedAt")) or datetime.now(tz=timezone.utc),
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
    Reads gross_award, attorney_fee_pct and line items from
    ``cases/{caseId}/settlement/inputs`` and runs the calculation automatically.

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

    def _items(raw: list):
        return [LineItem(description=i["description"], amount=Decimal(i["amount"])) for i in (raw or [])]

    calc_request = CalculationRequest(
        gross_award=Decimal(inputs_data["gross_award"]),
        attorney_fee_pct=Decimal(inputs_data["attorney_fee_pct"]),
        case_expenses=_items(inputs_data.get("case_expenses", [])),
        liens=_items(inputs_data.get("liens", [])),
        client_loans=_items(inputs_data.get("client_loans", [])),
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
        if doc.id == _INPUTS_DOC:
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
        if doc.id == _INPUTS_DOC:
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
        "expenseId":    expense_id,
        "caseId":       case_id,
        "description":  request.description,
        "amount":       float(request.amount),
        "category":     request.category.value,
        "date":         request.date,
        "addedBy":      request.added_by,
        "addedAt":      now,
        "qbExpenseId":  None,
        "qbSyncStatus": None,
        "qbSyncedAt":   None,
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
        return ExpenseListResponse(case_id=case_id, total=0, expenses=[])
    items    = snap.to_dict().get("items", [])
    expenses = [_doc_to_expense(i["expenseId"], i) for i in items]
    return ExpenseListResponse(case_id=case_id, total=len(expenses), expenses=expenses)


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
        "satisfactionStatus": request.satisfaction_status.value,
        "satisfactionDate":   request.satisfaction_date,
        "notes":              request.notes,
        "addedBy":            request.added_by,
        "addedAt":            now,
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
    db   = get_db()
    snap = await _liens_ref(db, case_id).get()
    if not snap.exists:
        return LienListResponse(case_id=case_id, total=0, liens=[])
    items = snap.to_dict().get("items", [])
    liens = [_doc_to_lien(i["lienId"], i) for i in items]
    return LienListResponse(case_id=case_id, total=len(liens), liens=liens)


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

    updated_item = None
    new_items = []
    for item in items:
        if item["lienId"] == lien_id:
            if request.satisfaction_status:
                item["satisfactionStatus"] = request.satisfaction_status.value
            if request.satisfaction_date:
                item["satisfactionDate"] = request.satisfaction_date
            if request.notes is not None:
                item["notes"] = request.notes
            if request.amount:
                item["amount"] = float(request.amount)
            updated_item = item
        new_items.append(item)

    if updated_item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail=f"Lien '{lien_id}' not found for case '{case_id}'")
    await doc_ref.set({"items": new_items})
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
        "satisfactionStatus": request.satisfaction_status.value,
        "satisfactionDate":   request.satisfaction_date,
        "addedBy":            request.added_by,
        "addedAt":            now,
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
        return LoanListResponse(case_id=case_id, total=0, loans=[])
    items = snap.to_dict().get("items", [])
    loans = [_doc_to_loan(i["loanId"], i) for i in items]
    return LoanListResponse(case_id=case_id, total=len(loans), loans=loans)


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

    updated_item = None
    new_items = []
    for item in items:
        if item["loanId"] == loan_id:
            if request.satisfaction_status:
                item["satisfactionStatus"] = request.satisfaction_status.value
            if request.satisfaction_date:
                item["satisfactionDate"] = request.satisfaction_date
            if request.amount:
                item["amount"] = float(request.amount)
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
