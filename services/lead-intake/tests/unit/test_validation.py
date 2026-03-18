"""
tests/unit/test_validation.py — Unit tests for domain validation.
"""
from __future__ import annotations
import sys
import os
from datetime import date

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../api'))

import pytest
from services.validation import validate_exposure_dates, validate_exposure_location, ValidationResult
from models.lead import ExposureDates


def make_dates(start: str, end: str) -> ExposureDates:
    return ExposureDates(start=date.fromisoformat(start), end=date.fromisoformat(end))


class TestValidateExposureDates:
    def test_overlapping_valid(self):
        result = ValidationResult()
        validate_exposure_dates(make_dates("2001-09-11", "2002-06-30"), result)
        assert result.is_valid

    def test_outside_window_invalid(self):
        result = ValidationResult()
        validate_exposure_dates(make_dates("2015-01-01", "2016-01-01"), result)
        assert not result.is_valid
        assert any(e.code == "OUTSIDE_VCF_WINDOW" for e in result.errors)

    def test_future_end_date_invalid(self):
        result = ValidationResult()
        future = date.today().replace(year=date.today().year + 1)
        validate_exposure_dates(ExposureDates(start=date(2001, 9, 11), end=future), result)
        assert any(e.code == "FUTURE_DATE" for e in result.errors)

    def test_pre_2001_start_invalid(self):
        result = ValidationResult()
        validate_exposure_dates(make_dates("2000-12-31", "2002-01-01"), result)
        assert any(e.code == "IMPLAUSIBLE_DATE" for e in result.errors)

    def test_boundary_start_date(self):
        """Exactly on VCF window start is valid."""
        result = ValidationResult()
        validate_exposure_dates(make_dates("2001-09-11", "2001-09-11"), result)
        assert result.is_valid

    def test_boundary_end_date(self):
        """Exactly on VCF window end is valid."""
        result = ValidationResult()
        validate_exposure_dates(make_dates("2011-05-30", "2011-05-30"), result)
        assert result.is_valid


class TestValidateExposureLocation:
    def test_known_location_no_error(self):
        result = ValidationResult()
        validate_exposure_location("World Trade Center", result)
        assert result.is_valid

    def test_unknown_location_no_hard_error(self):
        """Unknown locations don't hard-fail — they're logged only."""
        result = ValidationResult()
        validate_exposure_location("Somewhere Unknown", result)
        assert result.is_valid  # Soft warning only, not a blocking error
