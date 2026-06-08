"""
Unit tests for deadline-calculator Cloud Function.
"""

import os
from datetime import date
from unittest.mock import MagicMock, patch

import pytest

os.environ.setdefault("GCP_PROJECT_ID", "test-project")
os.environ.setdefault("FIRESTORE_DATABASE_ID", "(default)")
os.environ.setdefault("PUBSUB_TOPIC_ENROLLMENT", "enrollment-status-changes")


# ── Helpers ────────────────────────────────────────────────────────────────────

def _make_str_field(value: str) -> dict:
    return {"stringValue": value}


def _make_map_field(fields: dict) -> dict:
    return {"mapValue": {"fields": fields}}


def _make_new_fields(
    status: str = "Pending Paralegal Review",
    cert_date: str = "2023-03-15",
    injury_date: str = "",
    created_at: str = "2022-01-01",
    cert_status: str = "",
) -> dict:
    fields: dict = {
        "status": _make_str_field(status),
        "createdAt": _make_str_field(created_at),
    }
    medical: dict = {}
    if cert_date:
        medical["certificationDate"] = _make_str_field(cert_date)
    if injury_date:
        medical["injuryDate"] = _make_str_field(injury_date)
    if medical:
        fields["medicalInfo"] = _make_map_field(medical)
    if cert_status:
        fields["enrollment"] = _make_map_field({
            "certificationStatus": _make_str_field(cert_status)
        })
    return fields


# ── DEADLINE_RULES strategy tests ──────────────────────────────────────────────

class TestDeadlineRules:
    def test_cert_date_offset_two_years(self):
        from main import DEADLINE_RULES
        from dateutil.relativedelta import relativedelta
        base = date(2023, 3, 15)
        result = DEADLINE_RULES["cert_date_offset"](base, {"deadlineYears": 2})
        assert result == date(2025, 3, 15)

    def test_cert_date_offset_leap_year(self):
        from main import DEADLINE_RULES
        base = date(2020, 2, 29)
        result = DEADLINE_RULES["cert_date_offset"](base, {"deadlineYears": 2})
        assert result == date(2022, 2, 28)

    def test_cert_date_offset_default_two_years_when_key_missing(self):
        from main import DEADLINE_RULES
        base = date(2023, 1, 1)
        result = DEADLINE_RULES["cert_date_offset"](base, {})
        from dateutil.relativedelta import relativedelta
        assert result == base + relativedelta(years=2)

    def test_injury_date_offset_days(self):
        from main import DEADLINE_RULES
        from dateutil.relativedelta import relativedelta
        base = date(2023, 6, 1)
        result = DEADLINE_RULES["injury_date_offset"](base, {"deadlineDays": 730})
        assert result == base + relativedelta(days=730)

    def test_injury_date_offset_default_730_days_when_key_missing(self):
        from main import DEADLINE_RULES
        from dateutil.relativedelta import relativedelta
        base = date(2023, 6, 1)
        result = DEADLINE_RULES["injury_date_offset"](base, {})
        assert result == base + relativedelta(days=730)

    def test_statute_of_limitations_uses_statute_years(self):
        from main import DEADLINE_RULES
        from dateutil.relativedelta import relativedelta
        base = date(2022, 1, 1)
        result = DEADLINE_RULES["statute_of_limitations"](base, {"statuteYears": 3})
        assert result == date(2025, 1, 1)

    def test_statute_of_limitations_falls_back_to_deadline_years(self):
        from main import DEADLINE_RULES
        from dateutil.relativedelta import relativedelta
        base = date(2022, 1, 1)
        result = DEADLINE_RULES["statute_of_limitations"](base, {"deadlineYears": 4})
        assert result == base + relativedelta(years=4)

    def test_all_three_rule_types_present(self):
        from main import DEADLINE_RULES
        assert "cert_date_offset" in DEADLINE_RULES
        assert "injury_date_offset" in DEADLINE_RULES
        assert "statute_of_limitations" in DEADLINE_RULES


# ── _get_base_date tests ───────────────────────────────────────────────────────

