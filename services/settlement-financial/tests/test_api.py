"""
tests/test_api.py — FastAPI endpoint tests for the settlement-financial service.

Firestore is mocked so these run without GCP credentials.
All data lives as subcollections under cases/{case_id}:
  cases/{case_id}/settlement_inputs/current
  cases/{case_id}/settlement_calculations/{calc_id}
"""
from __future__ import annotations

import os
import sys
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def client():
    with patch("services.firestore_client.get_db"), patch("main.get_db"):
        from main import app
        return TestClient(app, raise_server_exceptions=True)


PREVIEW_PAYLOAD = {
    "gross_award": "500000.00",
    "attorney_fee_pct": "33.33",
    "case_expenses": [
        {"description": "Medical records", "amount": "850.00"},
        {"description": "Expert witness", "amount": "3500.00"},
    ],
    "liens": [{"description": "Medicare lien", "amount": "12000.00"}],
    "client_loans": [{"description": "Case advance", "amount": "5000.00"}],
    "notes": "Initial estimate",
}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_calc_doc(calc_id, case_id):
    return {
        "calculation_id": calc_id,
        "case_id": case_id,
        "created_at": datetime(2026, 4, 17, 12, 0, 0, tzinfo=timezone.utc),
        "created_by": "",
        "gross_award": "500000.00",
        "attorney_fee_pct": "33.33",
        "case_expenses": [
            {"description": "Medical records", "amount": "850.00"},
            {"description": "Expert witness", "amount": "3500.00"},
        ],
        "liens": [{"description": "Medicare lien", "amount": "12000.00"}],
        "client_loans": [{"description": "Case advance", "amount": "5000.00"}],
        "notes": "Initial estimate",
        "attorney_fee_amount": "166650.00",
        "total_expenses": "4350.00",
        "total_liens": "12000.00",
        "total_loans": "5000.00",
        "total_deductions": "188000.00",
        "net_to_client": "312000.00",
    }


def _make_inputs_doc(case_id):
    return {
        "case_id": case_id,
        "gross_award": "500000.00",
        "attorney_fee_pct": "33.33",
        "case_expenses": [
            {"description": "Medical records", "amount": "850.00"},
            {"description": "Expert witness", "amount": "3500.00"},
        ],
        "liens": [{"description": "Medicare lien", "amount": "12000.00"}],
        "client_loans": [{"description": "Case advance", "amount": "5000.00"}],
        "notes": "Pre-stored inputs",
        "updated_at": datetime(2026, 4, 17, 12, 0, 0, tzinfo=timezone.utc),
    }


def _mock_db_for_inputs(case_id, inputs_doc):
    mock_snap = MagicMock()
    mock_snap.to_dict.return_value = inputs_doc
    mock_snap.exists = True

    mock_doc_ref = MagicMock()
    mock_doc_ref.set = AsyncMock()
    mock_doc_ref.get = AsyncMock(return_value=mock_snap)

    mock_db = MagicMock()
    (mock_db.collection.return_value
              .document.return_value
              .collection.return_value
              .document.return_value) = mock_doc_ref

    return mock_db, mock_doc_ref, mock_snap


def _mock_db_for_calc(calc_id, case_id, calc_doc):
    """
    Build a mock db where:
      db.collection("cases").document(case_id).collection("settlement_calculations").document(calc_id)
    returns a ref with set/get mocked.
    """
    mock_snap = MagicMock()
    mock_snap.to_dict.return_value = calc_doc
    mock_snap.exists = True
    mock_snap.id = calc_id

    mock_doc_ref = MagicMock()
    mock_doc_ref.set = AsyncMock()
    mock_doc_ref.get = AsyncMock(return_value=mock_snap)
    mock_doc_ref.delete = AsyncMock()

    mock_db = MagicMock()
    (mock_db.collection.return_value
              .document.return_value
              .collection.return_value
              .document.return_value) = mock_doc_ref

    return mock_db, mock_doc_ref, mock_snap


# ── Health check ──────────────────────────────────────────────────────────────

