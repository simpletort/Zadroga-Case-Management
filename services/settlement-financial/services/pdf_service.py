"""
services/pdf_service.py
=======================
Assembles settlement data from Firestore (async), builds the PDF, and uploads
it to Google Cloud Storage.

Public API
----------
    build_and_upload_statement(db, case_id, request, settings) -> StatementGenerateResponse
"""
from __future__ import annotations

import asyncio
import os
import tempfile
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from functools import partial
from typing import Any

from google.cloud import storage as gcs

from config import Settings
from models.statement import StatementGenerateRequest, StatementGenerateResponse
from templates.settlement_statement_template import build_settlement_pdf


# ── Helpers ───────────────────────────────────────────────────────────────────

def _dec(val, default: str = "0") -> Decimal:
    if val is None:
        return Decimal(default)
    return Decimal(str(val))


def _today_display() -> str:
    now = datetime.now(tz=timezone.utc)
    return now.strftime("%B ") + str(now.day) + now.strftime(", %Y")


# ── Async Firestore loaders ───────────────────────────────────────────────────

async def _load_firm_settings(db) -> dict[str, str]:
    doc = await db.collection("firmSettings").document("profile").get()
    data = doc.to_dict() if doc.exists else {}
    return {
        "firm_name":    data.get("firmName",    "Law Firm"),
        "firm_address": data.get("firmAddress", ""),
        "firm_phone":   data.get("firmPhone",   ""),
        "firm_email":   data.get("firmEmail",   ""),
    }


async def _load_case_info(db, case_id: str) -> dict[str, str]:
    doc = await db.collection("cases").document(case_id).get()
    data = doc.to_dict() if doc.exists else {}

    # Try direct clientName field; fall back to leadData composite name
    client_name = data.get("clientName") or data.get("client_name")
    if not client_name:
        lead  = data.get("leadData", {})
        first = lead.get("firstName", "")
        last  = lead.get("lastName", "")
        client_name = f"{first} {last}".strip() or "—"

    return {
        "client_name": client_name,
        "case_type":   data.get("caseType", data.get("case_type", "Zadroga / WTC Health Program")),
    }


async def _load_settlement_inputs(db, case_id: str) -> dict:
    ref = (db.collection("cases").document(case_id)
             .collection("settlement").document("inputs"))
    doc = await ref.get()
    data = doc.to_dict() if doc.exists else {}
    gross        = _dec(data.get("grossAward",     data.get("gross_award")))
    fee_pct      = _dec(data.get("attorneyFeePct", data.get("attorney_fee_pct", "33.33")))
    attorney_fee = (gross * fee_pct / Decimal("100")).quantize(Decimal("0.01"))
    return {
        "gross_award":      gross,
        "attorney_fee_pct": fee_pct,
        "attorney_fee":     attorney_fee,
    }


async def _load_expenses(db, case_id: str) -> tuple[list[dict], Decimal]:
    ref = (db.collection("cases").document(case_id)
             .collection("settlement").document("expenses"))
    doc = await ref.get()
    items = (doc.to_dict() or {}).get("items", []) if doc.exists else []
    expenses, total = [], Decimal("0")
    for it in items:
        amt = _dec(it.get("amount"))
        expenses.append({"description": it.get("description", "Expense"), "amount": amt})
        total += amt
    return expenses, total


async def _load_liens(db, case_id: str) -> tuple[list[dict], Decimal]:
    ref = (db.collection("cases").document(case_id)
             .collection("settlement").document("liens"))
    doc = await ref.get()
    items = (doc.to_dict() or {}).get("items", []) if doc.exists else []
    liens, total = [], Decimal("0")
    for it in items:
        amt = _dec(it.get("amount"))
        liens.append({
            "lienholder": it.get("lienholder", "—"),
            "type":       it.get("lienType", "Private"),
            "amount":     amt,
            "disputed":   it.get("claimStatus") == "Disputed",
        })
        total += amt
    return liens, total


async def _load_loans(db, case_id: str) -> tuple[list[dict], Decimal]:
    ref = (db.collection("cases").document(case_id)
             .collection("settlement").document("loans"))
    doc = await ref.get()
    items = (doc.to_dict() or {}).get("items", []) if doc.exists else []
    loans, total = [], Decimal("0")
    for it in items:
        amt    = _dec(it.get("amount"))
        payoff = _dec(it.get("payoffAmount")) if it.get("payoffAmount") else amt
        loans.append({"lender": it.get("lender", "—"), "amount": amt, "payoff": payoff})
        total += payoff
    return loans, total


# ── Data assembly ─────────────────────────────────────────────────────────────

