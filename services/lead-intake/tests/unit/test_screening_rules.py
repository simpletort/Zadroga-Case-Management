"""
tests/unit/test_screening_rules.py

Tests for the configurable VCF screening rule engine:
  - _run_operator()      — per-operator unit tests (fields_not_empty, in_list,
                           date_overlap, boolean_equals, number_in_range, unknown)
  - _evaluate_rule()     — pass/fail → severity/code/reason mapping
  - _fetch_rules()       — Firestore fetch and module-level cache lifecycle
  - reset_rules_cache()
  - run_screening()      — end-to-end ELIGIBLE/NEEDS_REVIEW/INELIGIBLE scoring
  - CreateScreeningRuleRequest / ScreeningRuleParams — Pydantic validation
  - GET  /admin/settings/screening-rules
  - POST /admin/settings/screening-rules
  - GET  /admin/settings/screening-rules/{rule_id}
  - PUT  /admin/settings/screening-rules/{rule_id}
  - DELETE /admin/settings/screening-rules/{rule_id}
"""
from __future__ import annotations

import asyncio
import os
import sys
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../api"))

import pytest
from pydantic import ValidationError


# ── Async iterator helper ─────────────────────────────────────────────────────
# Used to mock Firestore query.stream() which is consumed with `async for`.

async def _aiter(items):
    for item in items:
        yield item


# ── Shared fixtures ────────────────────────────────────────────────────────────

def _make_partner_context(role: str = "system_admin"):
    from middleware.auth import PartnerContext
    return PartnerContext(
        partner_id  = "test-partner",
        auth_method = "firebase_jwt",
        raw_claims  = {"role": role, "email": "admin@test.com"},
    )


# Minimal rule dict that satisfies _evaluate_rule and run_screening.
_HARD_FAIL_RULE = {
    "ruleId":     "R01_SITE",
    "operator":   "in_list",
    "params":     {"field": "exposureLocation", "values": ["world trade center", "wtc"], "match_type": "substring"},
    "severity":   "hard_fail",
    "enabled":    True,
    "order":      10,
    "passCode":   "ELIGIBLE_SITE",
    "failCode":   "INELIGIBLE_SITE",
    "passReason": "Location matches a VCF site",
    "failReason": "Location does not match known VCF sites",
}

_SOFT_FLAG_RULE = {
    "ruleId":     "R04_PRIOR_ATTORNEY",
    "operator":   "boolean_equals",
    "params":     {"field": "priorAttorney", "expected": False},
    "severity":   "soft_flag",
    "enabled":    True,
    "order":      40,
    "passCode":   "NO_PRIOR_ATTORNEY",
    "failCode":   "PRIOR_ATTORNEY_FLAG",
    "passReason": "No prior attorney",
    "failReason": "Has prior attorney — manual review required",
}

_SAMPLE_CASE = {
    "firstName":             "John",
    "lastName":              "Doe",
    "email":                 "john@example.com",
    "phone":                 "+12125551234",
    "exposureLocation":      "world trade center",
    "exposureDateStart":     "2001-09-11",
    "exposureDateEnd":       "2002-06-30",
    "wtcHealthProgramStatus": "enrolled",
    "priorAttorney":         False,
    "conditions":            ["respiratory", "asthma"],
}

# A complete valid rule body for POST/PUT requests
_VALID_RULE_BODY = {
    "ruleId":      "R01_EXPOSURE_SITE",
    "name":        "Exposure Site Check",
    "description": "Location must be a recognised VCF site",
    "enabled":     True,
    "severity":    "hard_fail",
    "operator":    "in_list",
    "params": {
        "field":      "exposureLocation",
        "values":     ["world trade center", "wtc", "ground zero"],
        "match_type": "substring",
    },
    "passCode":   "ELIGIBLE_SITE",
    "failCode":   "INELIGIBLE_SITE",
    "passReason": "Location matches a recognised VCF site",
    "failReason": "Location does not match known VCF sites",
    "order":      10,
}

# Firestore doc dict that matches ScreeningRuleResponse
_RULE_DOC = {
    **_VALID_RULE_BODY,
    "updatedAt": datetime.utcnow().isoformat() + "Z",
    "updatedBy": "admin@test.com",
    "createdAt": datetime.utcnow().isoformat() + "Z",
}


# ── Helper: build Firestore mock for CRUD operations ─────────────────────────

