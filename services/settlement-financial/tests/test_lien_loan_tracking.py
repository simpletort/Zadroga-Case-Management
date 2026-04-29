"""
tests/test_lien_loan_tracking.py — Tests for expanded lien & loan tracking.

Covers
------
Liens:
  - lien_type (Medical / Government / Private)
  - claim_status (Claimed / Verified / Disputed / Paid)
  - is_disputed flag computed correctly
  - totals: total_amount, total_outstanding, total_disputed, total_satisfied, by_type
  - update with new fields

Loans:
  - interest_rate, disbursement_date, payoff_amount, notes
  - totals: total_amount, total_payoff, outstanding_amount, outstanding_payoff
  - payoff falls back to amount when payoff_amount is not set
  - update with new fields
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


# ── App fixture ───────────────────────────────────────────────────────────────

@pytest.fixture()
def client():
    with patch("services.firestore_client.get_db"), patch("main.get_db"):
        from main import app
        return TestClient(app)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_lien(lien_id, case_id, **overrides):
    base = {
        "lienId":             lien_id,
        "caseId":             case_id,
        "lienholder":         "Medicare",
        "amount":             12000.0,
        "lienType":           "Medical",
        "claimStatus":        "Claimed",
        "satisfactionStatus": "Outstanding",
        "satisfactionDate":   None,
        "notes":              "Pending reduction",
        "addedBy":            "user-uid-123",
        "addedAt":            datetime(2026, 4, 17, tzinfo=timezone.utc),
        "updatedAt":          None,
        "updatedBy":          None,
    }
    base.update(overrides)
    return base


def _make_loan(loan_id, case_id, **overrides):
    base = {
        "loanId":             loan_id,
        "caseId":             case_id,
        "lender":             "LawCash Advances",
        "amount":             5000.0,
        "interestRate":       None,
        "disbursementDate":   None,
        "payoffAmount":       None,
        "satisfactionStatus": "Outstanding",
        "satisfactionDate":   None,
        "notes":              None,
        "addedBy":            "user-uid-123",
        "addedAt":            datetime(2026, 4, 17, tzinfo=timezone.utc),
        "updatedAt":          None,
        "updatedBy":          None,
    }
    base.update(overrides)
    return base


def _mock_db_items(items: list):
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


# ═══════════════════════════════════════════════════════════════════════════════
# LIEN TESTS
# ═══════════════════════════════════════════════════════════════════════════════

class TestLienType:

    def test_add_lien_with_medical_type(self, client):
        case_id = "ZAD-2026-04-0001"
        lien_id = str(uuid.uuid4())
        item    = _make_lien(lien_id, case_id, lienType="Medical")
        mock_db, _ = _mock_db_items([item])

        payload = {
            "lienholder": "Medicare",
            "amount": "12000.00",
            "lien_type": "Medical",
            "claim_status": "Verified",
        }
        with patch("main.get_db", return_value=mock_db):
            resp = client.post(f"/api/v1/settlement/cases/{case_id}/liens", json=payload)

        assert resp.status_code == 201
        assert resp.json()["lien_type"] == "Medical"

    def test_add_lien_with_government_type(self, client):
        case_id = "ZAD-2026-04-0001"
        lien_id = str(uuid.uuid4())
        item    = _make_lien(lien_id, case_id, lienType="Government", claimStatus="Verified")
        mock_db, _ = _mock_db_items([item])

        payload = {"lienholder": "IRS", "amount": "8000.00", "lien_type": "Government"}
        with patch("main.get_db", return_value=mock_db):
            resp = client.post(f"/api/v1/settlement/cases/{case_id}/liens", json=payload)

        assert resp.status_code == 201
        assert resp.json()["lien_type"] == "Government"


class TestLienClaimStatus:

    def test_disputed_lien_sets_is_disputed_true(self, client):
        case_id = "ZAD-2026-04-0001"
        lien_id = str(uuid.uuid4())
        item    = _make_lien(lien_id, case_id, claimStatus="Disputed")
        mock_db, _ = _mock_db_items([item])

        with patch("main.get_db", return_value=mock_db):
            resp = client.get(f"/api/v1/settlement/cases/{case_id}/liens")

        assert resp.status_code == 200
        lien = resp.json()["liens"][0]
        assert lien["claim_status"] == "Disputed"
        assert lien["is_disputed"] is True

    def test_non_disputed_lien_is_disputed_false(self, client):
        case_id = "ZAD-2026-04-0001"
        lien_id = str(uuid.uuid4())
        item    = _make_lien(lien_id, case_id, claimStatus="Verified")
        mock_db, _ = _mock_db_items([item])

        with patch("main.get_db", return_value=mock_db):
            resp = client.get(f"/api/v1/settlement/cases/{case_id}/liens")

        lien = resp.json()["liens"][0]
        assert lien["is_disputed"] is False

    def test_update_lien_claim_status_to_disputed(self, client):
        case_id = "ZAD-2026-04-0001"
        lien_id = str(uuid.uuid4())
        item    = _make_lien(lien_id, case_id, claimStatus="Disputed")
        mock_db, _ = _mock_db_items([item])

        with patch("main.get_db", return_value=mock_db):
            resp = client.patch(
                f"/api/v1/settlement/cases/{case_id}/liens/{lien_id}",
                json={"claim_status": "Disputed"},
            )

        assert resp.status_code == 200
        assert resp.json()["claim_status"] == "Disputed"
        assert resp.json()["is_disputed"] is True

    def test_update_lien_type(self, client):
        case_id = "ZAD-2026-04-0001"
        lien_id = str(uuid.uuid4())
        item    = _make_lien(lien_id, case_id, lienType="Private")
        mock_db, _ = _mock_db_items([item])

        with patch("main.get_db", return_value=mock_db):
            resp = client.patch(
                f"/api/v1/settlement/cases/{case_id}/liens/{lien_id}",
                json={"lien_type": "Medical"},
            )

        assert resp.status_code == 200
        assert resp.json()["lien_type"] == "Medical"


class TestLienTotals:

    def test_totals_outstanding_and_satisfied(self, client):
        case_id = "ZAD-2026-04-0001"
        items = [
            _make_lien(str(uuid.uuid4()), case_id, amount=10000.0, satisfactionStatus="Outstanding"),
            _make_lien(str(uuid.uuid4()), case_id, amount=5000.0,  satisfactionStatus="Negotiating"),
            _make_lien(str(uuid.uuid4()), case_id, amount=3000.0,  satisfactionStatus="Satisfied"),
            _make_lien(str(uuid.uuid4()), case_id, amount=2000.0,  satisfactionStatus="Waived"),
        ]
        mock_db, _ = _mock_db_items(items)

        with patch("main.get_db", return_value=mock_db):
            resp = client.get(f"/api/v1/settlement/cases/{case_id}/liens")

        totals = resp.json()["totals"]
        assert totals["total_amount"]      == "20000.00"
        assert totals["total_outstanding"] == "15000.00"  # 10000 + 5000
        assert totals["total_satisfied"]   == "5000.00"   # 3000 + 2000

    def test_totals_disputed_flagged(self, client):
        case_id = "ZAD-2026-04-0001"
        items = [
            _make_lien(str(uuid.uuid4()), case_id, amount=8000.0,  claimStatus="Disputed"),
            _make_lien(str(uuid.uuid4()), case_id, amount=4000.0,  claimStatus="Verified"),
            _make_lien(str(uuid.uuid4()), case_id, amount=2000.0,  claimStatus="Disputed"),
        ]
        mock_db, _ = _mock_db_items(items)

        with patch("main.get_db", return_value=mock_db):
            resp = client.get(f"/api/v1/settlement/cases/{case_id}/liens")

        totals = resp.json()["totals"]
        assert totals["total_disputed"] == "10000.00"   # 8000 + 2000
        assert totals["disputed_count"] == 2

    def test_totals_by_type(self, client):
        case_id = "ZAD-2026-04-0001"
        items = [
            _make_lien(str(uuid.uuid4()), case_id, amount=12000.0, lienType="Medical"),
            _make_lien(str(uuid.uuid4()), case_id, amount=5000.0,  lienType="Government"),
            _make_lien(str(uuid.uuid4()), case_id, amount=3000.0,  lienType="Medical"),
        ]
        mock_db, _ = _mock_db_items(items)

        with patch("main.get_db", return_value=mock_db):
            resp = client.get(f"/api/v1/settlement/cases/{case_id}/liens")

        by_type = {t["lien_type"]: t for t in resp.json()["totals"]["by_type"]}
        assert by_type["Medical"]["total"]     == "15000.00"
        assert by_type["Medical"]["count"]     == 2
        assert by_type["Government"]["total"]  == "5000.00"

    def test_empty_liens_zero_totals(self, client):
        case_id  = "ZAD-2026-04-0001"
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
            resp = client.get(f"/api/v1/settlement/cases/{case_id}/liens")

        totals = resp.json()["totals"]
        assert totals["total_amount"]      == "0.00"
        assert totals["total_outstanding"] == "0.00"
        assert totals["disputed_count"]    == 0


# ═══════════════════════════════════════════════════════════════════════════════
# LOAN TESTS
# ═══════════════════════════════════════════════════════════════════════════════

class TestLoanFields:

    def test_add_loan_with_interest_and_payoff(self, client):
        case_id = "ZAD-2026-04-0001"
        loan_id = str(uuid.uuid4())
        item    = _make_loan(loan_id, case_id, interestRate=12.5, payoffAmount=5750.0,
                             disbursementDate=datetime(2026, 1, 15, tzinfo=timezone.utc))
        mock_db, _ = _mock_db_items([item])

        payload = {
            "lender":            "LawCash Advances",
            "amount":            "5000.00",
            "interest_rate":     "12.5",
            "payoff_amount":     "5750.00",
            "disbursement_date": "2026-01-15T00:00:00Z",
            "notes":             "Case advance for living expenses",
        }
        with patch("main.get_db", return_value=mock_db):
            resp = client.post(f"/api/v1/settlement/cases/{case_id}/loans", json=payload)

        assert resp.status_code == 201
        data = resp.json()
        assert data["amount"]        == "5000.00"
        assert data["interest_rate"] == "12.5000"
        assert data["payoff_amount"] == "5750.00"
        assert data["notes"]         == "Case advance for living expenses"

    def test_add_loan_without_optional_fields(self, client):
        case_id = "ZAD-2026-04-0001"
        loan_id = str(uuid.uuid4())
        item    = _make_loan(loan_id, case_id)
        mock_db, _ = _mock_db_items([item])

        payload = {"lender": "ABC Funding", "amount": "3000.00"}
        with patch("main.get_db", return_value=mock_db):
            resp = client.post(f"/api/v1/settlement/cases/{case_id}/loans", json=payload)

        assert resp.status_code == 201
        data = resp.json()
        assert data["interest_rate"] is None
        assert data["payoff_amount"] is None
        assert data["notes"]         is None

    def test_update_loan_payoff_amount(self, client):
        case_id = "ZAD-2026-04-0001"
        loan_id = str(uuid.uuid4())
        item    = _make_loan(loan_id, case_id, payoffAmount=5500.0)
        mock_db, _ = _mock_db_items([item])

        with patch("main.get_db", return_value=mock_db):
            resp = client.patch(
                f"/api/v1/settlement/cases/{case_id}/loans/{loan_id}",
                json={"payoff_amount": "5500.00"},
            )

        assert resp.status_code == 200
        assert resp.json()["payoff_amount"] == "5500.00"

    def test_update_loan_notes(self, client):
        case_id = "ZAD-2026-04-0001"
        loan_id = str(uuid.uuid4())
        item    = _make_loan(loan_id, case_id, notes="Updated note")
        mock_db, _ = _mock_db_items([item])

        with patch("main.get_db", return_value=mock_db):
            resp = client.patch(
                f"/api/v1/settlement/cases/{case_id}/loans/{loan_id}",
                json={"notes": "Updated note"},
            )

        assert resp.status_code == 200
        assert resp.json()["notes"] == "Updated note"


class TestLoanTotals:

    def test_totals_with_payoff_amounts(self, client):
        case_id = "ZAD-2026-04-0001"
        items = [
            _make_loan(str(uuid.uuid4()), case_id, amount=5000.0, payoffAmount=5750.0,
                       satisfactionStatus="Outstanding"),
            _make_loan(str(uuid.uuid4()), case_id, amount=3000.0, payoffAmount=3300.0,
                       satisfactionStatus="Outstanding"),
            _make_loan(str(uuid.uuid4()), case_id, amount=2000.0, payoffAmount=2100.0,
                       satisfactionStatus="Satisfied"),
        ]
        mock_db, _ = _mock_db_items(items)

        with patch("main.get_db", return_value=mock_db):
            resp = client.get(f"/api/v1/settlement/cases/{case_id}/loans")

        totals = resp.json()["totals"]
        assert totals["total_amount"]        == "10000.00"
        assert totals["total_payoff"]        == "11150.00"  # 5750+3300+2100
        assert totals["outstanding_amount"]  == "8000.00"   # 5000+3000
        assert totals["outstanding_payoff"]  == "9050.00"   # 5750+3300

    def test_totals_fallback_to_amount_when_no_payoff(self, client):
        case_id = "ZAD-2026-04-0001"
        items = [
            _make_loan(str(uuid.uuid4()), case_id, amount=4000.0, payoffAmount=None,
                       satisfactionStatus="Outstanding"),
        ]
        mock_db, _ = _mock_db_items(items)

        with patch("main.get_db", return_value=mock_db):
            resp = client.get(f"/api/v1/settlement/cases/{case_id}/loans")

        totals = resp.json()["totals"]
        # payoff_amount not set → falls back to amount
        assert totals["total_payoff"]       == "4000.00"
        assert totals["outstanding_payoff"] == "4000.00"

    def test_empty_loans_zero_totals(self, client):
        case_id   = "ZAD-2026-04-0001"
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
            resp = client.get(f"/api/v1/settlement/cases/{case_id}/loans")

        totals = resp.json()["totals"]
        assert totals["total_amount"]       == "0.00"
        assert totals["outstanding_amount"] == "0.00"
        assert totals["outstanding_payoff"] == "0.00"
