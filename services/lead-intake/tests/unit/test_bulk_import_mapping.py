"""
tests/unit/test_bulk_import_mapping.py — Tests for BulkImportRequest/ColumnMapping
validation and the row-mapping transform in services/bulk_import_service.py.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../api"))
os.environ.setdefault("FIREBASE_PROJECT_ID", "test-project")

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from models.bulk_import import BulkImportRequest, ColumnMapping
from services.bulk_import_service import (
    REQUIRED_LEAD_FIELDS,
    _apply_mapping,
    _serialize_for_firestore,
    _set_nested,
    _validate_headers_match,
    _validate_mapping_completeness,
)


def _full_mapping() -> list[ColumnMapping]:
    """A mapping that covers every required LeadRequest field."""
    pairs = {
        "firstName": "First Name",
        "lastName": "Last Name",
        "email": "Email",
        "phone": "Phone",
        "exposureLocation": "Exposure Location",
        "exposureDates.start": "Exposure Start",
        "exposureDates.end": "Exposure End",
        "wtcHealthProgramStatus": "WTC Status",
        "priorAttorney": "Prior Attorney",
    }
    return [ColumnMapping(excelColumn=v, leadField=k) for k, v in pairs.items()]


class TestColumnMappingModel:
    def test_valid_mapping(self):
        m = ColumnMapping(excelColumn="First Name", leadField="firstName")
        assert m.leadField == "firstName"

    def test_rejects_empty_excel_column(self):
        with pytest.raises(ValidationError):
            ColumnMapping(excelColumn="", leadField="firstName")

    def test_rejects_empty_lead_field(self):
        with pytest.raises(ValidationError):
            ColumnMapping(excelColumn="First Name", leadField="")


class TestBulkImportRequestModel:
    def test_requires_at_least_one_mapping(self):
        with pytest.raises(ValidationError):
            BulkImportRequest(columnMappings=[], marketingSource="google_ads")

    def test_requires_marketing_source(self):
        with pytest.raises(ValidationError):
            BulkImportRequest(columnMappings=_full_mapping())

    def test_defaults_header_row_index_to_zero(self):
        req = BulkImportRequest(columnMappings=_full_mapping(), marketingSource="google_ads")
        assert req.headerRowIndex == 0
        assert req.sheetName is None
        assert req.defaultReferralCode is None


class TestValidateMappingCompleteness:
    def test_full_mapping_passes(self):
        _validate_mapping_completeness(_full_mapping())  # should not raise

    def test_missing_required_field_raises_400(self):
        incomplete = [m for m in _full_mapping() if m.leadField != "email"]
        with pytest.raises(HTTPException) as exc_info:
            _validate_mapping_completeness(incomplete)
        assert exc_info.value.status_code == 400
        missing_fields = {d["field"] for d in exc_info.value.detail["details"]}
        assert "email" in missing_fields

    def test_all_required_fields_are_checked(self):
        with pytest.raises(HTTPException) as exc_info:
            _validate_mapping_completeness([])
        missing_fields = {d["field"] for d in exc_info.value.detail["details"]}
        assert missing_fields == set(REQUIRED_LEAD_FIELDS)

    def test_marketing_source_is_not_a_required_column_mapping(self):
        """marketingSource comes from BulkImportRequest itself, not a mapped column."""
        assert "marketingSource" not in REQUIRED_LEAD_FIELDS


class TestValidateHeadersMatch:
    def test_matching_headers_pass(self):
        real_headers = ["First Name", "Last Name", "Email"]
        mappings = [
            ColumnMapping(excelColumn="First Name", leadField="firstName"),
            ColumnMapping(excelColumn="Email", leadField="email"),
        ]
        _validate_headers_match(real_headers, mappings)  # should not raise

    def test_unmatched_column_raises_400(self):
        real_headers = ["First Name", "Last Name"]
        mappings = [ColumnMapping(excelColumn="E-mail Address", leadField="email")]
        with pytest.raises(HTTPException) as exc_info:
            _validate_headers_match(real_headers, mappings)
        assert exc_info.value.status_code == 400
        assert exc_info.value.detail["details"][0]["field"] == "E-mail Address"


class TestSetNested:
    def test_sets_top_level_field(self):
        target = {}
        _set_nested(target, ["firstName"], "John")
        assert target == {"firstName": "John"}

    def test_sets_nested_field(self):
        target = {}
        _set_nested(target, ["exposureDates", "start"], "2001-09-11")
        assert target == {"exposureDates": {"start": "2001-09-11"}}

    def test_merges_into_existing_nested_dict(self):
        target = {"exposureDates": {"start": "2001-09-11"}}
        _set_nested(target, ["exposureDates", "end"], "2001-12-31")
        assert target == {"exposureDates": {"start": "2001-09-11", "end": "2001-12-31"}}


class TestApplyMapping:
    def test_builds_nested_dict_from_flat_row(self):
        raw_row = {
            "First Name": "John", "Last Name": "Doe",
            "Exposure Start": "2001-09-11", "Exposure End": "2001-12-31",
        }
        mappings = [
            ColumnMapping(excelColumn="First Name", leadField="firstName"),
            ColumnMapping(excelColumn="Last Name", leadField="lastName"),
            ColumnMapping(excelColumn="Exposure Start", leadField="exposureDates.start"),
            ColumnMapping(excelColumn="Exposure End", leadField="exposureDates.end"),
        ]
        result = _apply_mapping(raw_row, mappings, "google_ads", None)
        assert result == {
            "marketingSource": "google_ads",
            "firstName": "John",
            "lastName": "Doe",
            "exposureDates": {"start": "2001-09-11", "end": "2001-12-31"},
        }

    def test_skips_blank_and_none_values(self):
        raw_row = {"First Name": "John", "Last Name": "  ", "Email": None}
        mappings = [
            ColumnMapping(excelColumn="First Name", leadField="firstName"),
            ColumnMapping(excelColumn="Last Name", leadField="lastName"),
            ColumnMapping(excelColumn="Email", leadField="email"),
        ]
        result = _apply_mapping(raw_row, mappings, "google_ads", None)
        assert "lastName" not in result
        assert "email" not in result
        assert result["firstName"] == "John"

    def test_applies_default_referral_code_when_not_mapped(self):
        result = _apply_mapping({}, [], "google_ads", "PARTNER-001")
        assert result["referralCode"] == "PARTNER-001"

    def test_mapped_referral_code_column_overrides_default(self):
        raw_row = {"Referral": "PARTNER-ROW"}
        mappings = [ColumnMapping(excelColumn="Referral", leadField="referralCode")]
        result = _apply_mapping(raw_row, mappings, "google_ads", "PARTNER-DEFAULT")
        # Column mapping is applied after the default, so it wins.
        assert result["referralCode"] == "PARTNER-ROW"


class TestSerializeForFirestore:
    def test_converts_date_to_iso_string(self):
        import datetime as dt
        result = _serialize_for_firestore({"dateOfBirth": dt.date(2001, 9, 11)})
        assert result == {"dateOfBirth": "2001-09-11"}

    def test_converts_datetime_to_iso_string(self):
        import datetime as dt
        result = _serialize_for_firestore({"createdAt": dt.datetime(2026, 1, 1, 12, 0, 0)})
        assert result["createdAt"] == "2026-01-01T12:00:00"

    def test_recurses_into_nested_dicts(self):
        import datetime as dt
        result = _serialize_for_firestore({
            "exposureDates": {"start": dt.date(2001, 9, 11), "end": dt.date(2001, 12, 31)},
        })
        assert result == {"exposureDates": {"start": "2001-09-11", "end": "2001-12-31"}}

    def test_leaves_primitives_unchanged(self):
        result = _serialize_for_firestore({"firstName": "John", "priorAttorney": False, "score": 42})
        assert result == {"firstName": "John", "priorAttorney": False, "score": 42}
