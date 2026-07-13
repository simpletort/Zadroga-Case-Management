"""
Unit tests for services/deadline_service.py
"""

from datetime import date
from unittest.mock import MagicMock, patch

import pytest


def test_calculate_vcf_deadline_from_string():
    from services.deadline_service import calculate_vcf_deadline
    result = calculate_vcf_deadline("2023-03-15")
    assert result == date(2025, 3, 15)


def test_calculate_vcf_deadline_from_date():
    from services.deadline_service import calculate_vcf_deadline
    result = calculate_vcf_deadline(date(2022, 6, 1))
    assert result == date(2024, 6, 1)


def test_calculate_vcf_deadline_leap_year():
    """Feb 29 cert date in leap year → Feb 28 in non-leap year."""
    from services.deadline_service import calculate_vcf_deadline
    result = calculate_vcf_deadline("2020-02-29")
    assert result == date(2022, 2, 28)


def test_deadline_status_active():
    from services.deadline_service import get_deadline_status
    from models.vcf_models import DeadlineStatus
    today = date(2025, 1, 1)
    deadline = date(2025, 5, 1)
    assert get_deadline_status(deadline, today) == DeadlineStatus.ACTIVE


def test_deadline_status_warning_90():
    from services.deadline_service import get_deadline_status
    from models.vcf_models import DeadlineStatus
    today = date(2025, 1, 1)
    deadline = date(2025, 3, 15)   # 73 days from Jan 1
    result = get_deadline_status(deadline, today)
    assert result == DeadlineStatus.WARNING_90


def test_deadline_status_warning_60():
    from services.deadline_service import get_deadline_status
    from models.vcf_models import DeadlineStatus
    today = date(2025, 1, 1)
    deadline = date(2025, 2, 15)   # 45 days
    assert get_deadline_status(deadline, today) == DeadlineStatus.WARNING_60


def test_deadline_status_warning_30():
    from services.deadline_service import get_deadline_status
    from models.vcf_models import DeadlineStatus
    today = date(2025, 1, 1)
    deadline = date(2025, 1, 20)   # 19 days
    assert get_deadline_status(deadline, today) == DeadlineStatus.WARNING_30


def test_deadline_status_expired():
    from services.deadline_service import get_deadline_status
    from models.vcf_models import DeadlineStatus
    today = date(2025, 6, 1)
    deadline = date(2025, 1, 1)   # past
    assert get_deadline_status(deadline, today) == DeadlineStatus.EXPIRED


def test_deadline_status_not_set():
    from services.deadline_service import get_deadline_status
    from models.vcf_models import DeadlineStatus
    assert get_deadline_status(None) == DeadlineStatus.NOT_SET


def test_days_until_deadline_positive():
    from services.deadline_service import days_until_deadline
    today = date(2025, 1, 1)
    deadline = date(2025, 4, 1)
    result = days_until_deadline(deadline, today)
    assert result == 90


def test_days_until_deadline_negative():
    from services.deadline_service import days_until_deadline
    today = date(2025, 6, 1)
    deadline = date(2025, 5, 1)
    result = days_until_deadline(deadline, today)
    assert result == -31


def test_days_until_deadline_none():
    from services.deadline_service import days_until_deadline
    assert days_until_deadline(None) is None


def test_update_case_deadline_no_cert_date(mock_db):
    from services.deadline_service import update_case_deadline
    result = update_case_deadline(db=mock_db, case_id="ZAD-001", certification_date_str=None)
    assert result["deadline_set"] is False
    assert result["reason"] == "no_certification_date"


def test_update_case_deadline_invalid_date(mock_db):
    from services.deadline_service import update_case_deadline
    result = update_case_deadline(db=mock_db, case_id="ZAD-001", certification_date_str="not-a-date")
    assert result["deadline_set"] is False
    assert result["reason"] == "invalid_certification_date"


def test_update_case_deadline_valid(mock_db):
    from services.deadline_service import update_case_deadline
    mock_case_ref = MagicMock()
    mock_db.collection.return_value.document.return_value = mock_case_ref
    mock_timeline_ref = MagicMock()
    mock_timeline_ref.id = "timeline-001"
    mock_case_ref.collection.return_value.document.return_value = mock_timeline_ref

    result = update_case_deadline(
        db=mock_db,
        case_id="ZAD-001",
        certification_date_str="2023-03-15",
        write_timeline=False,
    )
    assert result["deadline_set"] is True
    assert result["vcf_filing_deadline"] == "2025-03-15"
    mock_case_ref.update.assert_called_once()
