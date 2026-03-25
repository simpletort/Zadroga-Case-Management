"""
tests/unit/test_vcf_screener.py — Unit tests for VCF screening rule engine.

Covers:
  - All 6 rules individually
  - Boundary dates (exactly on VCF window start/end)
  - Multiple conditions (matched and unmatched)
  - Missing fields (hard fail)
  - Status transitions (eligible/ineligible/needs_review)
"""
import sys
from unittest.mock import MagicMock

sys.modules['functions_framework'] = MagicMock()

from __future__ import annotations
import sys
import os

# Ensure functions path is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../functions/vcf_screener'))

import pytest
from main import (
    run_screening,
    rule_exposure_site,
    rule_exposure_date_overlap,
    rule_wtc_health_program,
    rule_prior_attorney,
    rule_minimum_data_completeness,
    rule_conditions_match,
    VCF_WINDOW_START,
    VCF_WINDOW_END,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def eligible_case():
    return {
        "caseId": "ZAD-2025-03-0001",
        "firstName": "John",
        "lastName": "Doe",
        "email": "john@example.com",
        "phone": "+12125551234",
        "exposureLocation": "World Trade Center",
        "exposureDateStart": "2001-09-11",
        "exposureDateEnd": "2002-06-30",
        "wtcHealthProgramStatus": "enrolled",
        "priorAttorney": False,
        "conditions": ["respiratory", "asthma"],
    }


@pytest.fixture
def ineligible_case():
    return {
        "caseId": "ZAD-2025-03-0002",
        "firstName": "Jane",
        "lastName": "Smith",
        "email": "jane@example.com",
        "phone": "+12125559999",
        "exposureLocation": "Los Angeles International Airport",
        "exposureDateStart": "2015-01-01",
        "exposureDateEnd": "2016-01-01",
        "wtcHealthProgramStatus": "not_applied",
        "priorAttorney": False,
        "conditions": [],
    }


@pytest.fixture
def needs_review_case():
    return {
        "caseId": "ZAD-2025-03-0003",
        "firstName": "Bob",
        "lastName": "Review",
        "email": "bob@example.com",
        "phone": "+12125550001",
        "exposureLocation": "Ground Zero",
        "exposureDateStart": "2001-09-11",
        "exposureDateEnd": "2002-01-01",
        "wtcHealthProgramStatus": "not_applied",
        "priorAttorney": True,
        "conditions": ["cancer"],
    }


# ── R01: Exposure site ────────────────────────────────────────────────────────

class TestRuleExposureSite:
    def test_wtc_passes(self, eligible_case):
        r = rule_exposure_site(eligible_case)
        assert r.passed is True
        assert r.severity == "pass"

    def test_ground_zero_passes(self):
        r = rule_exposure_site({"exposureLocation": "Ground Zero, Manhattan"})
        assert r.passed is True

    def test_pentagon_passes(self):
        r = rule_exposure_site({"exposureLocation": "The Pentagon, Arlington VA"})
        assert r.passed is True

    def test_shanksville_passes(self):
        r = rule_exposure_site({"exposureLocation": "Shanksville, Pennsylvania"})
        assert r.passed is True

    def test_fresh_kills_passes(self):
        r = rule_exposure_site({"exposureLocation": "Fresh Kills Landfill"})
        assert r.passed is True

    def test_unrelated_location_fails(self, ineligible_case):
        r = rule_exposure_site(ineligible_case)
        assert r.passed is False
        assert r.severity == "hard_fail"
        assert r.code == "INELIGIBLE_SITE"

    def test_empty_location_fails(self):
        r = rule_exposure_site({"exposureLocation": ""})
        assert r.passed is False

    def test_missing_location_fails(self):
        r = rule_exposure_site({})
        assert r.passed is False


# ── R02: Exposure dates ───────────────────────────────────────────────────────

class TestRuleExposureDates:
    def test_overlapping_dates_pass(self, eligible_case):
        r = rule_exposure_date_overlap(eligible_case)
        assert r.passed is True
        assert r.code == "DATES_OVERLAP"

    def test_exactly_on_window_start_passes(self):
        """Boundary: exposure on exactly 2001-09-11."""
        r = rule_exposure_date_overlap({
            "exposureDateStart": "2001-09-11",
            "exposureDateEnd": "2001-09-11",
        })
        assert r.passed is True

    def test_exactly_on_window_end_passes(self):
        """Boundary: exposure on exactly 2011-05-30."""
        r = rule_exposure_date_overlap({
            "exposureDateStart": "2011-05-30",
            "exposureDateEnd": "2011-05-30",
        })
        assert r.passed is True

    def test_one_day_before_window_start_fails(self):
        """Exposure ends the day before VCF window opens."""
        r = rule_exposure_date_overlap({
            "exposureDateStart": "2001-09-01",
            "exposureDateEnd": "2001-09-10",
        })
        assert r.passed is False
        assert r.code == "DATES_OUTSIDE_WINDOW"

    def test_one_day_after_window_end_fails(self):
        """Exposure starts the day after VCF window closes."""
        r = rule_exposure_date_overlap({
            "exposureDateStart": "2011-05-31",
            "exposureDateEnd": "2012-01-01",
        })
        assert r.passed is False

    def test_spans_entire_window_passes(self):
        """Exposure spans entire VCF window."""
        r = rule_exposure_date_overlap({
            "exposureDateStart": "2000-01-01",
            "exposureDateEnd": "2015-01-01",
        })
        assert r.passed is True

    def test_missing_start_date_fails(self):
        r = rule_exposure_date_overlap({"exposureDateEnd": "2002-01-01"})
        assert r.passed is False
        assert r.code == "MISSING_DATES"

    def test_missing_end_date_fails(self):
        r = rule_exposure_date_overlap({"exposureDateStart": "2001-09-11"})
        assert r.passed is False

    def test_invalid_date_format_fails(self):
        r = rule_exposure_date_overlap({
            "exposureDateStart": "not-a-date",
            "exposureDateEnd": "2002-01-01",
        })
        assert r.passed is False
        assert r.code == "MISSING_DATES"

    def test_dates_entirely_before_window_fail(self, ineligible_case):
        r = rule_exposure_date_overlap(ineligible_case)
        assert r.passed is False

    def test_partial_overlap_start_before_window(self):
        """Start before window, end within window."""
        r = rule_exposure_date_overlap({
            "exposureDateStart": "2000-01-01",
            "exposureDateEnd": "2001-09-15",
        })
        assert r.passed is True

    def test_partial_overlap_end_after_window(self):
        """Start within window, end after window."""
        r = rule_exposure_date_overlap({
            "exposureDateStart": "2011-05-15",
            "exposureDateEnd": "2015-01-01",
        })
        assert r.passed is True


# ── R03: WTC Health Program ───────────────────────────────────────────────────

class TestRuleWTCHealthProgram:
    def test_enrolled_is_pass(self):
        r = rule_wtc_health_program({"wtcHealthProgramStatus": "enrolled"})
        assert r.passed is True
        assert r.severity == "pass"

    def test_applied_is_pass(self):
        r = rule_wtc_health_program({"wtcHealthProgramStatus": "applied"})
        assert r.passed is True
        assert r.severity == "pass"

    def test_not_applied_is_soft_flag(self):
        r = rule_wtc_health_program({"wtcHealthProgramStatus": "not_applied"})
        assert r.passed is True  # Non-blocking
        assert r.severity == "soft_flag"

    def test_unknown_is_soft_flag(self):
        r = rule_wtc_health_program({"wtcHealthProgramStatus": "unknown"})
        assert r.severity == "soft_flag"

    def test_missing_status_is_soft_flag(self):
        r = rule_wtc_health_program({})
        assert r.severity == "soft_flag"


# ── R04: Prior attorney ───────────────────────────────────────────────────────

class TestRulePriorAttorney:
    def test_no_prior_attorney_is_pass(self):
        r = rule_prior_attorney({"priorAttorney": False})
        assert r.severity == "pass"
        assert r.code == "NO_PRIOR_ATTORNEY"

    def test_prior_attorney_is_soft_flag(self):
        r = rule_prior_attorney({"priorAttorney": True})
        assert r.passed is True  # Non-blocking
        assert r.severity == "soft_flag"
        assert r.code == "PRIOR_ATTORNEY_FLAG"

    def test_missing_prior_attorney_defaults_to_false(self):
        r = rule_prior_attorney({})
        assert r.severity == "pass"


# ── R05: Data completeness ────────────────────────────────────────────────────

class TestRuleDataCompleteness:
    def test_complete_data_passes(self, eligible_case):
        r = rule_minimum_data_completeness(eligible_case)
        assert r.passed is True
        assert r.code == "COMPLETE"

    def test_missing_email_hard_fails(self):
        data = {"firstName": "John", "lastName": "Doe", "phone": "+12125551234", "exposureLocation": "WTC"}
        r = rule_minimum_data_completeness(data)
        assert r.passed is False
        assert r.severity == "hard_fail"
        assert "email" in r.reason

    def test_missing_multiple_fields(self):
        r = rule_minimum_data_completeness({})
        assert r.passed is False
        assert r.severity == "hard_fail"

    def test_missing_first_name_fails(self):
        data = {"lastName": "Doe", "email": "x@x.com", "phone": "+1", "exposureLocation": "WTC"}
        r = rule_minimum_data_completeness(data)
        assert r.passed is False


# ── R06: Conditions ───────────────────────────────────────────────────────────

class TestRuleConditions:
    def test_matched_condition_is_pass(self):
        r = rule_conditions_match({"conditions": ["respiratory", "asthma"]})
        assert r.severity == "pass"
        assert r.code == "CONDITIONS_MATCHED"

    def test_cancer_matches(self):
        r = rule_conditions_match({"conditions": ["lung cancer"]})
        assert r.severity == "pass"

    def test_ptsd_matches_mental_health(self):
        r = rule_conditions_match({"conditions": ["ptsd"]})
        assert r.severity == "pass"

    def test_unmatched_condition_is_soft_flag(self):
        r = rule_conditions_match({"conditions": ["broken leg", "appendicitis"]})
        assert r.severity == "soft_flag"
        assert r.code == "CONDITIONS_UNMATCHED"

    def test_empty_conditions_is_soft_flag(self):
        r = rule_conditions_match({"conditions": []})
        assert r.severity == "soft_flag"
        assert r.code == "NO_CONDITIONS_PROVIDED"

    def test_missing_conditions_field_is_soft_flag(self):
        r = rule_conditions_match({})
        assert r.severity == "soft_flag"

    def test_multiple_conditions_any_match_passes(self):
        r = rule_conditions_match({"conditions": ["broken leg", "asthma", "headache"]})
        assert r.severity == "pass"


# ── Full screening results ────────────────────────────────────────────────────

class TestRunScreening:
    def test_eligible_result(self, eligible_case):
        result = run_screening("ZAD-TEST", eligible_case)
        assert result.eligibility == "eligible"
        assert result.score == 95
        assert result.flags == []

    def test_ineligible_result(self, ineligible_case):
        result = run_screening("ZAD-TEST", ineligible_case)
        assert result.eligibility == "ineligible"
        assert result.score == 0
        assert len(result.rule_results) > 0

    def test_needs_review_result(self, needs_review_case):
        result = run_screening("ZAD-TEST", needs_review_case)
        assert result.eligibility == "needs_review"
        assert result.score == 60
        assert len(result.flags) > 0

    def test_missing_all_fields_is_ineligible(self):
        result = run_screening("ZAD-TEST", {})
        assert result.eligibility == "ineligible"
        assert result.score == 0

    def test_result_to_dict_structure(self, eligible_case):
        result = run_screening("ZAD-TEST", eligible_case)
        d = result.to_dict()
        assert "eligibility" in d
        assert "score" in d
        assert "flags" in d
        assert "ruleResults" in d
        assert isinstance(d["ruleResults"], list)
        for rule in d["ruleResults"]:
            assert "ruleId" in rule
            assert "passed" in rule
            assert "code" in rule

    def test_single_hard_fail_overrides_soft_flags(self):
        """Even with soft flags present, a hard fail = ineligible."""
        case = {
            "firstName": "Test", "lastName": "User",
            "email": "t@t.com", "phone": "+1",
            "exposureLocation": "World Trade Center",
            "exposureDateStart": "2001-09-11",
            "exposureDateEnd": "2002-01-01",
            "wtcHealthProgramStatus": "not_applied",  # soft flag
            "priorAttorney": True,  # soft flag
            # BUT location is good, dates are good, just missing conditions
            # Let's use a bad date to cause hard fail
            "exposureDateStart": "2020-01-01",
            "exposureDateEnd": "2021-01-01",
        }
        result = run_screening("ZAD-TEST", case)
        assert result.eligibility == "ineligible"
        assert result.score == 0