def _mock_db_doc_absent():
    """db.collection().document().get() → doc.exists=False."""
    mock_doc = MagicMock()
    mock_doc.exists = False
    mock_doc_ref = AsyncMock()
    mock_doc_ref.get    = AsyncMock(return_value=mock_doc)
    mock_doc_ref.set    = AsyncMock()
    mock_doc_ref.delete = AsyncMock()
    mock_col = MagicMock()
    mock_col.document.return_value = mock_doc_ref
    mock_db = MagicMock()
    mock_db.collection.return_value = mock_col
    return mock_db


def _mock_db_doc_present(data: dict):
    """db.collection().document().get() → doc.exists=True with data."""
    mock_doc = MagicMock()
    mock_doc.exists = True
    mock_doc.to_dict.return_value = data
    mock_doc_ref = AsyncMock()
    mock_doc_ref.get    = AsyncMock(return_value=mock_doc)
    mock_doc_ref.set    = AsyncMock()
    mock_doc_ref.delete = AsyncMock()
    mock_col = MagicMock()
    mock_col.document.return_value = mock_doc_ref
    mock_db = MagicMock()
    mock_db.collection.return_value = mock_col
    return mock_db


def _mock_db_for_list(rule_dicts: list[dict]):
    """db.collection().order_by().stream() → async iterator of docs."""
    def _make_doc(d):
        doc = MagicMock()
        doc.to_dict.return_value = d
        return doc

    mock_query = MagicMock()
    mock_query.stream.return_value = _aiter([_make_doc(d) for d in rule_dicts])
    mock_col = MagicMock()
    mock_col.order_by.return_value = mock_query
    mock_db = MagicMock()
    mock_db.collection.return_value = mock_col
    return mock_db


def _mock_db_for_fetch_rules(rule_dicts: list[dict]):
    """db.collection().where().order_by().stream() — for _fetch_rules()."""
    def _make_doc(d):
        doc = MagicMock()
        doc.to_dict.return_value = d
        return doc

    mock_query = MagicMock()
    mock_query.stream.return_value = _aiter([_make_doc(d) for d in rule_dicts])
    mock_chain = MagicMock()
    mock_chain.order_by.return_value = mock_query
    mock_col = MagicMock()
    mock_col.where.return_value = mock_chain
    mock_db = MagicMock()
    mock_db.collection.return_value = mock_col
    return mock_db