async def _assemble_pdf_data(
    db,
    case_id: str,
    request: StatementGenerateRequest,
) -> tuple[dict[str, Any], str, str]:
    """
    Fetch all Firestore data concurrently and build the dict the template needs.
    Returns (pdf_data, statement_date, prepared_by).
    """
    (firm, case, inputs,
     (expenses, total_expenses),
     (liens,    total_liens),
     (loans,    total_loans)) = await asyncio.gather(
        _load_firm_settings(db),
        _load_case_info(db, case_id),
        _load_settlement_inputs(db, case_id),
        _load_expenses(db, case_id),
        _load_liens(db, case_id),
        _load_loans(db, case_id),
    )

    gross            = inputs["gross_award"]
    attorney_fee     = inputs["attorney_fee"]
    total_deductions = (attorney_fee + total_expenses + total_liens + total_loans).quantize(Decimal("0.01"))
    net_to_client    = (gross - total_deductions).quantize(Decimal("0.01"))

    statement_date = request.statement_date or _today_display()
    prepared_by    = request.prepared_by    or "Settlement Department"
    payment_method = request.payment_method or "Check"
    payable_to     = request.payable_to     or case["client_name"]
    memo           = request.memo           or f"Settlement – {case_id}"

    pdf_data = {
        **firm,
        "client_name":      case["client_name"],
        "case_id":          case_id,
        "case_type":        case["case_type"],
        "statement_date":   statement_date,
        "prepared_by":      prepared_by,
        "gross_award":      gross,
        "attorney_fee_pct": inputs["attorney_fee_pct"],
        "attorney_fee":     attorney_fee,
        "expenses":         expenses,
        "liens":            liens,
        "loans":            loans,
        "total_expenses":   total_expenses,
        "total_liens":      total_liens,
        "total_loans":      total_loans,
        "total_deductions": total_deductions,
        "net_to_client":    net_to_client,
        "payment_method":   payment_method,
        "payable_to":       payable_to,
        "memo":             memo,
    }
    return pdf_data, statement_date, prepared_by


# ── GCS upload (blocking — run in executor) ───────────────────────────────────

def _upload_to_gcs(pdf_path: str, bucket_name: str, gcs_object_path: str,
                   sa_key_path: str | None = None) -> str:
    """
    Upload PDF to GCS and return a URL to access it.

    If a service-account key file is available it generates a v4 signed URL
    (60-minute TTL). Otherwise it falls back to a plain GCS URI
    (gs://bucket/path) which is still accessible to authenticated callers.
    """
    if sa_key_path and os.path.isfile(sa_key_path):
        from google.oauth2 import service_account as _sa
        credentials = _sa.Credentials.from_service_account_file(
            sa_key_path,
            scopes=["https://www.googleapis.com/auth/cloud-platform"],
        )
        client = gcs.Client(credentials=credentials)
    else:
        client = gcs.Client()

    bucket = client.bucket(bucket_name)
    blob   = bucket.blob(gcs_object_path)
    blob.upload_from_filename(pdf_path, content_type="application/pdf")

    if sa_key_path and os.path.isfile(sa_key_path):
        return blob.generate_signed_url(
            expiration=timedelta(minutes=60),
            method="GET",
            version="v4",
            credentials=credentials,
        )
    # Fallback: return gs:// URI (usable by authenticated GCS clients)
    return f"gs://{bucket_name}/{gcs_object_path}"


# ── Public entry point ────────────────────────────────────────────────────────

async def build_and_upload_statement(
    db,
    case_id: str,
    request: StatementGenerateRequest,
    settings: Settings,
) -> StatementGenerateResponse:
    """
    1. Fetch all Firestore data concurrently.
    2. Render PDF in a thread (non-blocking).
    3. Upload to GCS in a thread (non-blocking).
    4. Return StatementGenerateResponse with signed URL.
    """
    statement_id = str(uuid.uuid4())
    generated_at = datetime.now(tz=timezone.utc)
    logo_path    = settings.firm_logo_path or None

    pdf_data, statement_date, prepared_by = await _assemble_pdf_data(db, case_id, request)

    # Build PDF and upload in a thread so we don't block the event loop
    loop = asyncio.get_event_loop()

    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        tmp_path = tmp.name

    try:
        await loop.run_in_executor(
            None,
            partial(build_settlement_pdf, pdf_data, tmp_path, logo_path=logo_path)
        )

        gcs_object = f"settlements/{case_id}/{statement_id}.pdf"
        sa_key     = settings.firebase_service_account_key_path
        pdf_url = await loop.run_in_executor(
            None,
            partial(_upload_to_gcs, tmp_path, settings.gcs_bucket, gcs_object, sa_key)
        )
        gcs_path = f"gs://{settings.gcs_bucket}/{gcs_object}"

    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)

    return StatementGenerateResponse(
        case_id        = case_id,
        statement_id   = statement_id,
        pdf_url        = pdf_url,
        generated_at   = generated_at,
        prepared_by    = prepared_by,
        statement_date = statement_date,
        gcs_path       = gcs_path,
    )
