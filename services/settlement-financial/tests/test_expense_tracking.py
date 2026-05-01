"""
tests/test_expense_tracking.py — Tests for expense CRUD extensions.

Covers
------
  - PATCH  update_expense (success, not-found, audit trail)
  - PUT    attach_receipt (success, not-found)
  - DELETE remove_receipt (success, not-found)
  - GET    get_expense_categories
  - PUT    upsert_expense_categories
  - GET    list_expenses with totals
  - Paid / unpaid status tracking
"""
from __future__ import annotations

import os
import sys
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


# ── App fixture ───────────────────────────────────────────────────────────────

@pytest.fixture()
def client():
    with patch("services.firestore_client.get_db"), patch("main.get_db"):
        from main import app
        return TestClient(app)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_expense(expense_id, case_id, **overrides):
    base = {
        "expenseId":       expense_id,
        "caseId":          case_id,
        "description":     "Medical records fee",
        "amount":          850.0,
        "category":        "Medical Records",
        "vendor":          None,
        "date":            datetime(2026, 4, 1, tzinfo=timezone.utc),
        "paidStatus":      "Pending",
        "addedBy":         "user-uid-123",
        "addedAt":         datetime(2026, 4, 17, 12, 0, 0, tzinfo=timezone.utc),
        "updatedAt":       None,
        "updatedBy":       None,
        "receiptUrl":      None,
        "receiptFilename": None,
        "changeLog":       [],
        "qbExpenseId":     None,
        "qbSyncStatus":    None,
        "qbSyncedAt":      None,
    }
    base.update(overrides)
    return base


def _mock_expenses_db(case_id, items: list):
    """Return a mock_db whose 4-level chain resolves to a doc containing items."""
    mock_snap = MagicMock()
    mock_snap.exists = True
    mock_snap.to_dict.return_value = {"items": items}

    mock_doc_ref = MagicMock()
    mock_doc_ref.get = AsyncMock(return_value=mock_snap)
    mock_doc_ref.set = AsyncMock()

    mock_db = MagicMock()
    (mock_db.collection.return_value
              .document.return_value
              .collection.return_value
              .document.return_value) = mock_doc_ref

    return mock_db, mock_doc_ref


# ── PATCH update_expense ──────────────────────────────────────────────────────