# ═══════════════════════════════════════════════════════════════════════════════
# 1. _run_operator() — per-operator unit tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestRunOperator:
    def setup_method(self):
        from services.vcf_screener import _run_operator
        self._run = _run_operator

    # ── fields_not_empty ─────────────────────────────────────────────────────

    def test_fields_not_empty_all_present(self):
        met, _ = self._run("fields_not_empty",
                           {"fields": ["firstName", "lastName"]},
                           {"firstName": "John", "lastName": "Doe"})
        assert met is True

    def test_fields_not_empty_one_missing(self):
        met, detail = self._run("fields_not_empty",
                                {"fields": ["firstName", "email"]},
                                {"firstName": "John"})
        assert met is False
        assert "email" in detail

    def test_fields_not_empty_empty_string_counts_as_missing(self):
        met, _ = self._run("fields_not_empty",
                           {"fields": ["firstName"]},
                           {"firstName": ""})
        assert met is False

    def test_fields_not_empty_empty_fields_list(self):
        """No required fields configured → always passes."""
        met, _ = self._run("fields_not_empty", {"fields": []}, {})
        assert met is True

    # ── in_list (substring) ───────────────────────────────────────────────────

    def test_in_list_substring_match(self):
        met, _ = self._run("in_list",
                           {"field": "loc", "values": ["world trade center"], "match_type": "substring"},
                           {"loc": "World Trade Center, Manhattan"})
        assert met is True

    def test_in_list_no_match(self):
        met, _ = self._run("in_list",
                           {"field": "loc", "values": ["world trade center"], "match_type": "substring"},
                           {"loc": "Los Angeles"})
        assert met is False

    def test_in_list_exact_match(self):
        met, _ = self._run("in_list",
                           {"field": "status", "values": ["enrolled", "applied"], "match_type": "exact"},
                           {"status": "enrolled"})
        assert met is True

    def test_in_list_exact_no_match(self):
        met, _ = self._run("in_list",
                           {"field": "status", "values": ["enrolled", "applied"], "match_type": "exact"},
                           {"status": "not_applied"})
        assert met is False

    def test_in_list_array_field_any_match(self):
        """Array field: passes if ANY element matches."""
        met, _ = self._run("in_list",
                           {"field": "conditions", "values": ["cancer", "asthma"], "match_type": "substring"},
                           {"conditions": ["respiratory", "asthma", "gerd"]})
        assert met is True

    def test_in_list_array_field_no_match(self):
        met, _ = self._run("in_list",
                           {"field": "conditions", "values": ["cancer"], "match_type": "substring"},
                           {"conditions": ["headache", "joint pain"]})
        assert met is False

    def test_in_list_missing_field(self):
        met, detail = self._run("in_list",
                                {"field": "loc", "values": ["wtc"]},
                                {})
        assert met is False
        assert "loc" in detail

    # ── date_overlap ──────────────────────────────────────────────────────────

    def test_date_overlap_fully_inside_range(self):
        met, _ = self._run("date_overlap",
                           {"field_start": "start", "field_end": "end",
                            "range_start": "2001-09-11", "range_end": "2011-05-30"},
                           {"start": "2003-01-01", "end": "2005-01-01"})
        assert met is True

    def test_date_overlap_partial_overlap_start(self):
        met, _ = self._run("date_overlap",
                           {"field_start": "start", "field_end": "end",
                            "range_start": "2001-09-11", "range_end": "2011-05-30"},
                           {"start": "2000-01-01", "end": "2002-01-01"})
        assert met is True

    def test_date_overlap_entirely_before_range(self):
        met, _ = self._run("date_overlap",
                           {"field_start": "start", "field_end": "end",
                            "range_start": "2001-09-11", "range_end": "2011-05-30"},
                           {"start": "1999-01-01", "end": "2001-01-01"})
        assert met is False

    def test_date_overlap_entirely_after_range(self):
        met, _ = self._run("date_overlap",
                           {"field_start": "start", "field_end": "end",
                            "range_start": "2001-09-11", "range_end": "2011-05-30"},
                           {"start": "2015-01-01", "end": "2016-01-01"})
        assert met is False

    def test_date_overlap_missing_field_returns_false(self):
        met, detail = self._run("date_overlap",
                                {"field_start": "start", "field_end": "end",
                                 "range_start": "2001-09-11", "range_end": "2011-05-30"},
                                {})   # missing both date fields
        assert met is False
        assert "error" in detail.lower() or "parse" in detail.lower()

    # ── boolean_equals ────────────────────────────────────────────────────────

    def test_boolean_equals_false_false_passes(self):
        met, _ = self._run("boolean_equals",
                           {"field": "priorAttorney", "expected": False},
                           {"priorAttorney": False})
        assert met is True

    def test_boolean_equals_true_true_passes(self):
        met, _ = self._run("boolean_equals",
                           {"field": "enrolled", "expected": True},
                           {"enrolled": True})
        assert met is True

    def test_boolean_equals_true_false_fails(self):
        met, _ = self._run("boolean_equals",
                           {"field": "priorAttorney", "expected": False},
                           {"priorAttorney": True})
        assert met is False

    def test_boolean_equals_string_true_coerced(self):
        """String "true" is treated as boolean True."""
        met, _ = self._run("boolean_equals",
                           {"field": "flag", "expected": True},
                           {"flag": "true"})
        assert met is True

    # ── number_in_range ───────────────────────────────────────────────────────

    def test_number_in_range_within_bounds(self):
        met, _ = self._run("number_in_range",
                           {"field": "score", "min": 0.0, "max": 100.0},
                           {"score": 75})
        assert met is True

    def test_number_in_range_below_min(self):
        met, _ = self._run("number_in_range",
                           {"field": "score", "min": 50.0, "max": 100.0},
                           {"score": 10})
        assert met is False

    def test_number_in_range_above_max(self):
        met, _ = self._run("number_in_range",
                           {"field": "score", "min": 0.0, "max": 50.0},
                           {"score": 99})
        assert met is False

    def test_number_in_range_no_min_bound(self):
        met, _ = self._run("number_in_range",
                           {"field": "score", "max": 100.0},
                           {"score": -999})
        assert met is True

    def test_number_in_range_non_numeric_field_fails(self):
        met, detail = self._run("number_in_range",
                                {"field": "score", "min": 0.0, "max": 100.0},
                                {"score": "not-a-number"})
        assert met is False
        assert "numeric" in detail.lower()

    # ── unknown operator ──────────────────────────────────────────────────────

    def test_unknown_operator_passes_by_default(self):
        """Forward-compatible: unknown operator must not block the lead."""
        met, detail = self._run("future_operator_v9", {}, {})
        assert met is True
        assert "Unknown" in detail or "unknown" in detail