@pytest.mark.unit
def test_health(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "healthy"
    assert resp.json()["service"] == "settlement-financial"


# ── Preview endpoint ──────────────────────────────────────────────────────────

@pytest.mark.unit
def test_calculate_preview_success(client):
    resp = client.post("/api/v1/settlement/calculate", json=PREVIEW_PAYLOAD)
    assert resp.status_code == 200
    data = resp.json()
    assert data["gross_award"] == "500000.00"
    result = data["result"]
    assert result["attorney_fee_amount"] == "166650.00"
    assert result["total_expenses"] == "4350.00"
    assert result["total_liens"] == "12000.00"
    assert result["total_loans"] == "5000.00"
    assert result["total_deductions"] == "188000.00"
    assert result["net_to_client"] == "312000.00"


@pytest.mark.unit
def test_calculate_preview_negative_net_returns_422(client):
    payload = {
        "gross_award": "1000.00",
        "attorney_fee_pct": "50.00",
        "liens": [{"description": "Huge lien", "amount": "600.00"}],
    }
    resp = client.post("/api/v1/settlement/calculate", json=payload)
    assert resp.status_code == 422
    detail = resp.json()["detail"]
    detail_str = detail if isinstance(detail, str) else str(detail)
    assert "negative" in detail_str.lower()


@pytest.mark.unit
def test_calculate_preview_invalid_fee_pct(client):
    payload = {**PREVIEW_PAYLOAD, "attorney_fee_pct": "101.00"}
    resp = client.post("/api/v1/settlement/calculate", json=payload)
    assert resp.status_code == 422


@pytest.mark.unit
def test_calculate_preview_negative_gross_fails(client):
    payload = {**PREVIEW_PAYLOAD, "gross_award": "-1.00"}
    resp = client.post("/api/v1/settlement/calculate", json=payload)
    assert resp.status_code == 422


@pytest.mark.unit
def test_calculate_preview_zero_gross_fails(client):
    payload = {**PREVIEW_PAYLOAD, "gross_award": "0.00"}
    resp = client.post("/api/v1/settlement/calculate", json=payload)
    assert resp.status_code == 422


@pytest.mark.unit
def test_calculate_preview_negative_line_item_fails(client):
    payload = {
        **PREVIEW_PAYLOAD,
        "case_expenses": [{"description": "Bad", "amount": "-100.00"}],
    }
    resp = client.post("/api/v1/settlement/calculate", json=payload)
    assert resp.status_code == 422


@pytest.mark.unit
def test_calculate_preview_empty_line_items(client):
    payload = {"gross_award": "100000.00", "attorney_fee_pct": "33.00"}
    resp = client.post("/api/v1/settlement/calculate", json=payload)
    assert resp.status_code == 200
    assert resp.json()["result"]["total_expenses"] == "0.00"
    assert resp.json()["result"]["total_liens"] == "0.00"
    assert resp.json()["result"]["total_loans"] == "0.00"


# ── Save calculation endpoint ─────────────────────────────────────────────────

@pytest.mark.unit
def test_save_calculation_success(client):
    calc_id = str(uuid.uuid4())
    case_id = "ZAD-2024-01-0001"
    calc_doc = _make_calc_doc(calc_id, case_id)
    mock_db, _, _ = _mock_db_for_calc(calc_id, case_id, calc_doc)

    with patch("main.get_db", return_value=mock_db):
        resp = client.post(
            f"/api/v1/settlement/cases/{case_id}/calculations",
            json=PREVIEW_PAYLOAD,
        )

    assert resp.status_code == 201
    data = resp.json()
    assert data["case_id"] == case_id
    assert data["result"]["net_to_client"] == "312000.00"
    assert data["result"]["attorney_fee_amount"] == "166650.00"


@pytest.mark.unit
def test_save_calculation_negative_net_returns_422(client):
    payload = {
        "gross_award": "100.00",
        "attorney_fee_pct": "50.00",
        "liens": [{"description": "Big lien", "amount": "60.00"}],
    }
    resp = client.post("/api/v1/settlement/cases/ZAD-2024-01-0001/calculations", json=payload)
    assert resp.status_code == 422


# ── Get calculation by ID ─────────────────────────────────────────────────────

@pytest.mark.unit
def test_get_calculation_found(client):
    calc_id = str(uuid.uuid4())
    case_id = "ZAD-2024-01-0001"
    calc_doc = _make_calc_doc(calc_id, case_id)
    mock_db, _, mock_snap = _mock_db_for_calc(calc_id, case_id, calc_doc)
    mock_snap.id = calc_id

    with patch("main.get_db", return_value=mock_db):
        resp = client.get(f"/api/v1/settlement/cases/{case_id}/calculations/{calc_id}")

    assert resp.status_code == 200
    assert resp.json()["case_id"] == case_id


@pytest.mark.unit
def test_get_calculation_not_found(client):
    mock_snap = MagicMock()
    mock_snap.exists = False

    mock_doc_ref = MagicMock()
    mock_doc_ref.get = AsyncMock(return_value=mock_snap)

    mock_db = MagicMock()
    (mock_db.collection.return_value
              .document.return_value
              .collection.return_value
              .document.return_value) = mock_doc_ref

    with patch("main.get_db", return_value=mock_db):
        resp = client.get("/api/v1/settlement/cases/ZAD-2024-01-0001/calculations/does-not-exist")

    assert resp.status_code == 404


# ── History / list endpoint ───────────────────────────────────────────────────

@pytest.mark.unit
def test_list_calculations(client):
    case_id = "ZAD-2024-01-0001"
    calc_id = str(uuid.uuid4())
    calc_doc = _make_calc_doc(calc_id, case_id)

    mock_doc = MagicMock()
    mock_doc.id = calc_id
    mock_doc.to_dict.return_value = calc_doc

    async def _stream_one(*args, **kwargs):
        yield mock_doc

    mock_coll = MagicMock()
    mock_coll.stream = _stream_one

    mock_db = MagicMock()
    (mock_db.collection.return_value
              .document.return_value
              .collection.return_value) = mock_coll

    with patch("main.get_db", return_value=mock_db):
        resp = client.get(f"/api/v1/settlement/cases/{case_id}/calculations")

    assert resp.status_code == 200
    data = resp.json()
    assert data["case_id"] == case_id
    assert isinstance(data["calculations"], list)


# ── Delete endpoint ───────────────────────────────────────────────────────────

@pytest.mark.unit
def test_delete_calculation_success(client):
    calc_id = str(uuid.uuid4())
    case_id = "ZAD-2024-01-0001"

    mock_snap = MagicMock()
    mock_snap.exists = True

    mock_doc_ref = MagicMock()
    mock_doc_ref.get = AsyncMock(return_value=mock_snap)
    mock_doc_ref.delete = AsyncMock()

    mock_db = MagicMock()
    (mock_db.collection.return_value
              .document.return_value
              .collection.return_value
              .document.return_value) = mock_doc_ref

    with patch("main.get_db", return_value=mock_db):
        resp = client.delete(f"/api/v1/settlement/cases/{case_id}/calculations/{calc_id}")

    assert resp.status_code == 204


@pytest.mark.unit
def test_delete_calculation_not_found(client):
    mock_snap = MagicMock()
    mock_snap.exists = False

    mock_doc_ref = MagicMock()
    mock_doc_ref.get = AsyncMock(return_value=mock_snap)

    mock_db = MagicMock()
    (mock_db.collection.return_value
              .document.return_value
              .collection.return_value
              .document.return_value) = mock_doc_ref

    with patch("main.get_db", return_value=mock_db):
        resp = client.delete("/api/v1/settlement/cases/ZAD-2024-01-0001/calculations/ghost-id")

    assert resp.status_code == 404


# ── Case inputs endpoints ─────────────────────────────────────────────────────

INPUTS_PAYLOAD = {
    "gross_award": "500000.00",
    "attorney_fee_pct": "33.33",
    "case_expenses": [
        {"description": "Medical records", "amount": "850.00"},
        {"description": "Expert witness", "amount": "3500.00"},
    ],
    "liens": [{"description": "Medicare lien", "amount": "12000.00"}],
    "client_loans": [{"description": "Case advance", "amount": "5000.00"}],
    "notes": "Pre-stored inputs",
}


@pytest.mark.unit
def test_upsert_case_inputs_success(client):
    case_id = "ZAD-2024-01-0001"
    inputs_doc = _make_inputs_doc(case_id)
    mock_db, _, _ = _mock_db_for_inputs(case_id, inputs_doc)

    with patch("main.get_db", return_value=mock_db):
        resp = client.put(f"/api/v1/settlement/cases/{case_id}/inputs", json=INPUTS_PAYLOAD)

    assert resp.status_code == 200
    data = resp.json()
    assert data["case_id"] == case_id
    assert data["gross_award"] == "500000.00"
    assert data["attorney_fee_pct"] == "33.33"


@pytest.mark.unit
def test_get_case_inputs_found(client):
    case_id = "ZAD-2024-01-0001"
    inputs_doc = _make_inputs_doc(case_id)
    mock_db, _, _ = _mock_db_for_inputs(case_id, inputs_doc)

    with patch("main.get_db", return_value=mock_db):
        resp = client.get(f"/api/v1/settlement/cases/{case_id}/inputs")

    assert resp.status_code == 200
    assert resp.json()["case_id"] == case_id
    assert resp.json()["gross_award"] == "500000.00"


@pytest.mark.unit
def test_get_case_inputs_not_found(client):
    mock_snap = MagicMock()
    mock_snap.exists = False

    mock_doc_ref = MagicMock()
    mock_doc_ref.get = AsyncMock(return_value=mock_snap)

    mock_db = MagicMock()
    (mock_db.collection.return_value
              .document.return_value
              .collection.return_value
              .document.return_value) = mock_doc_ref

    with patch("main.get_db", return_value=mock_db):
        resp = client.get("/api/v1/settlement/cases/UNKNOWN-CASE/inputs")

    assert resp.status_code == 404
    assert "UNKNOWN-CASE" in resp.json()["detail"]


@pytest.mark.unit
def test_calculate_from_inputs_success(client):
    case_id = "ZAD-2024-01-0001"
    calc_id = str(uuid.uuid4())
    inputs_doc = _make_inputs_doc(case_id)
    calc_doc = _make_calc_doc(calc_id, case_id)

    mock_inputs_snap = MagicMock()
    mock_inputs_snap.exists = True
    mock_inputs_snap.to_dict.return_value = inputs_doc

    mock_calc_snap = MagicMock()
    mock_calc_snap.to_dict.return_value = calc_doc

    # _inputs_ref and _calcs_ref.document(uuid) share the same 4-level mock chain.
    # Use side_effect so first .get() → inputs snap, second .get() → calc snap.
    mock_shared_ref = MagicMock()
    mock_shared_ref.set = AsyncMock()
    mock_shared_ref.get = AsyncMock(side_effect=[mock_inputs_snap, mock_calc_snap])

    mock_db = MagicMock()
    (mock_db.collection.return_value
              .document.return_value
              .collection.return_value
              .document.return_value) = mock_shared_ref

    with patch("main.get_db", return_value=mock_db):
        resp = client.post(f"/api/v1/settlement/cases/{case_id}/calculate")

    assert resp.status_code == 201
    data = resp.json()
    assert data["case_id"] == case_id
    assert data["result"]["net_to_client"] == "312000.00"


@pytest.mark.unit
def test_calculate_from_inputs_no_inputs_returns_404(client):
    mock_snap = MagicMock()
    mock_snap.exists = False

    mock_doc_ref = MagicMock()
    mock_doc_ref.get = AsyncMock(return_value=mock_snap)

    mock_db = MagicMock()
    (mock_db.collection.return_value
              .document.return_value
              .collection.return_value
              .document.return_value) = mock_doc_ref

    with patch("main.get_db", return_value=mock_db):
        resp = client.post("/api/v1/settlement/cases/NO-INPUTS-CASE/calculate")

    assert resp.status_code == 404


# ── OpenAPI docs reachable ────────────────────────────────────────────────────

@pytest.mark.unit
def test_openapi_schema_reachable(client):
    resp = client.get("/openapi.json")
    assert resp.status_code == 200
    schema = resp.json()
    assert "settlement" in schema["info"]["title"].lower()
    paths = schema["paths"]
    assert "/api/v1/settlement/calculate" in paths
    assert "/api/v1/settlement/cases/{case_id}/calculations" in paths
    assert "/api/v1/settlement/cases/{case_id}/calculations/latest" in paths
    assert "/api/v1/settlement/cases/{case_id}/calculations/{calculation_id}" in paths
    assert "/api/v1/settlement/cases/{case_id}/inputs" in paths
    assert "/api/v1/settlement/cases/{case_id}/calculate" in paths
    assert "/api/v1/settlement/cases/{case_id}/expenses" in paths
    assert "/api/v1/settlement/cases/{case_id}/liens" in paths
    assert "/api/v1/settlement/cases/{case_id}/loans" in paths
    assert "/api/v1/settlement/cases/{case_id}/disbursements" in paths


# ── 2.6.1 Expense helpers ─────────────────────────────────────────────────────

def _make_expense_doc(expense_id, case_id):
    return {
        "expenseId":    expense_id,
        "caseId":       case_id,
        "description":  "Medical records fee",
        "amount":       850.0,
        "category":     "Medical Records",
        "date":         datetime(2026, 4, 1, tzinfo=timezone.utc),
        "addedBy":      "user-uid-123",
        "addedAt":      datetime(2026, 4, 17, 12, 0, 0, tzinfo=timezone.utc),
        "qbExpenseId":  None,
        "qbSyncStatus": None,
        "qbSyncedAt":   None,
    }


def _mock_db_for_expense(expense_id, case_id, expense_doc):
    # settlement/expenses is now a single document with an items array
    mock_snap = MagicMock()
    mock_snap.to_dict.return_value = {"items": [expense_doc]}
    mock_snap.exists = True

    mock_doc_ref = MagicMock()
    mock_doc_ref.set = AsyncMock()
    mock_doc_ref.get = AsyncMock(return_value=mock_snap)

    mock_db = MagicMock()
    # cases/{caseId}/settlement/expenses  (4-level chain)
    (mock_db.collection.return_value
              .document.return_value
              .collection.return_value
              .document.return_value) = mock_doc_ref

    return mock_db, mock_doc_ref, mock_snap


# ── 2.6.1 Expense tests ───────────────────────────────────────────────────────

EXPENSE_PAYLOAD = {
    "description": "Medical records fee",
    "amount": "850.00",
    "category": "Medical Records",
    "date": "2026-04-01T00:00:00Z",
    "added_by": "user-uid-123",
}


@pytest.mark.unit
def test_add_expense_success(client):
    expense_id = str(uuid.uuid4())
    case_id    = "ZAD-2026-04-0001"
    expense_doc = _make_expense_doc(expense_id, case_id)
    mock_db, _, _ = _mock_db_for_expense(expense_id, case_id, expense_doc)

    with patch("main.get_db", return_value=mock_db):
        resp = client.post(
            f"/api/v1/settlement/cases/{case_id}/expenses",
            json=EXPENSE_PAYLOAD,
        )

    assert resp.status_code == 201
    data = resp.json()
    assert data["case_id"] == case_id
    assert data["description"] == "Medical records fee"
    assert data["amount"] == "850.00"
    assert data["category"] == "Medical Records"


@pytest.mark.unit
def test_add_expense_invalid_category(client):
    payload = {**EXPENSE_PAYLOAD, "category": "Bad Category"}
    resp = client.post("/api/v1/settlement/cases/ZAD-2026-04-0001/expenses", json=payload)
    assert resp.status_code == 422


@pytest.mark.unit
def test_add_expense_zero_amount_fails(client):
    payload = {**EXPENSE_PAYLOAD, "amount": "0.00"}
    resp = client.post("/api/v1/settlement/cases/ZAD-2026-04-0001/expenses", json=payload)
    assert resp.status_code == 422


@pytest.mark.unit
def test_list_expenses_success(client):
    case_id    = "ZAD-2026-04-0001"
    expense_id = str(uuid.uuid4())
    expense_doc = _make_expense_doc(expense_id, case_id)

    mock_snap = MagicMock()
    mock_snap.exists = True
    mock_snap.to_dict.return_value = {"items": [expense_doc]}

    mock_doc_ref = MagicMock()
    mock_doc_ref.get = AsyncMock(return_value=mock_snap)

    mock_db = MagicMock()
    (mock_db.collection.return_value
              .document.return_value
              .collection.return_value
              .document.return_value) = mock_doc_ref

    with patch("main.get_db", return_value=mock_db):
        resp = client.get(f"/api/v1/settlement/cases/{case_id}/expenses")

    assert resp.status_code == 200
    data = resp.json()
    assert data["case_id"] == case_id
    assert data["total"] == 1
    assert data["expenses"][0]["amount"] == "850.00"


@pytest.mark.unit
def test_delete_expense_success(client):
    expense_id  = str(uuid.uuid4())
    case_id     = "ZAD-2026-04-0001"
    expense_doc = _make_expense_doc(expense_id, case_id)

    mock_snap = MagicMock()
    mock_snap.exists = True
    mock_snap.to_dict.return_value = {"items": [expense_doc]}

    mock_doc_ref = MagicMock()
    mock_doc_ref.get = AsyncMock(return_value=mock_snap)
    mock_doc_ref.set = AsyncMock()

    mock_db = MagicMock()
    (mock_db.collection.return_value
              .document.return_value
              .collection.return_value
              .document.return_value) = mock_doc_ref

    with patch("main.get_db", return_value=mock_db):
        resp = client.delete(f"/api/v1/settlement/cases/{case_id}/expenses/{expense_id}")

    assert resp.status_code == 204


@pytest.mark.unit
def test_delete_expense_not_found(client):
    mock_snap = MagicMock()
    mock_snap.exists = True
    mock_snap.to_dict.return_value = {"items": []}  # empty — expense not present

    mock_doc_ref = MagicMock()
    mock_doc_ref.get = AsyncMock(return_value=mock_snap)

    mock_db = MagicMock()
    (mock_db.collection.return_value
              .document.return_value
              .collection.return_value
              .document.return_value) = mock_doc_ref

    with patch("main.get_db", return_value=mock_db):
        resp = client.delete("/api/v1/settlement/cases/ZAD-2026-04-0001/expenses/no-such-id")

    assert resp.status_code == 404


# ── 2.6.2 Lien helpers ────────────────────────────────────────────────────────

def _make_lien_doc(lien_id, case_id):
    return {
        "lienId":             lien_id,
        "caseId":             case_id,
        "lienholder":         "Medicare",
        "amount":             12000.0,
        "satisfactionStatus": "Outstanding",
        "satisfactionDate":   None,
        "notes":              "Pending reduction",
        "addedBy":            "user-uid-123",
        "addedAt":            datetime(2026, 4, 17, 12, 0, 0, tzinfo=timezone.utc),
    }


def _mock_db_for_lien(lien_id, case_id, lien_doc):
    mock_snap = MagicMock()
    mock_snap.to_dict.return_value = {"items": [lien_doc]}
    mock_snap.exists = True

    mock_doc_ref = MagicMock()
    mock_doc_ref.set = AsyncMock()
    mock_doc_ref.get = AsyncMock(return_value=mock_snap)

    mock_db = MagicMock()
    # cases/{caseId}/settlement/liens  (4-level chain)
    (mock_db.collection.return_value
              .document.return_value
              .collection.return_value
              .document.return_value) = mock_doc_ref

    return mock_db, mock_doc_ref, mock_snap


# ── 2.6.2 Lien tests ─────────────────────────────────────────────────────────

LIEN_PAYLOAD = {
    "lienholder":          "Medicare",
    "amount":              "12000.00",
    "satisfaction_status": "Outstanding",
    "notes":               "Pending reduction",
    "added_by":            "user-uid-123",
}


@pytest.mark.unit
def test_add_lien_success(client):
    lien_id  = str(uuid.uuid4())
    case_id  = "ZAD-2026-04-0001"
    lien_doc = _make_lien_doc(lien_id, case_id)
    mock_db, _, _ = _mock_db_for_lien(lien_id, case_id, lien_doc)

    with patch("main.get_db", return_value=mock_db):
        resp = client.post(
            f"/api/v1/settlement/cases/{case_id}/liens",
            json=LIEN_PAYLOAD,
        )

    assert resp.status_code == 201
    data = resp.json()
    assert data["case_id"] == case_id
    assert data["lienholder"] == "Medicare"
    assert data["amount"] == "12000.00"
    assert data["satisfaction_status"] == "Outstanding"


@pytest.mark.unit
def test_add_lien_zero_amount_fails(client):
    payload = {**LIEN_PAYLOAD, "amount": "0.00"}
    resp = client.post("/api/v1/settlement/cases/ZAD-2026-04-0001/liens", json=payload)
    assert resp.status_code == 422


@pytest.mark.unit
def test_list_liens_success(client):
    case_id = "ZAD-2026-04-0001"
    lien_id = str(uuid.uuid4())
    lien_doc = _make_lien_doc(lien_id, case_id)

    mock_doc = MagicMock()
    mock_doc.id = lien_id
    mock_doc.to_dict.return_value = lien_doc

    async def _stream_one(*args, **kwargs):
        yield mock_doc

    mock_coll = MagicMock()
    mock_coll.stream = _stream_one

    mock_snap = MagicMock()
    mock_snap.exists = True
    mock_snap.to_dict.return_value = {"items": [lien_doc]}

    mock_doc_ref = MagicMock()
    mock_doc_ref.get = AsyncMock(return_value=mock_snap)

    mock_db = MagicMock()
    (mock_db.collection.return_value
              .document.return_value
              .collection.return_value
              .document.return_value) = mock_doc_ref

    with patch("main.get_db", return_value=mock_db):
        resp = client.get(f"/api/v1/settlement/cases/{case_id}/liens")

    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1
    assert data["liens"][0]["lienholder"] == "Medicare"


@pytest.mark.unit
def test_update_lien_success(client):
    lien_id  = str(uuid.uuid4())
    case_id  = "ZAD-2026-04-0001"
    lien_doc = _make_lien_doc(lien_id, case_id)
    lien_doc["satisfactionStatus"] = "Satisfied"
    mock_db, _, _ = _mock_db_for_lien(lien_id, case_id, lien_doc)

    with patch("main.get_db", return_value=mock_db):
        resp = client.patch(
            f"/api/v1/settlement/cases/{case_id}/liens/{lien_id}",
            json={"satisfaction_status": "Satisfied"},
        )

    assert resp.status_code == 200
    assert resp.json()["satisfaction_status"] == "Satisfied"


@pytest.mark.unit
def test_delete_lien_success(client):
    lien_id  = str(uuid.uuid4())
    case_id  = "ZAD-2026-04-0001"
    lien_doc = _make_lien_doc(lien_id, case_id)

    mock_snap = MagicMock()
    mock_snap.exists = True
    mock_snap.to_dict.return_value = {"items": [lien_doc]}

    mock_doc_ref = MagicMock()
    mock_doc_ref.get = AsyncMock(return_value=mock_snap)
    mock_doc_ref.set = AsyncMock()

    mock_db = MagicMock()
    (mock_db.collection.return_value
              .document.return_value
              .collection.return_value
              .document.return_value) = mock_doc_ref

    with patch("main.get_db", return_value=mock_db):
        resp = client.delete(f"/api/v1/settlement/cases/{case_id}/liens/{lien_id}")

    assert resp.status_code == 204


# ── 2.6.3 Loan helpers ────────────────────────────────────────────────────────

def _make_loan_doc(loan_id, case_id):
    return {
        "loanId":             loan_id,
        "caseId":             case_id,
        "lender":             "LawCash Advances",
        "amount":             5000.0,
        "satisfactionStatus": "Outstanding",
        "satisfactionDate":   None,
        "addedBy":            "user-uid-123",
        "addedAt":            datetime(2026, 4, 17, 12, 0, 0, tzinfo=timezone.utc),
    }


def _mock_db_for_loan(loan_id, case_id, loan_doc):
    mock_snap = MagicMock()
    mock_snap.to_dict.return_value = {"items": [loan_doc]}
    mock_snap.exists = True

    mock_doc_ref = MagicMock()
    mock_doc_ref.set = AsyncMock()
    mock_doc_ref.get = AsyncMock(return_value=mock_snap)

    mock_db = MagicMock()
    # cases/{caseId}/settlement/loans  (4-level chain)
    (mock_db.collection.return_value
              .document.return_value
              .collection.return_value
              .document.return_value) = mock_doc_ref

    return mock_db, mock_doc_ref, mock_snap


# ── 2.6.3 Loan tests ─────────────────────────────────────────────────────────

LOAN_PAYLOAD = {
    "lender":              "LawCash Advances",
    "amount":              "5000.00",
    "satisfaction_status": "Outstanding",
    "added_by":            "user-uid-123",
}


@pytest.mark.unit
def test_add_loan_success(client):
    loan_id  = str(uuid.uuid4())
    case_id  = "ZAD-2026-04-0001"
    loan_doc = _make_loan_doc(loan_id, case_id)
    mock_db, _, _ = _mock_db_for_loan(loan_id, case_id, loan_doc)

    with patch("main.get_db", return_value=mock_db):
        resp = client.post(
            f"/api/v1/settlement/cases/{case_id}/loans",
            json=LOAN_PAYLOAD,
        )

    assert resp.status_code == 201
    data = resp.json()
    assert data["case_id"] == case_id
    assert data["lender"] == "LawCash Advances"
    assert data["amount"] == "5000.00"
    assert data["satisfaction_status"] == "Outstanding"


@pytest.mark.unit
def test_add_loan_zero_amount_fails(client):
    payload = {**LOAN_PAYLOAD, "amount": "0.00"}
    resp = client.post("/api/v1/settlement/cases/ZAD-2026-04-0001/loans", json=payload)
    assert resp.status_code == 422


@pytest.mark.unit
def test_list_loans_success(client):
    case_id = "ZAD-2026-04-0001"
    loan_id = str(uuid.uuid4())
    loan_doc = _make_loan_doc(loan_id, case_id)

    mock_doc = MagicMock()
    mock_doc.id = loan_id
    mock_doc.to_dict.return_value = loan_doc

    async def _stream_one(*args, **kwargs):
        yield mock_doc

    mock_coll = MagicMock()
    mock_coll.stream = _stream_one

    mock_snap = MagicMock()
    mock_snap.exists = True
    mock_snap.to_dict.return_value = {"items": [loan_doc]}

    mock_doc_ref = MagicMock()
    mock_doc_ref.get = AsyncMock(return_value=mock_snap)

    mock_db = MagicMock()
    (mock_db.collection.return_value
              .document.return_value
              .collection.return_value
              .document.return_value) = mock_doc_ref

    with patch("main.get_db", return_value=mock_db):
        resp = client.get(f"/api/v1/settlement/cases/{case_id}/loans")

    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1
    assert data["loans"][0]["lender"] == "LawCash Advances"


@pytest.mark.unit
def test_update_loan_success(client):
    loan_id  = str(uuid.uuid4())
    case_id  = "ZAD-2026-04-0001"
    loan_doc = _make_loan_doc(loan_id, case_id)
    loan_doc["satisfactionStatus"] = "Satisfied"
    mock_db, _, _ = _mock_db_for_loan(loan_id, case_id, loan_doc)

    with patch("main.get_db", return_value=mock_db):
        resp = client.patch(
            f"/api/v1/settlement/cases/{case_id}/loans/{loan_id}",
            json={"satisfaction_status": "Satisfied"},
        )

    assert resp.status_code == 200
    assert resp.json()["satisfaction_status"] == "Satisfied"


@pytest.mark.unit
def test_delete_loan_success(client):
    loan_id  = str(uuid.uuid4())
    case_id  = "ZAD-2026-04-0001"
    loan_doc = _make_loan_doc(loan_id, case_id)

    mock_snap = MagicMock()
    mock_snap.exists = True
    mock_snap.to_dict.return_value = {"items": [loan_doc]}

    mock_doc_ref = MagicMock()
    mock_doc_ref.get = AsyncMock(return_value=mock_snap)
    mock_doc_ref.set = AsyncMock()

    mock_db = MagicMock()
    (mock_db.collection.return_value
              .document.return_value
              .collection.return_value
              .document.return_value) = mock_doc_ref

    with patch("main.get_db", return_value=mock_db):
        resp = client.delete(f"/api/v1/settlement/cases/{case_id}/loans/{loan_id}")

    assert resp.status_code == 204


# ── 2.6.4 Disbursement helpers ────────────────────────────────────────────────

def _make_disbursement_doc(disbursement_id, case_id):
    return {
        "disbursementId":  disbursement_id,
        "caseId":          case_id,
        "payee":           "John Smith",
        "payeeType":       "Client",
        "amount":          312000.0,
        "date":            datetime(2026, 4, 20, tzinfo=timezone.utc),
        "method":          "Check",
        "referenceNumber": "CHK-00123",
        "status":          "Pending",
        "qbPaymentId":     None,
        "qbSyncStatus":    None,
        "processedBy":     "user-uid-123",
        "processedAt":     datetime(2026, 4, 20, 10, 0, 0, tzinfo=timezone.utc),
    }


def _mock_db_for_disbursement(disbursement_id, case_id, disbursement_doc):
    mock_snap = MagicMock()
    mock_snap.to_dict.return_value = {"items": [disbursement_doc]}
    mock_snap.exists = True

    mock_doc_ref = MagicMock()
    mock_doc_ref.set = AsyncMock()
    mock_doc_ref.get = AsyncMock(return_value=mock_snap)

    mock_db = MagicMock()
    # cases/{caseId}/settlement/disbursements  (4-level chain)
    (mock_db.collection.return_value
              .document.return_value
              .collection.return_value
              .document.return_value) = mock_doc_ref

    return mock_db, mock_doc_ref, mock_snap


# ── 2.6.4 Disbursement tests ──────────────────────────────────────────────────

DISBURSEMENT_PAYLOAD = {
    "payee":            "John Smith",
    "payee_type":       "Client",
    "amount":           "312000.00",
    "date":             "2026-04-20T00:00:00Z",
    "method":           "Check",
    "reference_number": "CHK-00123",
    "status":           "Pending",
    "processed_by":     "user-uid-123",
}


@pytest.mark.unit
def test_add_disbursement_success(client):
    disbursement_id = str(uuid.uuid4())
    case_id         = "ZAD-2026-04-0001"
    disbursement_doc = _make_disbursement_doc(disbursement_id, case_id)
    mock_db, _, _ = _mock_db_for_disbursement(disbursement_id, case_id, disbursement_doc)

    with patch("main.get_db", return_value=mock_db):
        resp = client.post(
            f"/api/v1/settlement/cases/{case_id}/disbursements",
            json=DISBURSEMENT_PAYLOAD,
        )

    assert resp.status_code == 201
    data = resp.json()
    assert data["case_id"] == case_id
    assert data["payee"] == "John Smith"
    assert data["payee_type"] == "Client"
    assert data["amount"] == "312000.00"
    assert data["method"] == "Check"
    assert data["status"] == "Pending"


@pytest.mark.unit
def test_add_disbursement_invalid_payee_type(client):
    payload = {**DISBURSEMENT_PAYLOAD, "payee_type": "Unknown"}
    resp = client.post("/api/v1/settlement/cases/ZAD-2026-04-0001/disbursements", json=payload)
    assert resp.status_code == 422


@pytest.mark.unit
def test_add_disbursement_zero_amount_fails(client):
    payload = {**DISBURSEMENT_PAYLOAD, "amount": "0.00"}
    resp = client.post("/api/v1/settlement/cases/ZAD-2026-04-0001/disbursements", json=payload)
    assert resp.status_code == 422


@pytest.mark.unit
def test_list_disbursements_success(client):
    case_id         = "ZAD-2026-04-0001"
    disbursement_id = str(uuid.uuid4())
    disbursement_doc = _make_disbursement_doc(disbursement_id, case_id)

    mock_doc = MagicMock()
    mock_doc.id = disbursement_id
    mock_doc.to_dict.return_value = disbursement_doc

    async def _stream_one(*args, **kwargs):
        yield mock_doc

    mock_coll = MagicMock()
    mock_coll.stream = _stream_one

    mock_snap = MagicMock()
    mock_snap.exists = True
    mock_snap.to_dict.return_value = {"items": [disbursement_doc]}

    mock_doc_ref = MagicMock()
    mock_doc_ref.get = AsyncMock(return_value=mock_snap)

    mock_db = MagicMock()
    (mock_db.collection.return_value
              .document.return_value
              .collection.return_value
              .document.return_value) = mock_doc_ref

    with patch("main.get_db", return_value=mock_db):
        resp = client.get(f"/api/v1/settlement/cases/{case_id}/disbursements")

    assert resp.status_code == 200
    data = resp.json()
    assert data["case_id"] == case_id
    assert data["total"] == 1
    assert data["disbursements"][0]["payee"] == "John Smith"
    assert data["disbursements"][0]["amount"] == "312000.00"