@pytest.mark.unit
def test_update_expense_success(client):
    case_id    = "ZAD-2026-04-0001"
    expense_id = str(uuid.uuid4())
    item       = _make_expense(expense_id, case_id)
    mock_db, _ = _mock_expenses_db(case_id, [item])

    payload = {"description": "Updated medical records", "paid_status": "Paid", "updated_by": "admin"}

    with patch("main.get_db", return_value=mock_db):
        resp = client.patch(
            f"/api/v1/settlement/cases/{case_id}/expenses/{expense_id}",
            json=payload,
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["description"] == "Updated medical records"
    assert data["paid_status"] == "Paid"
    assert data["expense_id"] == expense_id


@pytest.mark.unit
def test_update_expense_records_audit_trail(client):
    case_id    = "ZAD-2026-04-0001"
    expense_id = str(uuid.uuid4())
    item       = _make_expense(expense_id, case_id)
    mock_db, mock_doc_ref = _mock_expenses_db(case_id, [item])

    payload = {"amount": "1200.00", "updated_by": "admin-uid"}

    with patch("main.get_db", return_value=mock_db):
        resp = client.patch(
            f"/api/v1/settlement/cases/{case_id}/expenses/{expense_id}",
            json=payload,
        )

    assert resp.status_code == 200
    # change_log should have one entry
    data = resp.json()
    assert len(data["change_log"]) == 1
    assert "amount" in data["change_log"][0]["changes"]
    assert data["change_log"][0]["changed_by"] == "admin-uid"


@pytest.mark.unit
def test_update_expense_not_found(client):
    case_id = "ZAD-2026-04-0001"
    # empty items — expense doesn't exist
    mock_db, _ = _mock_expenses_db(case_id, [])

    with patch("main.get_db", return_value=mock_db):
        resp = client.patch(
            f"/api/v1/settlement/cases/{case_id}/expenses/ghost-id",
            json={"description": "X"},
        )

    assert resp.status_code == 404


@pytest.mark.unit
def test_update_expense_no_change_no_log_entry(client):
    case_id    = "ZAD-2026-04-0001"
    expense_id = str(uuid.uuid4())
    item       = _make_expense(expense_id, case_id)
    mock_db, _ = _mock_expenses_db(case_id, [item])

    # Send same description — no diff, no audit entry
    payload = {"description": "Medical records fee"}

    with patch("main.get_db", return_value=mock_db):
        resp = client.patch(
            f"/api/v1/settlement/cases/{case_id}/expenses/{expense_id}",
            json=payload,
        )

    assert resp.status_code == 200
    assert resp.json()["change_log"] == []


# ── Paid / unpaid status ──────────────────────────────────────────────────────

@pytest.mark.unit
def test_mark_expense_paid(client):
    case_id    = "ZAD-2026-04-0001"
    expense_id = str(uuid.uuid4())
    item       = _make_expense(expense_id, case_id, paidStatus="Pending")
    mock_db, _ = _mock_expenses_db(case_id, [item])

    with patch("main.get_db", return_value=mock_db):
        resp = client.patch(
            f"/api/v1/settlement/cases/{case_id}/expenses/{expense_id}",
            json={"paid_status": "Paid"},
        )

    assert resp.status_code == 200
    assert resp.json()["paid_status"] == "Paid"


# ── PUT attach_receipt ────────────────────────────────────────────────────────

@pytest.mark.unit
def test_attach_receipt_success(client):
    case_id    = "ZAD-2026-04-0001"
    expense_id = str(uuid.uuid4())
    item       = _make_expense(expense_id, case_id)
    mock_db, _ = _mock_expenses_db(case_id, [item])

    payload = {
        "receipt_url":      "https://storage.googleapis.com/bucket/receipt.pdf",
        "receipt_filename": "receipt.pdf",
    }

    with patch("main.get_db", return_value=mock_db):
        resp = client.put(
            f"/api/v1/settlement/cases/{case_id}/expenses/{expense_id}/receipt",
            json=payload,
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["receipt_url"]      == payload["receipt_url"]
    assert data["receipt_filename"] == payload["receipt_filename"]


@pytest.mark.unit
def test_attach_receipt_not_found(client):
    case_id = "ZAD-2026-04-0001"
    mock_db, _ = _mock_expenses_db(case_id, [])

    with patch("main.get_db", return_value=mock_db):
        resp = client.put(
            f"/api/v1/settlement/cases/{case_id}/expenses/ghost-id/receipt",
            json={"receipt_url": "https://example.com/r.pdf", "receipt_filename": "r.pdf"},
        )

    assert resp.status_code == 404


# ── DELETE remove_receipt ─────────────────────────────────────────────────────

@pytest.mark.unit
def test_remove_receipt_success(client):
    case_id    = "ZAD-2026-04-0001"
    expense_id = str(uuid.uuid4())
    item = _make_expense(
        expense_id, case_id,
        receiptUrl="https://storage.googleapis.com/bucket/r.pdf",
        receiptFilename="r.pdf",
    )
    mock_db, _ = _mock_expenses_db(case_id, [item])

    with patch("main.get_db", return_value=mock_db):
        resp = client.delete(
            f"/api/v1/settlement/cases/{case_id}/expenses/{expense_id}/receipt"
        )

    assert resp.status_code == 204


@pytest.mark.unit
def test_remove_receipt_not_found(client):
    case_id = "ZAD-2026-04-0001"
    mock_db, _ = _mock_expenses_db(case_id, [])

    with patch("main.get_db", return_value=mock_db):
        resp = client.delete(
            f"/api/v1/settlement/cases/{case_id}/expenses/ghost-id/receipt"
        )

    assert resp.status_code == 404


# ── GET list_expenses — totals ─────────────────────────────────────────────────

@pytest.mark.unit
def test_list_expenses_totals_calculated(client):
    case_id = "ZAD-2026-04-0001"
    e1_id   = str(uuid.uuid4())
    e2_id   = str(uuid.uuid4())
    items = [
        _make_expense(e1_id, case_id, amount=500.0,  category="Filing Fee",      paidStatus="Paid"),
        _make_expense(e2_id, case_id, amount=1000.0, category="Medical Records", paidStatus="Pending"),
    ]
    mock_db, _ = _mock_expenses_db(case_id, items)

    with patch("main.get_db", return_value=mock_db):
        resp = client.get(f"/api/v1/settlement/cases/{case_id}/expenses")

    assert resp.status_code == 200
    totals = resp.json()["totals"]
    assert totals["total_amount"]  == "1500.00"
    assert totals["total_paid"]    == "500.00"
    assert totals["total_unpaid"]  == "1000.00"
    assert len(totals["by_category"]) == 2


@pytest.mark.unit
def test_list_expenses_empty_totals(client):
    case_id = "ZAD-2026-04-0001"

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
        resp = client.get(f"/api/v1/settlement/cases/{case_id}/expenses")

    assert resp.status_code == 200
    totals = resp.json()["totals"]
    assert totals["total_amount"] == "0.00"
    assert totals["by_category"]  == []


# ── Admin expense categories ──────────────────────────────────────────────────

@pytest.mark.unit
def test_get_expense_categories_returns_builtin(client):
    mock_snap = MagicMock()
    mock_snap.exists = False
    mock_doc_ref = MagicMock()
    mock_doc_ref.get = AsyncMock(return_value=mock_snap)
    mock_db = MagicMock()
    mock_db.collection.return_value.document.return_value = mock_doc_ref

    with patch("main.get_db", return_value=mock_db):
        resp = client.get("/api/v1/admin/expense-categories")

    assert resp.status_code == 200
    data = resp.json()
    assert "Filing Fee"      in data["built_in"]
    assert "Medical Records" in data["built_in"]
    assert "Postage"         in data["built_in"]
    assert data["custom"]    == []


@pytest.mark.unit
def test_upsert_expense_categories_success(client):
    mock_doc_ref = MagicMock()
    mock_doc_ref.set = AsyncMock()
    mock_db = MagicMock()
    mock_db.collection.return_value.document.return_value = mock_doc_ref

    payload = {"custom_categories": ["Court Reporters", "Investigators"], "updated_by": "admin"}

    with patch("main.get_db", return_value=mock_db):
        resp = client.put("/api/v1/admin/expense-categories", json=payload)

    assert resp.status_code == 200
    data = resp.json()
    assert "Court Reporters" in data["custom"]
    assert "Investigators"   in data["custom"]
    assert "Court Reporters" in data["all_categories"]
    assert "Filing Fee"      in data["all_categories"]   # built-in still present


@pytest.mark.unit
def test_get_expense_categories_includes_custom(client):
    mock_snap = MagicMock()
    mock_snap.exists = True
    mock_snap.to_dict.return_value = {
        "custom_categories": ["Court Reporters"],
        "updated_by": "admin",
        "updated_at": datetime(2026, 4, 24, tzinfo=timezone.utc),
    }
    mock_doc_ref = MagicMock()
    mock_doc_ref.get = AsyncMock(return_value=mock_snap)
    mock_db = MagicMock()
    mock_db.collection.return_value.document.return_value = mock_doc_ref

    with patch("main.get_db", return_value=mock_db):
        resp = client.get("/api/v1/admin/expense-categories")

    assert resp.status_code == 200
    data = resp.json()
    assert "Court Reporters" in data["custom"]
    assert "Court Reporters" in data["all_categories"]
    assert "Filing Fee"      in data["all_categories"]
