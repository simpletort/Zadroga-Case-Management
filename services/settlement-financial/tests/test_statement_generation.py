"""
tests/test_statement_generation.py
===================================
Tests for the settlement statement PDF generation endpoint.

Covers
------
- _assemble_pdf_data pulls all Firestore collections correctly
- PDF is built and written to a temp file
- GCS upload is called with correct bucket / path
- Endpoint returns 201 with StatementGenerateResponse
- Firestore metadata is saved after generation
- Missing Firestore docs fall back gracefully (no crash)
"""
from __future__ import annotations

import os
import sys
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch, call
import tempfile

import pytest
from fastapi.testclient import TestClient

# ── path setup ────────────────────────────────────────────────────────────────
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ── Firestore mock helpers ────────────────────────────────────────────────────

def _doc(exists: bool = True, data: dict = None):
    """Return a mock async Firestore DocumentSnapshot."""
    m = MagicMock()
    m.exists = exists
    m.to_dict.return_value = data or {}
    return m


def _make_db(
    firm_data=None,
    case_data=None,
    inputs_data=None,
    expenses_items=None,
    liens_items=None,
    loans_items=None,
):
    """Build a mock async Firestore client pre-loaded with settlement data."""
    db = MagicMock()

    def collection_side_effect(name):
        col = MagicMock()

        def document_side_effect(doc_id):
            doc_mock = MagicMock()

            if name == "firmSettings" and doc_id == "profile":
                doc_mock.get = AsyncMock(return_value=_doc(
                    exists=bool(firm_data), data=firm_data or {}
                ))

            elif name == "cases":
                case_doc = MagicMock()
                case_doc.get = AsyncMock(return_value=_doc(
                    exists=bool(case_data), data=case_data or {}
                ))

                def sub_collection(sub_name):
                    sub = MagicMock()

                    def sub_document(sub_doc_id):
                        sd = MagicMock()
                        if sub_doc_id == "inputs":
                            sd.get = AsyncMock(return_value=_doc(data=inputs_data or {}))
                        elif sub_doc_id == "expenses":
                            sd.get = AsyncMock(return_value=_doc(
                                data={"items": expenses_items or []}
                            ))
                        elif sub_doc_id == "liens":
                            sd.get = AsyncMock(return_value=_doc(
                                data={"items": liens_items or []}
                            ))
                        elif sub_doc_id == "loans":
                            sd.get = AsyncMock(return_value=_doc(
                                data={"items": loans_items or []}
                            ))
                        elif sub_doc_id == "statements":
                            stmts = MagicMock()
                            stmts.collection.return_value.document.return_value.set = AsyncMock()
                            return stmts
                        else:
                            sd.get = AsyncMock(return_value=_doc(exists=False))
                        return sd

                    sub.document.side_effect = sub_document
                    return sub

                case_doc.collection.side_effect = sub_collection
                return case_doc

            return doc_mock

        col.document.side_effect = document_side_effect
        return col

    db.collection.side_effect = collection_side_effect
    return db


# ── Fixtures ──────────────────────────────────────────────────────────────────

FIRM = {
    "firmName":    "SimpleTort Law Group",
    "firmAddress": "123 Legal Plaza, New York, NY 10001",
    "firmPhone":   "(212) 555-0100",
    "firmEmail":   "settlements@simpletort.com",
}

CASE = {
    "clientName": "John Michael Doe",
    "caseType":   "Zadroga / WTC Health Program",
}

INPUTS = {
    "grossAward":     "500000.00",
    "attorneyFeePct": "33.33",
}

EXPENSES = [
    {"description": "Filing Fee",      "amount": "500.00"},
    {"description": "Medical Records", "amount": "850.00"},
]

LIENS = [
    {"lienholder": "Medicare", "lienType": "Medical",  "amount": "12000.00", "claimStatus": "Verified"},
    {"lienholder": "Aetna",    "lienType": "Private",  "amount": "5500.00",  "claimStatus": "Disputed"},
]

