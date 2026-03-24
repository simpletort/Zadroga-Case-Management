"""
Unit tests for main.py (Cloud Function entry point).
"""

import pytest
from unittest.mock import MagicMock, patch
from cloudevents.http import CloudEvent


def _make_event(new_status="Pending Paralegal Review", old_status="Pending Client Information",
                 assigned_paralegal="", doc_name=None):
    if doc_name is None:
        doc_name = "projects/test-project/databases/(default)/documents/cases/ZAD-2024-01-0001"

    value_fields = {
        "status": {"stringValue": new_status},
        "assignment": {
            "mapValue": {
                "fields": {
                    "assignedParalegal": {"stringValue": assigned_paralegal},
                }
            }
        },
    }

    old_value_fields = {
        "status": {"stringValue": old_status},
    } if old_status else {}

    data = {
        "value": {"name": doc_name, "fields": value_fields},
        "oldValue": {"name": doc_name, "fields": old_value_fields},
    }

    return CloudEvent(
        attributes={"type": "google.cloud.firestore.document.v1.written", "source": "test"},
        data=data,
    )


class TestCaseAssignmentFunction:

    def setup_method(self):
        # Patch the Firestore client so module-level init doesn't fail
        patcher = patch("main._get_db")
        self.mock_get_db = patcher.start()
        self.mock_db = MagicMock()
        self.mock_get_db.return_value = self.mock_db
        self.addCleanup = patcher.stop

    def teardown_method(self):
        self.addCleanup()

    def test_skips_non_target_status(self):
        event = _make_event(new_status="Pending Attorney Review")
        with patch("main.assign_case") as mock_assign:
            from main import case_assignment
            case_assignment(event)
        mock_assign.assert_not_called()

    def test_skips_unchanged_status(self):
        """If old and new status are both 'Pending Paralegal Review', skip."""
        event = _make_event(
            new_status="Pending Paralegal Review",
            old_status="Pending Paralegal Review",
        )
        with patch("main.assign_case") as mock_assign:
            from main import case_assignment
            case_assignment(event)
        mock_assign.assert_not_called()

    def test_skips_already_assigned(self):
        event = _make_event(
            new_status="Pending Paralegal Review",
            assigned_paralegal="existing-uid",
        )
        with patch("main.assign_case") as mock_assign:
            from main import case_assignment
            case_assignment(event)
        mock_assign.assert_not_called()

    def test_calls_assign_case_on_valid_transition(self):
        event = _make_event()
        with patch("main.assign_case", return_value="p1") as mock_assign, \
             patch("main.publish_assignment_notification") as mock_notify:
            from main import case_assignment
            case_assignment(event)

        mock_assign.assert_called_once()
        call_args = mock_assign.call_args[0]
        assert call_args[1] == "ZAD-2024-01-0001"
        mock_notify.assert_called_once()

    def test_no_notification_when_no_paralegal_available(self):
        event = _make_event()
        with patch("main.assign_case", return_value=None), \
             patch("main.publish_assignment_notification") as mock_notify, \
             patch("main._write_no_paralegal_timeline") as mock_timeline:
            from main import case_assignment
            case_assignment(event)

        mock_notify.assert_not_called()
        mock_timeline.assert_called_once_with(self.mock_db, "ZAD-2024-01-0001")

    def test_skips_on_missing_value(self):
        """Delete events have no 'value' — function should return early."""
        event = CloudEvent(
            attributes={"type": "google.cloud.firestore.document.v1.written", "source": "test"},
            data={"oldValue": {"name": "projects/p/databases/d/documents/cases/ZAD-X", "fields": {}}},
        )
        with patch("main.assign_case") as mock_assign:
            from main import case_assignment
            case_assignment(event)
        mock_assign.assert_not_called()
