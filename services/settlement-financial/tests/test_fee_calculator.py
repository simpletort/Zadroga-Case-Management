"""
tests/test_fee_calculator.py — Unit tests for the attorney fee calculation engine.

Covers
------
  - Flat fee: basic, rounding, zero percentage, 100%
  - Graduated fee: within one tier, spanning multiple tiers, exact boundary
  - Fee cap: by amount, by percentage, cap not triggered
  - Effective percentage computation
  - Error cases
"""
from __future__ import annotations

from decimal import Decimal

import pytest

from models.fee_config import (
    FeeCapType,
    FeeConfigData,
    FeeStructureType,
    GraduatedTier,
)
from services.fee_calculator import calculate_attorney_fee


# ── Helpers ────────────────────────────────────────────────────────────────────

def flat_config(pct: str, cap_type=FeeCapType.none, cap_amount=None, cap_pct=None) -> FeeConfigData:
    return FeeConfigData(
        structure_type=FeeStructureType.flat,
        flat_percentage=Decimal(pct),
        cap_type=cap_type,
        cap_amount=Decimal(cap_amount) if cap_amount else None,
        cap_percentage=Decimal(cap_pct) if cap_pct else None,
    )


def graduated_config(tiers, cap_type=FeeCapType.none, cap_amount=None, cap_pct=None) -> FeeConfigData:
    """
    tiers: list of (up_to_str_or_None, pct_str)
    """
    gt = [GraduatedTier(up_to=Decimal(u) if u else None, percentage=Decimal(p)) for u, p in tiers]
    return FeeConfigData(
        structure_type=FeeStructureType.graduated,
        graduated_tiers=gt,
        cap_type=cap_type,
        cap_amount=Decimal(cap_amount) if cap_amount else None,
        cap_percentage=Decimal(cap_pct) if cap_pct else None,
    )


# ── Flat fee tests ─────────────────────────────────────────────────────────────

class TestFlatFee:

    def test_basic_33_pct(self):
        result = calculate_attorney_fee(Decimal("500000"), flat_config("33.33"))
        assert result.fee_amount == Decimal("166650.00")
        assert result.structure_type == FeeStructureType.flat
        assert not result.capped
        assert len(result.tier_breakdown) == 1

    def test_rounding_half_up(self):
        # 100 * 33.333% = 33.333 → rounds to 33.33
        result = calculate_attorney_fee(Decimal("100"), flat_config("33.333"))
        assert result.fee_amount == Decimal("33.33")

    def test_zero_pct(self):
        result = calculate_attorney_fee(Decimal("100000"), flat_config("0"))
        assert result.fee_amount == Decimal("0.00")
        assert result.effective_percentage == Decimal("0.0000")

    def test_100_pct(self):
        result = calculate_attorney_fee(Decimal("50000"), flat_config("100"))
        assert result.fee_amount == Decimal("50000.00")

    def test_effective_percentage_stored(self):
        result = calculate_attorney_fee(Decimal("300000"), flat_config("33.33"))
        # fee = 99990.00; 99990/300000*100 = 33.33
        assert result.fee_amount == Decimal("99990.00")
        assert result.effective_percentage == Decimal("33.3300")

    def test_structure_label_propagated(self):
        result = calculate_attorney_fee(
            Decimal("100000"), flat_config("25"), structure_label="case_override"
        )
        assert result.structure_used == "case_override"

    def test_small_cent_level_award(self):
        result = calculate_attorney_fee(Decimal("0.03"), flat_config("33.33"))
        assert result.fee_amount == Decimal("0.01")

    def test_large_award(self):
        result = calculate_attorney_fee(Decimal("10000000"), flat_config("33.33"))
        assert result.fee_amount == Decimal("3333000.00")


# ── Graduated fee tests ────────────────────────────────────────────────────────

class TestGraduatedFee:

    def _three_tier_config(self):
        # 33.33% on first $250k | 25% on next $250k | 20% above $500k
        return graduated_config([
            ("250000", "33.33"),
            ("500000", "25.00"),
            (None,     "20.00"),
        ])

    def test_award_within_first_tier(self):
        # $100k × 33.33% = $33,330
        result = calculate_attorney_fee(Decimal("100000"), self._three_tier_config())
        assert result.fee_amount == Decimal("33330.00")
        assert len(result.tier_breakdown) == 1

    def test_award_at_first_tier_boundary(self):
        # exactly $250,000 — all in first tier
        result = calculate_attorney_fee(Decimal("250000"), self._three_tier_config())
        assert result.fee_amount == Decimal("83325.00")  # 250000 * 33.33%
        assert len(result.tier_breakdown) == 1

    def test_award_spans_two_tiers(self):
        # $350k: first $250k @ 33.33% + next $100k @ 25%
        # = 83325 + 25000 = 108325
        result = calculate_attorney_fee(Decimal("350000"), self._three_tier_config())
        assert result.fee_amount == Decimal("108325.00")
        assert len(result.tier_breakdown) == 2

    def test_award_spans_all_three_tiers(self):
        # $600k: $250k@33.33% + $250k@25% + $100k@20%
        # = 83325 + 62500 + 20000 = 165825
        result = calculate_attorney_fee(Decimal("600000"), self._three_tier_config())
        assert result.fee_amount == Decimal("165825.00")
        assert len(result.tier_breakdown) == 3

    def test_single_unlimited_tier(self):
        # Only one tier: 33% on everything
        cfg = graduated_config([(None, "33")])
        result = calculate_attorney_fee(Decimal("500000"), cfg)
        assert result.fee_amount == Decimal("165000.00")

    def test_tier_breakdown_amounts_sum_to_fee(self):
        result = calculate_attorney_fee(Decimal("750000"), self._three_tier_config())
        total = sum(t.fee_amount for t in result.tier_breakdown)
        assert total == result.fee_amount

    def test_award_portions_sum_to_gross(self):
        gross = Decimal("750000")
        result = calculate_attorney_fee(gross, self._three_tier_config())
        total_portions = sum(t.award_portion for t in result.tier_breakdown)
        assert total_portions == gross