LOANS = [
    {"lender": "LawCash", "amount": "5000.00", "payoffAmount": "5750.00"},
]


# ── Tests: _assemble_pdf_data ─────────────────────────────────────────────────

class TestAssemblePdfData:

    @pytest.mark.asyncio
    async def test_gross_award_loaded(self):
        from services.pdf_service import _assemble_pdf_data
        from models.statement import StatementGenerateRequest
        db = _make_db(firm_data=FIRM, case_data=CASE, inputs_data=INPUTS,
                      expenses_items=EXPENSES, liens_items=LIENS, loans_items=LOANS)
        data, _, _ = await _assemble_pdf_data(db, "ZAD-001", StatementGenerateRequest())
        assert data["gross_award"] == Decimal("500000.00")

    @pytest.mark.asyncio
    async def test_attorney_fee_calculated(self):
        from services.pdf_service import _assemble_pdf_data
        from models.statement import StatementGenerateRequest
        db = _make_db(firm_data=FIRM, case_data=CASE, inputs_data=INPUTS,
                      expenses_items=EXPENSES, liens_items=LIENS, loans_items=LOANS)
        data, _, _ = await _assemble_pdf_data(db, "ZAD-001", StatementGenerateRequest())
        expected = (Decimal("500000.00") * Decimal("33.33") / 100).quantize(Decimal("0.01"))
        assert data["attorney_fee"] == expected

    @pytest.mark.asyncio
    async def test_expenses_total(self):
        from services.pdf_service import _assemble_pdf_data
        from models.statement import StatementGenerateRequest
        db = _make_db(firm_data=FIRM, case_data=CASE, inputs_data=INPUTS,
                      expenses_items=EXPENSES, liens_items=LIENS, loans_items=LOANS)
        data, _, _ = await _assemble_pdf_data(db, "ZAD-001", StatementGenerateRequest())
        assert data["total_expenses"] == Decimal("1350.00")

    @pytest.mark.asyncio
    async def test_liens_total(self):
        from services.pdf_service import _assemble_pdf_data
        from models.statement import StatementGenerateRequest
        db = _make_db(firm_data=FIRM, case_data=CASE, inputs_data=INPUTS,
                      expenses_items=EXPENSES, liens_items=LIENS, loans_items=LOANS)
        data, _, _ = await _assemble_pdf_data(db, "ZAD-001", StatementGenerateRequest())
        assert data["total_liens"] == Decimal("17500.00")

    @pytest.mark.asyncio
    async def test_loans_use_payoff_amount(self):
        from services.pdf_service import _assemble_pdf_data
        from models.statement import StatementGenerateRequest
        db = _make_db(firm_data=FIRM, case_data=CASE, inputs_data=INPUTS,
                      expenses_items=EXPENSES, liens_items=LIENS, loans_items=LOANS)
        data, _, _ = await _assemble_pdf_data(db, "ZAD-001", StatementGenerateRequest())
        assert data["total_loans"] == Decimal("5750.00")

    @pytest.mark.asyncio
    async def test_disputed_lien_flagged(self):
        from services.pdf_service import _assemble_pdf_data
        from models.statement import StatementGenerateRequest
        db = _make_db(firm_data=FIRM, case_data=CASE, inputs_data=INPUTS,
                      expenses_items=EXPENSES, liens_items=LIENS, loans_items=LOANS)
        data, _, _ = await _assemble_pdf_data(db, "ZAD-001", StatementGenerateRequest())
        disputed = [l for l in data["liens"] if l["disputed"]]
        assert len(disputed) == 1
        assert disputed[0]["lienholder"] == "Aetna"

    @pytest.mark.asyncio
    async def test_net_to_client_calculated(self):
        from services.pdf_service import _assemble_pdf_data
        from models.statement import StatementGenerateRequest
        db = _make_db(firm_data=FIRM, case_data=CASE, inputs_data=INPUTS,
                      expenses_items=EXPENSES, liens_items=LIENS, loans_items=LOANS)
        data, _, _ = await _assemble_pdf_data(db, "ZAD-001", StatementGenerateRequest())
        assert data["net_to_client"] == data["gross_award"] - data["total_deductions"]


    @pytest.mark.asyncio
    async def test_request_overrides_applied(self):
        from services.pdf_service import _assemble_pdf_data
        from models.statement import StatementGenerateRequest
        db = _make_db(firm_data=FIRM, case_data=CASE, inputs_data=INPUTS)
        req = StatementGenerateRequest(
            prepared_by="Jane Smith",
            statement_date="May 3, 2026",
            payment_method="Wire Transfer",
            payable_to="Estate of John Doe",
            memo="Ref: ZAD-001",
        )
        data, stmt_date, prepared_by = await _assemble_pdf_data(db, "ZAD-001", req)
        assert prepared_by            == "Jane Smith"
        assert stmt_date              == "May 3, 2026"
        assert data["payment_method"] == "Wire Transfer"
        assert data["payable_to"]     == "Estate of John Doe"
        assert data["memo"]           == "Ref: ZAD-001"

    @pytest.mark.asyncio
    async def test_missing_case_and_financial_docs_no_crash(self):
        """Case/inputs/expenses docs absent → zeros, but firm data must be present."""
        from services.pdf_service import _assemble_pdf_data
        from models.statement import StatementGenerateRequest
        # firm_data is required; only case/financial docs are absent
        db = _make_db(firm_data=FIRM)
        data, _, _ = await _assemble_pdf_data(db, "ZAD-MISSING", StatementGenerateRequest())
        assert data["gross_award"]    == Decimal("0")
        assert data["total_expenses"] == Decimal("0")
        assert data["expenses"] == []
        assert data["liens"]    == []
        assert data["loans"]    == []

    @pytest.mark.asyncio
    async def test_missing_firm_name_raises_config_error(self):
        """firmSettings/profile.firmName absent → ConfigError (no silent fallback)."""
        from services.pdf_service import _assemble_pdf_data, ConfigError
        from models.statement import StatementGenerateRequest
        db = _make_db(firm_data={})   # profile doc exists but firmName key is missing
        with pytest.raises(ConfigError, match="firmSettings/profile.firmName is required"):
            await _assemble_pdf_data(db, "ZAD-001", StatementGenerateRequest())