# ═══════════════════════════════════════════════════════════════════════════════
# 2. _evaluate_rule() — severity and code/reason routing
# ═══════════════════════════════════════════════════════════════════════════════

class TestEvaluateRule:
    def setup_method(self):
        from services.vcf_screener import _evaluate_rule
        self._eval = _evaluate_rule

    def test_hard_fail_condition_met_returns_pass(self):
        rule = {**_HARD_FAIL_RULE}
        res  = self._eval(rule, {**_SAMPLE_CASE})
        assert res.passed   is True
        assert res.severity == "pass"
        assert res.code     == "ELIGIBLE_SITE"

    def test_hard_fail_condition_not_met_returns_failed(self):
        res = self._eval(_HARD_FAIL_RULE, {**_SAMPLE_CASE, "exposureLocation": "Los Angeles"})
        assert res.passed   is False
        assert res.severity == "hard_fail"
        assert res.code     == "INELIGIBLE_SITE"

    def test_soft_flag_condition_met_returns_pass(self):
        res = self._eval(_SOFT_FLAG_RULE, {**_SAMPLE_CASE, "priorAttorney": False})
        assert res.passed   is True
        assert res.severity == "pass"
        assert res.code     == "NO_PRIOR_ATTORNEY"

    def test_soft_flag_condition_not_met_returns_soft_flag_but_passed_true(self):
        """Soft flag keeps passed=True — only the severity changes."""
        res = self._eval(_SOFT_FLAG_RULE, {**_SAMPLE_CASE, "priorAttorney": True})
        assert res.passed   is True
        assert res.severity == "soft_flag"
        assert res.code     == "PRIOR_ATTORNEY_FLAG"

    def test_rule_id_propagated_to_result(self):
        res = self._eval(_HARD_FAIL_RULE, {**_SAMPLE_CASE})
        assert res.rule_id == "R01_SITE"

    def test_custom_fail_reason_used(self):
        res = self._eval(_HARD_FAIL_RULE, {**_SAMPLE_CASE, "exposureLocation": "nowhere"})
        assert res.reason == "Location does not match known VCF sites"

    def test_operator_detail_used_when_fail_reason_absent(self):
        """If failReason is omitted, the operator's own detail message is used."""
        rule = {**_HARD_FAIL_RULE, "failReason": ""}
        res  = self._eval(rule, {**_SAMPLE_CASE, "exposureLocation": "nowhere"})
        assert len(res.reason) > 0


# ═══════════════════════════════════════════════════════════════════════════════
# 3. _fetch_rules() cache lifecycle + reset_rules_cache()
# ═══════════════════════════════════════════════════════════════════════════════

class TestRulesCache:
    def _reset(self):
        import services.vcf_screener as sv
        sv._rules_cache = None

    def test_reset_rules_cache_clears_to_none(self):
        import services.vcf_screener as sv
        sv._rules_cache = [{"ruleId": "R01"}]
        from services.vcf_screener import reset_rules_cache
        reset_rules_cache()
        assert sv._rules_cache is None

    def test_fetch_rules_returns_cached_without_firestore(self):
        import services.vcf_screener as sv
        sv._rules_cache = [{"ruleId": "CACHED"}]
        from services.vcf_screener import _fetch_rules

        mock_db = AsyncMock()
        result  = asyncio.run(_fetch_rules(mock_db))

        assert result == [{"ruleId": "CACHED"}]
        mock_db.collection.assert_not_called()

    def test_fetch_rules_reads_firestore_on_cache_miss(self):
        self._reset()
        from services.vcf_screener import _fetch_rules

        mock_db = _mock_db_for_fetch_rules([_HARD_FAIL_RULE])
        result  = asyncio.run(_fetch_rules(mock_db))

        assert len(result) == 1
        assert result[0]["ruleId"] == "R01_SITE"

    def test_fetch_rules_only_enabled_rules_queried(self):
        """The Firestore where() clause must filter on enabled==True."""
        self._reset()
        from services.vcf_screener import _fetch_rules

        mock_db = _mock_db_for_fetch_rules([])
        asyncio.run(_fetch_rules(mock_db))

        mock_db.collection.assert_called_once_with("screeningRules")
        mock_col = mock_db.collection.return_value
        mock_col.where.assert_called_once_with("enabled", "==", True)

    def test_fetch_rules_result_cached_after_first_call(self):
        self._reset()
        from services.vcf_screener import _fetch_rules

        mock_db = _mock_db_for_fetch_rules([_HARD_FAIL_RULE])
        asyncio.run(_fetch_rules(mock_db))   # first — hits Firestore
        asyncio.run(_fetch_rules(mock_db))   # second — must use cache

        # stream() should only have been consumed once
        mock_query = mock_db.collection.return_value.where.return_value.order_by.return_value
        assert mock_query.stream.call_count == 1

    def test_fetch_rules_empty_collection_returns_empty_list(self):
        self._reset()
        from services.vcf_screener import _fetch_rules

        mock_db = _mock_db_for_fetch_rules([])
        result  = asyncio.run(_fetch_rules(mock_db))

        assert result == []


