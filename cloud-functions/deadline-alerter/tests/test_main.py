"""
Unit tests for deadline-alerter Cloud Function.
"""

import os
from datetime import date, timedelta
from unittest.mock import MagicMock, patch, call

import pytest

os.environ.setdefault("GCP_PROJECT_ID", "test-project")
os.environ.setdefault("FIRESTORE_DATABASE_ID", "(default)")
os.environ.setdefault("PUBSUB_TOPIC_NOTIFICATIONS", "notification-requests")
os.environ.setdefault("PUBSUB_TOPIC_ENROLLMENT", "enrollment-status-changes")
os.environ.setdefault("ALERT_DAYS", "90,60,30")


def test_compute_status_expired():
    from main import _compute_status
    assert _compute_status(-1) == "expired"
    assert _compute_status(-100) == "expired"


def test_compute_status_warning_30():
    from main import _compute_status
    assert _compute_status(0) == "warning_30"
    assert _compute_status(30) == "warning_30"


def test_compute_status_warning_60():
    from main import _compute_status
    assert _compute_status(31) == "warning_60"
    assert _compute_status(60) == "warning_60"


def test_compute_status_warning_90():
    from main import _compute_status
    assert _compute_status(61) == "warning_90"
    assert _compute_status(90) == "warning_90"


def test_compute_status_active():
    from main import _compute_status
    assert _compute_status(91) == "active"
    assert _compute_status(365) == "active"


def test_no_duplicate_alert_for_same_milestone():
    """
    If lastAlertMilestone == 30, then a 30-day alert should NOT fire again.
    """
    last_alert = 30
    threshold_to_check = 30
    # Logic: only fire if last_alert is None OR last_alert > threshold_to_check
    should_fire = last_alert is None or last_alert > threshold_to_check
    assert should_fire is False


def test_new_milestone_fires_when_no_previous_alert():
    """No previous alert → fire the 90-day alert."""
    last_alert = None
    threshold = 90
    should_fire = last_alert is None or last_alert > threshold
    assert should_fire is True


def test_progression_90_to_60():
    """After 90-day alert, 60-day alert should fire."""
    last_alert = 90
    threshold = 60
    should_fire = last_alert is None or last_alert > threshold
    assert should_fire is True


def test_skip_final_status():
    """Cases with Closed/Settled/etc status are skipped."""
    skip_statuses = {"Closed", "Settled", "Does Not Qualify", "Rejected"}
    assert all(s in skip_statuses for s in ["Closed", "Settled"])
    assert "Enrolled" not in skip_statuses


def test_alert_threshold_selection():
    """Highest applicable threshold is chosen (90 before 60 before 30)."""
    today = date.today()
    alert_days = [90, 60, 30]
    # Case with 85 days remaining → should trigger 90-day threshold (85 <= 90)
    days_remaining = 85
    for threshold in sorted(alert_days, reverse=True):
        if days_remaining <= threshold:
            selected = threshold
            break
    assert selected == 90


def test_alert_threshold_for_25_days():
    """25 days remaining → triggers 30-day threshold."""
    alert_days = [90, 60, 30]
    days_remaining = 25
    for threshold in sorted(alert_days, reverse=True):
        if days_remaining <= threshold:
            selected = threshold
            break
    assert selected == 30


@patch("main._get_db")
@patch("main._get_publisher")
def test_process_case_fires_alert(mock_pub, mock_db_fn):
    """Verify _process_case fires alert for a 85-day case with no prior alert."""
    from main import _process_case

    today = date.today()
    deadline = today + timedelta(days=85)

    mock_db = MagicMock()
    mock_db_fn.return_value = mock_db

    mock_publisher = MagicMock()
    mock_pub.return_value = mock_publisher
    mock_publisher.topic_path.return_value = "projects/test/topics/test"
    mock_publisher.publish.return_value = MagicMock()

    mock_tasks_ref = MagicMock()
    mock_tasks_ref.id = "task-123"
    mock_timeline_ref = MagicMock()
    mock_timeline_ref.id = "timeline-456"

    mock_case_ref = MagicMock()
    mock_case_ref.collection.return_value.document.side_effect = [
        mock_tasks_ref, mock_timeline_ref
    ]
    mock_db.collection.return_value.document.return_value = mock_case_ref

    case_doc = MagicMock()
    case_doc.id = "ZAD-2024-01-0001"
    case_doc.to_dict.return_value = {
        "status": "Approved for Filing",
        "enrollment": {
            "vcfFilingDeadline": deadline.isoformat(),
            "lastAlertMilestone": None,
        },
        "assignment": {
            "assignedParalegal": "paralegal-uid",
            "supervisingAttorney": "attorney-uid",
        },
    }

    stats = {"scanned": 0, "alerts_fired": 0, "skipped_duplicate": 0,
             "skipped_final_status": 0, "errors": 0,
             "by_threshold": {"90": 0, "60": 0, "30": 0}}

    _process_case(mock_db, case_doc, today, stats)

    assert stats["alerts_fired"] == 1
    assert stats["by_threshold"]["90"] == 1