# ── Tests: build_and_upload_statement ────────────────────────────────────────

class TestBuildAndUpload:

    def _settings(self):
        from config import Settings
        s = MagicMock(spec=Settings)
        s.gcs_bucket                        = "test-bucket"
        s.firm_logo_path                    = ""
        s.firebase_service_account_key_path = ""   # no key in tests → fallback URL
        return s

    @pytest.mark.asyncio
    @patch("services.pdf_service._upload_to_gcs")
    async def test_returns_response_model(self, mock_upload):
        from services.pdf_service import build_and_upload_statement
        from models.statement import StatementGenerateRequest, StatementGenerateResponse
        mock_upload.return_value = "https://signed-url.example.com/file.pdf"
        db = _make_db(firm_data=FIRM, case_data=CASE, inputs_data=INPUTS,
                      expenses_items=EXPENSES, liens_items=LIENS, loans_items=LOANS)
        result = await build_and_upload_statement(
            db, "ZAD-001", StatementGenerateRequest(), self._settings()
        )
        assert isinstance(result, StatementGenerateResponse)
        assert result.case_id == "ZAD-001"
        assert result.pdf_url == "https://signed-url.example.com/file.pdf"
        assert result.gcs_path.startswith("gs://test-bucket/settlements/ZAD-001/")

    @pytest.mark.asyncio
    @patch("services.pdf_service._upload_to_gcs")
    async def test_gcs_called_with_correct_bucket(self, mock_upload):
        from services.pdf_service import build_and_upload_statement
        from models.statement import StatementGenerateRequest
        mock_upload.return_value = "https://url"
        db = _make_db(firm_data=FIRM, case_data=CASE, inputs_data=INPUTS)
        await build_and_upload_statement(db, "ZAD-001", StatementGenerateRequest(), self._settings())
        assert mock_upload.call_args[0][1] == "test-bucket"

    @pytest.mark.asyncio
    @patch("services.pdf_service._upload_to_gcs")
    async def test_temp_file_cleaned_up(self, mock_upload):
        captured_path = []
        from services.pdf_service import build_and_upload_statement
        from models.statement import StatementGenerateRequest

        original_build = __import__(
            "templates.settlement_statement_template",
            fromlist=["build_settlement_pdf"]
        ).build_settlement_pdf

        def capturing_build(data, path, logo_path=None):
            captured_path.append(path)
            return original_build(data, path, logo_path=logo_path)

        mock_upload.return_value = "https://url"
        db = _make_db(firm_data=FIRM, case_data=CASE, inputs_data=INPUTS,
                      expenses_items=EXPENSES, liens_items=LIENS, loans_items=LOANS)

        with patch("services.pdf_service.build_settlement_pdf", side_effect=capturing_build):
            await build_and_upload_statement(
                db, "ZAD-001", StatementGenerateRequest(), self._settings()
            )

        assert captured_path, "build_settlement_pdf was not called"
        assert not os.path.exists(captured_path[0]), "Temp file was not deleted"

    @pytest.mark.asyncio
    @patch("services.pdf_service._upload_to_gcs", side_effect=Exception("GCS unavailable"))
    async def test_gcs_failure_propagates(self, mock_upload):
        from services.pdf_service import build_and_upload_statement
        from models.statement import StatementGenerateRequest
        db = _make_db(firm_data=FIRM, case_data=CASE, inputs_data=INPUTS,
                      expenses_items=EXPENSES, liens_items=LIENS, loans_items=LOANS)
        with pytest.raises(Exception, match="GCS unavailable"):
            await build_and_upload_statement(
                db, "ZAD-001", StatementGenerateRequest(), self._settings()
            )