# ═══════════════════════════════════════════════════════════════════════════════
# 4. run_screening() — end-to-end scoring logic
# ═══════════════════════════════════════════════════════════════════════════════

class TestRunScreening:
    def _reset(self):
        import services.vcf_screener as sv
        sv._rules_cache = None

    def _run(self, rules: list[dict], case_data: dict):
        import services.vcf_screener as sv
        sv._rules_cache = rules          # inject rules directly via cache
        from services.vcf_screener import run_screening
        return asyncio.run(run_screening("CASE-2026-01-0001", case_data, AsyncMock()))

    def test_no_rules_returns_eligible(self):
        """Empty rule set → all leads pass → ELIGIBLE, score 95."""
        res = self._run([], _SAMPLE_CASE)
        assert res.eligibility == "eligible"
        assert res.score       == 95
        assert res.flags       == []

    def test_single_hard_fail_returns_ineligible(self):
        res = self._run([_HARD_FAIL_RULE], {**_SAMPLE_CASE, "exposureLocation": "Los Angeles"})
        assert res.eligibility == "ineligible"
        assert res.score       == 0

    def test_hard_fail_rule_passes_returns_eligible(self):
        res = self._run([_HARD_FAIL_RULE], _SAMPLE_CASE)
        assert res.eligibility == "eligible"
        assert res.score       == 95

    def test_soft_flag_returns_needs_review(self):
        res = self._run([_SOFT_FLAG_RULE], {**_SAMPLE_CASE, "priorAttorney": True})
        assert res.eligibility == "needs_review"
        assert res.score       == 60
        assert len(res.flags)  == 1

    def test_hard_fail_takes_precedence_over_soft_flag(self):
        """Even when a soft flag fires, a hard fail must still win."""
        case = {**_SAMPLE_CASE, "exposureLocation": "Los Angeles", "priorAttorney": True}
        res  = self._run([_HARD_FAIL_RULE, _SOFT_FLAG_RULE], case)
        assert res.eligibility == "ineligible"
        assert res.score       == 0

    def test_all_rules_pass_eligible(self):
        case = {**_SAMPLE_CASE, "exposureLocation": "world trade center", "priorAttorney": False}
        res  = self._run([_HARD_FAIL_RULE, _SOFT_FLAG_RULE], case)
        assert res.eligibility == "eligible"
        assert res.score       == 95
        assert res.flags       == []

    def test_multiple_soft_flags_accumulate(self):
        soft1 = {**_SOFT_FLAG_RULE, "ruleId": "S1"}
        soft2 = {
            "ruleId":   "S2",
            "operator": "in_list",
            "params":   {"field": "wtcHealthProgramStatus", "values": ["enrolled", "applied"], "match_type": "exact"},
            "severity": "soft_flag",
            "enabled":  True,
            "order":    50,
            "passCode": "ENROLLED",
            "failCode": "NOT_ENROLLED",
            "passReason": "Enrolled",
            "failReason": "Not enrolled — manual review",
        }
        case = {**_SAMPLE_CASE, "priorAttorney": True, "wtcHealthProgramStatus": "not_applied"}
        res  = self._run([soft1, soft2], case)
        assert res.eligibility == "needs_review"
        assert len(res.flags)  == 2

    def test_rule_results_list_populated(self):
        res = self._run([_HARD_FAIL_RULE, _SOFT_FLAG_RULE], _SAMPLE_CASE)
        assert len(res.rule_results) == 2
        ids = [r.rule_id for r in res.rule_results]
        assert "R01_SITE" in ids
        assert "R04_PRIOR_ATTORNEY" in ids

    def test_case_id_propagated(self):
        import services.vcf_screener as sv
        sv._rules_cache = []
        from services.vcf_screener import run_screening
        res = asyncio.run(run_screening("ZAD-2026-06-0007", _SAMPLE_CASE, AsyncMock()))
        assert res.case_id == "ZAD-2026-06-0007"

    def test_case_status_property_eligible(self):
        res = self._run([], _SAMPLE_CASE)
        assert res.case_status == "Qualified"

    def test_case_status_property_ineligible(self):
        res = self._run([_HARD_FAIL_RULE], {**_SAMPLE_CASE, "exposureLocation": "nowhere"})
        assert res.case_status == "Disqualified"

    def test_to_dict_contains_rule_results(self):
        res  = self._run([_HARD_FAIL_RULE], _SAMPLE_CASE)
        data = res.to_dict()
        assert "eligibility"  in data
        assert "score"        in data
        assert "flags"        in data
        assert "ruleResults"  in data
        assert len(data["ruleResults"]) == 1


