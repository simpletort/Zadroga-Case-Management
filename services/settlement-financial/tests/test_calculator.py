"""
tests/test_calculator.py — Unit tests for the settlement calculator.

All tests are pure (no I/O, no mocks needed) and tagged @pytest.mark.unit.
"""
from __future__ import annotations

from decimal import Decimal

import pytest

from models.settlement import CalculationRequest, LineItem
from services.calculator import CENT, run_calculation


def _req(
    gross="500000.00",
    fee_pct="33.33",
    expenses=None,
    liens=None,
    loans=None,
):
    return CalculationRequest(
        gross_award=gross,
        attorney_fee_pct=fee_pct,
        case_expenses=expenses or [],
        liens=liens or [],
        client_loans=loans or [],
    )


def _item(description, amount):
    return LineItem(description=description, amount=amount)


# ── Basic arithmetic ──────────────────────────────────────────────────────────

@pytest.mark.unit
def test_attorney_fee_rounded_to_cent():
    """33.33% of $500 000 = $166 650.00 exactly."""
    req = _req(gross="500000.00", fee_pct="33.33")
    result = run_calculation(req)
    assert result.attorney_fee_amount == Decimal("166650.00")


@pytest.mark.unit
def test_net_to_client_simple():
    """No deductions beyond attorney fee."""
    req = _req(gross="100000.00", fee_pct="40.00")
    result = run_calculation(req)
    assert result.attorney_fee_amount == Decimal("40000.00")
    assert result.total_deductions == Decimal("40000.00")
    assert result.net_to_client == Decimal("60000.00")


@pytest.mark.unit
def test_all_deductions():
    """Full example: attorney fee + expenses + liens + loans."""
    req = _req(
        gross="500000.00",
        fee_pct="33.33",
        expenses=[_item("Medical records", "850.00"), _item("Expert witness", "3500.00")],
        liens=[_item("Medicare lien", "12000.00")],
        loans=[_item("Case advance", "5000.00")],
    )
    result = run_calculation(req)

    assert result.attorney_fee_amount == Decimal("166650.00")
    assert result.total_expenses == Decimal("4350.00")
    assert result.total_liens == Decimal("12000.00")
    assert result.total_loans == Decimal("5000.00")
    assert result.total_deductions == Decimal("188000.00")
    assert result.net_to_client == Decimal("312000.00")


@pytest.mark.unit
def test_zero_attorney_fee():
    req = _req(gross="200000.00", fee_pct="0.00")
    result = run_calculation(req)
    assert result.attorney_fee_amount == Decimal("0.00")
    assert result.net_to_client == Decimal("200000.00")


@pytest.mark.unit
def test_empty_line_item_lists():
    req = _req(gross="100000.00", fee_pct="25.00")
    result = run_calculation(req)
    assert result.total_expenses == Decimal("0.00")
    assert result.total_liens == Decimal("0.00")
    assert result.total_loans == Decimal("0.00")


@pytest.mark.unit
def test_multiple_items_summed_correctly():
    req = _req(
        gross="300000.00",
        fee_pct="0.00",
        expenses=[
            _item("Fee A", "1000.00"),
            _item("Fee B", "2000.00"),
            _item("Fee C", "500.50"),
        ],
    )
    result = run_calculation(req)
    assert result.total_expenses == Decimal("3500.50")
    assert result.net_to_client == Decimal("296499.50")


# ── Rounding precision ────────────────────────────────────────────────────────

@pytest.mark.unit
def test_rounding_half_up():
    """
    1/3 of $1.00 = $0.33333... rounds to $0.33.
    Remaining net = $1.00 - $0.33 = $0.67.
    """
    req = _req(gross="1.00", fee_pct="33.3333333")
    result = run_calculation(req)
    # ROUND_HALF_UP: 0.333333... → 0.33
    assert result.attorney_fee_amount == Decimal("0.33")
    assert result.net_to_client == Decimal("0.67")
    # All amounts are quantized to cents
    assert result.attorney_fee_amount == result.attorney_fee_amount.quantize(CENT)


@pytest.mark.unit
def test_cent_precision_throughout():
    """All result fields must be quantized to exactly 2 decimal places."""
    req = _req(
        gross="999999.99",
        fee_pct="33.33",
        expenses=[_item("Misc", "0.01")],
    )
    result = run_calculation(req)
    for field_name in ("attorney_fee_amount", "total_expenses", "total_liens",
                       "total_loans", "total_deductions", "net_to_client"):
        val = getattr(result, field_name)
        assert val == val.quantize(CENT), f"{field_name} is not cent-quantized: {val}"


# ── Validation: negative net-to-client ───────────────────────────────────────

@pytest.mark.unit
def test_negative_net_to_client_raises():
    """Deductions exceeding gross award must raise ValueError."""
    req = _req(
        gross="1000.00",
        fee_pct="50.00",
        liens=[_item("Huge lien", "600.00")],
    )
    with pytest.raises(ValueError, match="negative"):
        run_calculation(req)


@pytest.mark.unit
def test_exactly_zero_net_to_client_is_allowed():
    """Net-to-client of exactly $0.00 is valid (no error raised)."""
    req = _req(
        gross="1000.00",
        fee_pct="100.00",
    )
    result = run_calculation(req)
    assert result.net_to_client == Decimal("0.00")


@pytest.mark.unit
def test_attorney_fee_100_pct():
    req = _req(gross="50000.00", fee_pct="100.00")
    result = run_calculation(req)
    assert result.attorney_fee_amount == Decimal("50000.00")
    assert result.net_to_client == Decimal("0.00")


# ── Edge cases ────────────────────────────────────────────────────────────────

@pytest.mark.unit
def test_large_award():
    """$10M settlement with 33% fee and various deductions."""
    req = _req(
        gross="10000000.00",
        fee_pct="33.00",
        expenses=[_item("Total expenses", "50000.00")],
        liens=[_item("Medicare", "100000.00")],
        loans=[_item("Advances", "25000.00")],
    )
    result = run_calculation(req)
    assert result.attorney_fee_amount == Decimal("3300000.00")
    assert result.total_deductions == Decimal("3475000.00")
    assert result.net_to_client == Decimal("6525000.00")


@pytest.mark.unit
def test_small_cent_level_award():
    req = _req(gross="0.01", fee_pct="0.00")
    result = run_calculation(req)
    assert result.net_to_client == Decimal("0.01")


@pytest.mark.unit
def test_fractional_fee_pct():
    """33.3% of $300 = $99.90."""
    req = _req(gross="300.00", fee_pct="33.3")
    result = run_calculation(req)
    assert result.attorney_fee_amount == Decimal("99.90")
    assert result.net_to_client == Decimal("200.10")