# ── Tests: API endpoint ───────────────────────────────────────────────────────

class TestStatementEndpoint:

    def _client(self):
        from main import app
        return TestClient(app)

    @patch("main.get_db")
    @patch("main.get_settings", return_value=MagicMock(gcs_bucket="test-bucket", firm_logo_path=""))
    def test_endpoint_returns_201(self, mock_settings, mock_get_db):
        from models.statement import StatementGenerateResponse

        # The endpoint calls db.collection(...).document(...).collection(...).document(...).set(...)
        # after build_and_upload_statement returns.  Make .set() awaitable.
        mock_db = MagicMock()
        (mock_db.collection.return_value
                .document.return_value
                .collection.return_value
                .document.return_value
                .set) = AsyncMock()
        mock_get_db.return_value = mock_db

        expected = StatementGenerateResponse(
            case_id        = "ZAD-001",
            statement_id   = str(uuid.uuid4()),
            pdf_url        = "https://signed-url.example.com/file.pdf",
            generated_at   = datetime.now(tz=timezone.utc),
            prepared_by    = "Settlement Department",
            statement_date = "May 3, 2026",
            gcs_path       = "gs://test-bucket/settlements/ZAD-001/abc.pdf",
        )
        with patch("main.build_and_upload_statement", new=AsyncMock(return_value=expected)):
            client = self._client()
            resp = client.post("/api/v1/settlement/cases/ZAD-001/statement/generate", json={})
        assert resp.status_code == 201
        body = resp.json()
        assert body["case_id"] == "ZAD-001"
        assert "pdf_url"       in body
        assert "statement_id"  in body

    @patch("main.get_db", return_value=MagicMock())
    @patch("main.get_settings", return_value=MagicMock(gcs_bucket="test-bucket", firm_logo_path=""))
    def test_endpoint_500_on_failure(self, mock_settings, mock_get_db):
        with patch("main.build_and_upload_statement",
                   new=AsyncMock(side_effect=RuntimeError("render failed"))):
            client = self._client()
            resp = client.post("/api/v1/settlement/cases/ZAD-001/statement/generate", json={})
        assert resp.status_code == 500
        assert "render failed" in resp.json()["detail"]