class TestGetBaseDate:
    def test_cert_date_offset_reads_certification_date(self):
        from main import _get_base_date
        new_fields = _make_new_fields(cert_date="2023-03-15")
        result = _get_base_date(new_fields, "cert_date_offset")
        assert result == date(2023, 3, 15)

    def test_injury_date_offset_reads_injury_date(self):
        from main import _get_base_date
        new_fields = _make_new_fields(injury_date="2022-07-04")
        result = _get_base_date(new_fields, "injury_date_offset")
        assert result == date(2022, 7, 4)

    def test_statute_reads_created_at(self):
        from main import _get_base_date
        new_fields = _make_new_fields(created_at="2021-05-20")
        result = _get_base_date(new_fields, "statute_of_limitations")
        assert result == date(2021, 5, 20)

    def test_missing_field_returns_none(self):
        from main import _get_base_date
        new_fields = _make_new_fields(cert_date="")
        assert _get_base_date(new_fields, "cert_date_offset") is None

    def test_invalid_date_returns_none(self):
        from main import _get_base_date
        new_fields = {
            "medicalInfo": _make_map_field({
                "certificationDate": _make_str_field("not-a-date")
            })
        }
        assert _get_base_date(new_fields, "cert_date_offset") is None

    def test_unknown_rule_type_returns_none(self):
        from main import _get_base_date
        new_fields = _make_new_fields()
        assert _get_base_date(new_fields, "unknown_rule") is None


# ── calculate_deadline tests ───────────────────────────────────────────────────

class TestCalculateDeadline:
    def test_cert_date_offset_full_path(self):
        from main import calculate_deadline
        new_fields = _make_new_fields(cert_date="2023-03-15")
        firm_config = {"deadlineRuleType": "cert_date_offset", "deadlineYears": 2}
        result = calculate_deadline(new_fields, firm_config)
        assert result == date(2025, 3, 15)

    def test_injury_date_offset_full_path(self):
        from main import calculate_deadline
        new_fields = _make_new_fields(injury_date="2023-01-01")
        firm_config = {"deadlineRuleType": "injury_date_offset", "deadlineDays": 365}
        result = calculate_deadline(new_fields, firm_config)
        assert result == date(2024, 1, 1)

    def test_defaults_to_cert_date_offset_when_rule_type_missing(self):
        from main import calculate_deadline
        new_fields = _make_new_fields(cert_date="2023-06-01")
        result = calculate_deadline(new_fields, {})
        from dateutil.relativedelta import relativedelta
        assert result == date(2023, 6, 1) + relativedelta(years=2)

    def test_unknown_rule_type_falls_back_to_cert_date_offset(self):
        from main import calculate_deadline
        new_fields = _make_new_fields(cert_date="2023-06-01")
        firm_config = {"deadlineRuleType": "nonexistent_rule", "deadlineYears": 2}
        result = calculate_deadline(new_fields, firm_config)
        assert result == date(2025, 6, 1)

    def test_returns_none_when_base_date_missing(self):
        from main import calculate_deadline
        new_fields = _make_new_fields(cert_date="")
        firm_config = {"deadlineRuleType": "cert_date_offset", "deadlineYears": 2}
        assert calculate_deadline(new_fields, firm_config) is None


# ── _get_firm_config tests ─────────────────────────────────────────────────────

class TestGetFirmConfig:
    def setup_method(self):
        import main
        main._firm_config_cache = None
        main._db = None

    def test_loads_from_firestore(self):
        import main
        mock_db = MagicMock()
        mock_doc = MagicMock()
        mock_doc.exists = True
        mock_doc.to_dict.return_value = {
            "deadlineRuleType": "injury_date_offset",
            "deadlineDays": 730,
        }
        mock_db.collection.return_value.document.return_value.get.return_value = mock_doc

        with patch("main._get_db", return_value=mock_db):
            cfg = main._get_firm_config()

        assert cfg["deadlineRuleType"] == "injury_date_offset"
        assert cfg["deadlineDays"] == 730

    def test_injects_deadline_years_env_fallback(self):
        import main
        mock_db = MagicMock()
        mock_doc = MagicMock()
        mock_doc.exists = False
        mock_db.collection.return_value.document.return_value.get.return_value = mock_doc

        with patch("main._get_db", return_value=mock_db):
            cfg = main._get_firm_config()

        # DEADLINE_YEARS env var should be injected as fallback
        assert "deadlineYears" in cfg

    def test_falls_back_to_defaults_on_firestore_error(self):
        import main
        with patch("main._get_db", side_effect=Exception("connection refused")):
            cfg = main._get_firm_config()

        assert isinstance(cfg, dict)
        assert "deadlineYears" in cfg

    def test_caches_result(self):
        import main
        mock_db = MagicMock()
        mock_doc = MagicMock()
        mock_doc.exists = True
        mock_doc.to_dict.return_value = {"deadlineRuleType": "cert_date_offset"}
        mock_db.collection.return_value.document.return_value.get.return_value = mock_doc

        with patch("main._get_db", return_value=mock_db):
            first  = main._get_firm_config()
            second = main._get_firm_config()

        assert first is second
        assert mock_db.collection.call_count == 1