# ── Fee cap tests ──────────────────────────────────────────────────────────────

class TestFeeCap:

    def test_cap_by_amount_triggered(self):
        # 33.33% of $500k = $166,650 > cap of $150,000
        cfg = flat_config("33.33", cap_type=FeeCapType.amount, cap_amount="150000")
        result = calculate_attorney_fee(Decimal("500000"), cfg)
        assert result.fee_amount == Decimal("150000.00")
        assert result.capped is True
        assert result.cap_applied == Decimal("150000.00")

    def test_cap_by_amount_not_triggered(self):
        # 33.33% of $100k = $33,330 < cap of $150,000
        cfg = flat_config("33.33", cap_type=FeeCapType.amount, cap_amount="150000")
        result = calculate_attorney_fee(Decimal("100000"), cfg)
        assert result.fee_amount == Decimal("33330.00")
        assert result.capped is False
        assert result.cap_applied is None

    def test_cap_by_percentage_triggered(self):
        # 40% of $500k = $200k; cap is 30% of $500k = $150k
        cfg = flat_config("40", cap_type=FeeCapType.percentage, cap_pct="30")
        result = calculate_attorney_fee(Decimal("500000"), cfg)
        assert result.fee_amount == Decimal("150000.00")
        assert result.capped is True

    def test_cap_by_percentage_not_triggered(self):
        # 25% of $500k = $125k; cap is 30% = $150k — no cap
        cfg = flat_config("25", cap_type=FeeCapType.percentage, cap_pct="30")
        result = calculate_attorney_fee(Decimal("500000"), cfg)
        assert result.fee_amount == Decimal("125000.00")
        assert result.capped is False

    def test_graduated_with_cap(self):
        cfg = graduated_config(
            [("250000", "33.33"), (None, "25.00")],
            cap_type=FeeCapType.amount,
            cap_amount="100000",
        )
        # $500k: 83325 + 62500 = 145825; capped at 100000
        result = calculate_attorney_fee(Decimal("500000"), cfg)
        assert result.fee_amount == Decimal("100000.00")
        assert result.capped is True


# ── Effective percentage ───────────────────────────────────────────────────────

class TestEffectivePercentage:

    def test_effective_equals_flat_pct_when_uncapped(self):
        result = calculate_attorney_fee(Decimal("100000"), flat_config("33.33"))
        # 33330 / 100000 * 100 = 33.33
        assert result.effective_percentage == Decimal("33.3300")

    def test_effective_lower_than_nominal_when_capped(self):
        cfg = flat_config("40", cap_type=FeeCapType.amount, cap_amount="30000")
        result = calculate_attorney_fee(Decimal("100000"), cfg)
        # capped at 30000; 30000/100000*100 = 30.00
        assert result.effective_percentage == Decimal("30.0000")

    def test_graduated_effective_pct(self):
        # 3-tier on $600k: fee = 165825; eff% = 165825/600000*100 = 27.6375
        cfg = graduated_config([("250000", "33.33"), ("500000", "25.00"), (None, "20.00")])
        result = calculate_attorney_fee(Decimal("600000"), cfg)
        assert result.effective_percentage == Decimal("27.6375")


# ── Error cases ────────────────────────────────────────────────────────────────

class TestErrors:

    def test_zero_gross_award_raises(self):
        with pytest.raises(ValueError, match="greater than zero"):
            calculate_attorney_fee(Decimal("0"), flat_config("33.33"))

    def test_negative_gross_award_raises(self):
        with pytest.raises(ValueError, match="greater than zero"):
            calculate_attorney_fee(Decimal("-100"), flat_config("33.33"))

    def test_flat_config_missing_percentage_raises(self):
        with pytest.raises(Exception):
            FeeConfigData(structure_type=FeeStructureType.flat)

    def test_graduated_config_empty_tiers_raises(self):
        with pytest.raises(Exception):
            FeeConfigData(structure_type=FeeStructureType.graduated, graduated_tiers=[])

    def test_graduated_config_no_unlimited_tier_raises(self):
        with pytest.raises(Exception):
            FeeConfigData(
                structure_type=FeeStructureType.graduated,
                graduated_tiers=[
                    GraduatedTier(up_to=Decimal("250000"), percentage=Decimal("33")),
                    GraduatedTier(up_to=Decimal("500000"), percentage=Decimal("25")),
                    # missing the final tier with up_to=None
                ],
            )

    def test_graduated_config_last_tier_must_be_unlimited(self):
        with pytest.raises(Exception):
            FeeConfigData(
                structure_type=FeeStructureType.graduated,
                graduated_tiers=[
                    GraduatedTier(up_to=None, percentage=Decimal("33")),      # unlimited first
                    GraduatedTier(up_to=Decimal("500000"), percentage=Decimal("25")),
                ],
            )

    def test_cap_amount_missing_raises(self):
        with pytest.raises(Exception):
            FeeConfigData(
                structure_type=FeeStructureType.flat,
                flat_percentage=Decimal("33"),
                cap_type=FeeCapType.amount,
                # cap_amount not provided
            )

    def test_cap_percentage_missing_raises(self):
        with pytest.raises(Exception):
            FeeConfigData(
                structure_type=FeeStructureType.flat,
                flat_percentage=Decimal("33"),
                cap_type=FeeCapType.percentage,
                # cap_percentage not provided
            )