# ═══════════════════════════════════════════════════════════════════════════════
# 5. Pydantic model validation
# ═══════════════════════════════════════════════════════════════════════════════

class TestCreateScreeningRuleRequest:
    def _make(self, **overrides):
        from routers.settings import CreateScreeningRuleRequest
        body = {**_VALID_RULE_BODY, **overrides}
        return CreateScreeningRuleRequest(**body)

    def test_valid_in_list_rule(self):
        req = self._make()
        assert req.ruleId   == "R01_EXPOSURE_SITE"
        assert req.operator == "in_list"
        assert req.severity == "hard_fail"

    def test_valid_fields_not_empty_rule(self):
        req = self._make(
            ruleId   = "R05_COMPLETENESS",
            operator = "fields_not_empty",
            params   = {"fields": ["firstName", "lastName", "email"]},
            passCode = "COMPLETE",
            failCode = "INCOMPLETE",
        )
        assert req.operator == "fields_not_empty"

    def test_valid_date_overlap_rule(self):
        req = self._make(
            ruleId   = "R02_DATES",
            operator = "date_overlap",
            params   = {"field_start": "exposureDateStart", "field_end": "exposureDateEnd",
                        "range_start": "2001-09-11", "range_end": "2011-05-30"},
            passCode = "DATES_OVERLAP",
            failCode = "DATES_OUTSIDE_WINDOW",
        )
        assert req.operator == "date_overlap"

    def test_valid_boolean_equals_rule(self):
        req = self._make(
            ruleId   = "R04_ATTORNEY",
            operator = "boolean_equals",
            params   = {"field": "priorAttorney", "expected": False},
            severity = "soft_flag",
            passCode = "NO_PRIOR",
            failCode = "HAS_PRIOR",
        )
        assert req.severity == "soft_flag"

    def test_valid_number_in_range_rule(self):
        req = self._make(
            ruleId   = "SCORE_RANGE",
            operator = "number_in_range",
            params   = {"field": "score", "min": 0.0, "max": 100.0},
            passCode = "IN_RANGE",
            failCode = "OUT_OF_RANGE",
        )
        assert req.operator == "number_in_range"

    def test_invalid_operator_rejected(self):
        with pytest.raises(ValidationError):
            self._make(operator="custom_operator")

    def test_invalid_severity_rejected(self):
        with pytest.raises(ValidationError):
            self._make(severity="warning")

    def test_lowercase_rule_id_rejected(self):
        with pytest.raises(ValidationError):
            self._make(ruleId="r01_site")   # lowercase not allowed

    def test_rule_id_with_spaces_rejected(self):
        with pytest.raises(ValidationError):
            self._make(ruleId="R01 SITE")

    def test_rule_id_too_long_rejected(self):
        with pytest.raises(ValidationError):
            self._make(ruleId="A" * 51)

    def test_empty_pass_code_rejected(self):
        with pytest.raises(ValidationError):
            self._make(passCode="")

    def test_empty_fail_code_rejected(self):
        with pytest.raises(ValidationError):
            self._make(failCode="")

    def test_negative_order_rejected(self):
        with pytest.raises(ValidationError):
            self._make(order=-1)

    def test_disabled_rule_accepted(self):
        req = self._make(enabled=False)
        assert req.enabled is False


# ═══════════════════════════════════════════════════════════════════════════════
# 6. Screening-rules CRUD router endpoints
# ═══════════════════════════════════════════════════════════════════════════════

