"""
services/calculator.py — Pure settlement distribution calculation logic.

Uses Python's Decimal type with ROUND_HALF_UP throughout to ensure
cent-accurate results.  No I/O — fully unit-testable without mocks.
"""
from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from typing import List

from models.settlement import CalculationRequest, CalculationResult, LineItem

# One cent — used to quantize every intermediate and final amount.
CENT = Decimal("0.01")


def _sum_items(items: List[LineItem]) -> Decimal:
    """Sum the amounts of a list of LineItems, quantized to cents."""
    if not items:
        return Decimal("0.00")
    total = sum((item.amount for item in items), Decimal("0"))
    return total.quantize(CENT, rounding=ROUND_HALF_UP)


def run_calculation(request: CalculationRequest) -> CalculationResult:
    """
    Compute the full settlement distribution breakdown.

    All intermediate values are quantized to cents with ROUND_HALF_UP to
    prevent floating-point drift and ensure reproducibility.

    Raises
    ------
    ValueError
        If net_to_client would be negative (total deductions exceed gross award).
    """
    gross = request.gross_award.quantize(CENT, rounding=ROUND_HALF_UP)

    # Attorney fee: gross × (pct / 100), rounded to nearest cent
    fee_pct = request.attorney_fee_pct.quantize(
        Decimal("0.0001"), rounding=ROUND_HALF_UP
    )
    attorney_fee = (gross * fee_pct / Decimal("100")).quantize(
        CENT, rounding=ROUND_HALF_UP
    )

    total_expenses = _sum_items(request.case_expenses)
    total_liens = _sum_items(request.liens)
    total_loans = _sum_items(request.client_loans)

    total_deductions = (
        attorney_fee + total_expenses + total_liens + total_loans
    ).quantize(CENT, rounding=ROUND_HALF_UP)

    net_to_client = (gross - total_deductions).quantize(
        CENT, rounding=ROUND_HALF_UP
    )

    if net_to_client < Decimal("0.00"):
        raise ValueError(
            f"Net to client would be negative (${net_to_client:.2f}). "
            "Total deductions exceed the gross award. "
            "Reduce expenses, liens, loans, or the attorney fee percentage."
        )

    return CalculationResult(
        attorney_fee_amount=attorney_fee,
        total_expenses=total_expenses,
        total_liens=total_liens,
        total_loans=total_loans,
        total_deductions=total_deductions,
        net_to_client=net_to_client,
    )