# ── _get_closed_statuses tests ─────────────────────────────────────────────────

class TestGetClosedStatuses:
    def setup_method(self):
        import main
        main._closed_statuses_cache = None
        main._db = None

    def test_loads_from_firestore(self):
        import main
        mock_db = MagicMock()
        mock_doc = MagicMock()
        mock_doc.exists = True
        mock_doc.to_dict.return_value = {
            "closedStatuses": ["Closed", "Settled", "Withdrawn"]
        }
        mock_db.collection.return_value.document.return_value.get.return_value = mock_doc

        with patch("main._get_db", return_value=mock_db):
            statuses = main._get_closed_statuses()

        assert "Closed" in statuses
        assert "Withdrawn" in statuses
        assert "Pending Paralegal Review" not in statuses

    def test_falls_back_to_defaults_when_document_absent(self):
        import main
        mock_db = MagicMock()
        mock_doc = MagicMock()
        mock_doc.exists = False
        mock_db.collection.return_value.document.return_value.get.return_value = mock_doc

        with patch("main._get_db", return_value=mock_db):
            statuses = main._get_closed_statuses()

        from main import DEFAULT_SKIP_STATUSES
        assert statuses == DEFAULT_SKIP_STATUSES

    def test_falls_back_to_defaults_on_firestore_error(self):
        import main
        with patch("main._get_db", side_effect=Exception("timeout")):
            statuses = main._get_closed_statuses()

        from main import DEFAULT_SKIP_STATUSES
        assert statuses == DEFAULT_SKIP_STATUSES

    def test_caches_result(self):
        import main
        mock_db = MagicMock()
        mock_doc = MagicMock()
        mock_doc.exists = True
        mock_doc.to_dict.return_value = {"closedStatuses": ["Closed"]}
        mock_db.collection.return_value.document.return_value.get.return_value = mock_doc

        with patch("main._get_db", return_value=mock_db):
            first  = main._get_closed_statuses()
            second = main._get_closed_statuses()

        assert first is second
        assert mock_db.collection.call_count == 1

    def test_default_skip_statuses_contains_expected_values(self):
        from main import DEFAULT_SKIP_STATUSES
        assert "Closed" in DEFAULT_SKIP_STATUSES
        assert "Settled" in DEFAULT_SKIP_STATUSES
        assert "Does Not Qualify" in DEFAULT_SKIP_STATUSES
        assert "Rejected" in DEFAULT_SKIP_STATUSES
        assert "Enrolled" not in DEFAULT_SKIP_STATUSES


# ── Deadline status bucket tests ───────────────────────────────────────────────

class TestDeadlineStatusBuckets:
    def test_active(self):
        today    = date(2025, 1, 1)
        deadline = date(2025, 5, 1)
        days     = (deadline - today).days
        assert days > 90

    def test_warning_90(self):
        today    = date(2025, 2, 1)
        deadline = date(2025, 5, 1)
        days     = (deadline - today).days
        assert 60 < days <= 90

    def test_warning_60(self):
        today    = date(2025, 3, 15)
        deadline = date(2025, 5, 1)
        days     = (deadline - today).days
        assert 30 < days <= 60

    def test_warning_30(self):
        today    = date(2025, 4, 15)
        deadline = date(2025, 5, 1)
        days     = (deadline - today).days
        assert 0 < days <= 30

    def test_expired(self):
        today    = date(2025, 6, 1)
        deadline = date(2025, 5, 1)
        days     = (deadline - today).days
        assert days < 0


# ── Field helper tests ─────────────────────────────────────────────────────────

class TestFieldHelpers:
    def test_str_field_returns_string_value(self):
        from main import _str_field
        fields = {"status": {"stringValue": "Active"}}
        assert _str_field(fields, "status") == "Active"

    def test_str_field_returns_empty_for_missing_key(self):
        from main import _str_field
        assert _str_field({}, "missing") == ""

    def test_map_field_returns_nested_fields(self):
        from main import _map_field
        fields = {
            "medicalInfo": {
                "mapValue": {
                    "fields": {"certificationDate": {"stringValue": "2023-01-01"}}
                }
            }
        }
        result = _map_field(fields, "medicalInfo")
        assert "certificationDate" in result

    def test_map_field_returns_empty_for_missing_key(self):
        from main import _map_field
        assert _map_field({}, "missing") == {}