class TestScreeningRulesRouter:
    """Tests for all 5 /admin/settings/screening-rules endpoints."""

    def setup_method(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from routers.settings import router
        from middleware.auth import get_partner
        from services.firestore_client import get_db

        self.app         = FastAPI()
        self.app.include_router(router, prefix="/api/v1")
        self.get_partner = get_partner
        self.get_db      = get_db
        self.TestClient  = TestClient

    def _client(self, role: str = "system_admin", mock_db=None):
        from fastapi.testclient import TestClient
        partner = _make_partner_context(role)
        self.app.dependency_overrides[self.get_partner] = lambda: partner
        self.app.dependency_overrides[self.get_db]      = lambda: mock_db or AsyncMock()
        return TestClient(self.app)

    # ── GET /screening-rules ─────────────────────────────────────────────────

    def test_list_returns_empty_array_when_no_rules(self):
        client = self._client(mock_db=_mock_db_for_list([]))
        resp   = client.get("/api/v1/admin/settings/screening-rules")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_list_returns_all_rules(self):
        client = self._client(mock_db=_mock_db_for_list([_RULE_DOC, {**_RULE_DOC, "ruleId": "R02"}]))
        resp   = client.get("/api/v1/admin/settings/screening-rules")
        assert resp.status_code == 200
        assert len(resp.json()) == 2

    def test_list_rejected_for_non_admin(self):
        client = self._client(role="paralegal", mock_db=_mock_db_for_list([]))
        resp   = client.get("/api/v1/admin/settings/screening-rules")
        assert resp.status_code == 403

    # ── POST /screening-rules ────────────────────────────────────────────────

    def test_post_creates_rule_and_returns_201(self):
        with patch("routers.settings.reset_rules_cache"):
            client = self._client(mock_db=_mock_db_doc_absent())
            resp   = client.post("/api/v1/admin/settings/screening-rules", json=_VALID_RULE_BODY)
        assert resp.status_code == 201
        data = resp.json()
        assert data["ruleId"]   == _VALID_RULE_BODY["ruleId"]
        assert data["operator"] == _VALID_RULE_BODY["operator"]
        assert data["severity"] == _VALID_RULE_BODY["severity"]

    def test_post_returns_409_when_rule_id_exists(self):
        with patch("routers.settings.reset_rules_cache"):
            client = self._client(mock_db=_mock_db_doc_present(_RULE_DOC))
            resp   = client.post("/api/v1/admin/settings/screening-rules", json=_VALID_RULE_BODY)
        assert resp.status_code == 409
        assert resp.json()["detail"]["error"] == "CONFLICT"

    def test_post_resets_rules_cache(self):
        import services.vcf_screener as sv
        sv._rules_cache = [{"ruleId": "OLD"}]
        client = self._client(mock_db=_mock_db_doc_absent())
        client.post("/api/v1/admin/settings/screening-rules", json=_VALID_RULE_BODY)
        assert sv._rules_cache is None

    def test_post_stores_to_firestore(self):
        mock_db = _mock_db_doc_absent()
        with patch("routers.settings.reset_rules_cache"):
            client = self._client(mock_db=mock_db)
            client.post("/api/v1/admin/settings/screening-rules", json=_VALID_RULE_BODY)
        mock_db.collection.return_value.document.return_value.set.assert_awaited_once()

    def test_post_rejects_invalid_operator(self):
        client = self._client()
        body   = {**_VALID_RULE_BODY, "operator": "unsupported_op"}
        resp   = client.post("/api/v1/admin/settings/screening-rules", json=body)
        assert resp.status_code == 422

    def test_post_rejects_invalid_severity(self):
        client = self._client()
        body   = {**_VALID_RULE_BODY, "severity": "warning"}
        resp   = client.post("/api/v1/admin/settings/screening-rules", json=body)
        assert resp.status_code == 422

    def test_post_rejected_for_non_admin(self):
        client = self._client(role="junior_partner")
        resp   = client.post("/api/v1/admin/settings/screening-rules", json=_VALID_RULE_BODY)
        assert resp.status_code == 403

    # ── GET /screening-rules/{rule_id} ───────────────────────────────────────

    def test_get_rule_returns_200_with_data(self):
        client = self._client(mock_db=_mock_db_doc_present(_RULE_DOC))
        resp   = client.get("/api/v1/admin/settings/screening-rules/R01_EXPOSURE_SITE")
        assert resp.status_code == 200
        assert resp.json()["ruleId"] == _RULE_DOC["ruleId"]

    def test_get_rule_returns_404_when_not_found(self):
        client = self._client(mock_db=_mock_db_doc_absent())
        resp   = client.get("/api/v1/admin/settings/screening-rules/NONEXISTENT")
        assert resp.status_code == 404
        assert resp.json()["detail"]["error"] == "NOT_FOUND"

    def test_get_rule_rejected_for_non_admin(self):
        client = self._client(role="admin_staff")
        resp   = client.get("/api/v1/admin/settings/screening-rules/R01_EXPOSURE_SITE")
        assert resp.status_code == 403

    # ── PUT /screening-rules/{rule_id} ───────────────────────────────────────

    def test_put_updates_rule_and_returns_200(self):
        updated_body = {**_VALID_RULE_BODY, "name": "Updated Site Check"}
        with patch("routers.settings.reset_rules_cache"):
            client = self._client(mock_db=_mock_db_doc_present(_RULE_DOC))
            resp   = client.put(
                "/api/v1/admin/settings/screening-rules/R01_EXPOSURE_SITE",
                json=updated_body,
            )
        assert resp.status_code == 200

    def test_put_returns_404_when_rule_not_found(self):
        with patch("routers.settings.reset_rules_cache"):
            client = self._client(mock_db=_mock_db_doc_absent())
            resp   = client.put(
                "/api/v1/admin/settings/screening-rules/NONEXISTENT",
                json=_VALID_RULE_BODY,
            )
        assert resp.status_code == 404
        assert resp.json()["detail"]["error"] == "NOT_FOUND"

    def test_put_resets_rules_cache(self):
        import services.vcf_screener as sv
        sv._rules_cache = [{"ruleId": "STALE"}]
        client = self._client(mock_db=_mock_db_doc_present(_RULE_DOC))
        client.put(
            "/api/v1/admin/settings/screening-rules/R01_EXPOSURE_SITE",
            json=_VALID_RULE_BODY,
        )
        assert sv._rules_cache is None

    def test_put_calls_set_with_merge_false(self):
        mock_db  = _mock_db_doc_present(_RULE_DOC)
        doc_ref  = mock_db.collection.return_value.document.return_value
        with patch("routers.settings.reset_rules_cache"):
            client = self._client(mock_db=mock_db)
            client.put(
                "/api/v1/admin/settings/screening-rules/R01_EXPOSURE_SITE",
                json=_VALID_RULE_BODY,
            )
        call_kwargs = doc_ref.set.call_args
        # merge=False must be passed (full replacement, not merge)
        assert call_kwargs.kwargs.get("merge") is False or (
            len(call_kwargs.args) > 1 and call_kwargs.args[1] is False
        ) or call_kwargs.kwargs.get("merge") is False

    def test_put_rejected_for_non_admin(self):
        client = self._client(role="paralegal")
        resp   = client.put(
            "/api/v1/admin/settings/screening-rules/R01_EXPOSURE_SITE",
            json=_VALID_RULE_BODY,
        )
        assert resp.status_code == 403

    # ── DELETE /screening-rules/{rule_id} ────────────────────────────────────

    def test_delete_returns_204(self):
        with patch("routers.settings.reset_rules_cache"):
            client = self._client(mock_db=_mock_db_doc_present(_RULE_DOC))
            resp   = client.delete("/api/v1/admin/settings/screening-rules/R01_EXPOSURE_SITE")
        assert resp.status_code == 204

    def test_delete_returns_404_when_not_found(self):
        with patch("routers.settings.reset_rules_cache"):
            client = self._client(mock_db=_mock_db_doc_absent())
            resp   = client.delete("/api/v1/admin/settings/screening-rules/NONEXISTENT")
        assert resp.status_code == 404
        assert resp.json()["detail"]["error"] == "NOT_FOUND"

    def test_delete_resets_rules_cache(self):
        import services.vcf_screener as sv
        sv._rules_cache = [{"ruleId": "STALE"}]
        client = self._client(mock_db=_mock_db_doc_present(_RULE_DOC))
        client.delete("/api/v1/admin/settings/screening-rules/R01_EXPOSURE_SITE")
        assert sv._rules_cache is None

    def test_delete_calls_firestore_delete(self):
        mock_db = _mock_db_doc_present(_RULE_DOC)
        doc_ref = mock_db.collection.return_value.document.return_value
        with patch("routers.settings.reset_rules_cache"):
            client = self._client(mock_db=mock_db)
            client.delete("/api/v1/admin/settings/screening-rules/R01_EXPOSURE_SITE")
        doc_ref.delete.assert_awaited_once()

    def test_delete_rejected_for_non_admin(self):
        client = self._client(role="admin_staff")
        resp   = client.delete("/api/v1/admin/settings/screening-rules/R01_EXPOSURE_SITE")
        assert resp.status_code == 403
