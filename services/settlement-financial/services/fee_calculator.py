"""
services/fee_calculator.py — Attorney fee calculation engine.

Supports
--------
  flat        Single percentage of the gross award.
  graduated   Tiered percentages applied to successive bands of the award
              (similar to income-tax brackets).
  cap         Hard ceiling applied after the base fee is computed — either a
              fixed dollar amount or a percentage of the gross award.

All arithmetic uses Decimal with ROUND_HALF_UP for cent-accurate results.
"""
from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from typing import List, Tuple

from models.fee_config import (
    FeeCapType,
    FeeCalculationDetail,
    FeeConfigData,
    FeeStructureType,
    TierBreakdown,
)

_CENT  = Decimal("0.01")
_FOUR  = Decimal("0.0001")   # four-decimal precision for percentages


# ── Private helpers ────────────────────────────────────────────────────────────

def _round(v: Decimal) -> Decimal:
    return v.quantize(_CENT, rounding=ROUND_HALF_UP)


def _calc_flat(
    gross_award: Decimal,
    config: FeeConfigData,
) -> Tuple[Decimal, List[TierBreakdown]]:
    pct = config.flat_percentage  # validated non-None for flat type
    fee = _round(gross_award * pct / Decimal("100"))
    breakdown = [
        TierBreakdown(
            description=f"Flat {pct:.4f}% of ${gross_award:.2f}",
            award_portion=gross_award,
            percentage=pct,
            fee_amount=fee,
        )
    ]
    return fee, breakdown


def _calc_graduated(
    gross_award: Decimal,
    config: FeeConfigData,
) -> Tuple[Decimal, List[TierBreakdown]]:
    remaining   = gross_award
    total_fee   = Decimal("0")
    breakdown: List[TierBreakdown] = []
    prev_limit  = Decimal("0")

    for tier in config.graduated_tiers:
        if remaining <= Decimal("0"):
            break

        if tier.up_to is not None:
            tier_size   = tier.up_to - prev_limit
            tier_amount = min(remaining, tier_size)
            range_desc  = f"${prev_limit:.2f} – ${tier.up_to:.2f}"
        else:
            tier_amount = remaining
            range_desc  = f"above ${prev_limit:.2f}"

        tier_fee = _round(tier_amount * tier.percentage / Decimal("100"))

        breakdown.append(
            TierBreakdown(
                description=f"{tier.percentage:.4f}% on {range_desc}",
                award_portion=tier_amount,
                percentage=tier.percentage,
                fee_amount=tier_fee,
            )
        )
        total_fee += tier_fee
        remaining -= tier_amount
        if tier.up_to is not None:
            prev_limit = tier.up_to

    return total_fee, breakdown


# ── Public API ─────────────────────────────────────────────────────────────────

def calculate_attorney_fee(
    gross_award:     Decimal,
    config:          FeeConfigData,
    structure_label: str = "firm_default",
) -> FeeCalculationDetail:
    """
    Compute the attorney fee for *gross_award* using *config*.

    Parameters
    ----------
    gross_award     : Gross settlement award in USD (Decimal, > 0).
    config          : Fee configuration (flat or graduated, with optional cap).
    structure_label : Human-readable source label embedded in the result —
                      e.g. "firm_default", "case_override", or "manual".

    Returns
    -------
    FeeCalculationDetail with fee_amount, effective_percentage, tier_breakdown,
    and cap information.

    Raises
    ------
    ValueError if gross_award <= 0.
    """
    if gross_award <= Decimal("0"):
        raise ValueError("gross_award must be greater than zero")

    # ── Base fee ──────────────────────────────────────────────────────────────
    if config.structure_type == FeeStructureType.flat:
        fee, breakdown = _calc_flat(gross_award, config)
    else:
        fee, breakdown = _calc_graduated(gross_award, config)

    # ── Apply cap ─────────────────────────────────────────────────────────────
    capped:     bool                   = False
    cap_applied: Decimal | None        = None

    if config.cap_type == FeeCapType.amount and config.cap_amount:
        ceiling = _round(config.cap_amount)
        if fee > ceiling:
            fee         = ceiling
            capped      = True
            cap_applied = ceiling

    elif config.cap_type == FeeCapType.percentage and config.cap_percentage:
        ceiling = _round(gross_award * config.cap_percentage / Decimal("100"))
        if fee > ceiling:
            fee         = ceiling
            capped      = True
            cap_applied = ceiling

    # ── Effective percentage ──────────────────────────────────────────────────
    effective_pct = (fee / gross_award * Decimal("100")).quantize(
        _FOUR, rounding=ROUND_HALF_UP
    )

    return FeeCalculationDetail(
        gross_award          = gross_award,
        fee_amount           = fee,
        effective_percentage = effective_pct,
        structure_used       = structure_label,
        structure_type       = config.structure_type,
        tier_breakdown       = breakdown,
        capped               = capped,
        cap_applied          = cap_applied,
    )
