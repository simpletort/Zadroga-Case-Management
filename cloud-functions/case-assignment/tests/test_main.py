"""
Unit tests for main.py (Cloud Function entry point).

The function now reads case state directly from Firestore rather than parsing
the Eventarc binary protobuf payload.  Tests mock _get_db() and the Firestore
document snapshot so no live GCP dependency is required.
"""

import pytest
from unittest.mock import MagicMock, patch
from cloudevents.http import CloudEvent


# ── Helpers ────────────────────────────────────────────────────────────────

def _make_event(case_id="ZAD-2024-01-0001", collection="cases"):
    """Create a CloudEvent with the Eventarc Firestore subject attribute."""
    return CloudEvent(
        attributes={
            "type": "google.cloud.firestore.document.v1.written",
            "source": "projects/test-project/databases/(default)",
            "subject": "documents/{}/{}".format(collection, case_id),
        },
        data=b"",  # binary protobuf payload — not parsed; function reads Firestore instead
    )


def _make_snap(status="Pending Paralegal Review", assigned="", exists=True):
    """Return a mock Firestore DocumentSnapshot."""
    snap = MagicMock()
    snap.exists = exists
    if exists:
        snap.to_dict.return_value = {
            "status": status,
            "assignment": {"assignedParalegal": assigned},
        }
    return snap


# ── Tests ──────────────────────────────────────────────────────────────────

class TestCaseAssignmentFunction:

    def setup_method(self):
        patcher = patch("main._get_db")
        self.mock_get_db = patcher.start()
        self.mock_db = MagicMock()
        self.mock_get_db.return_value = self.mock_db
        self.addCleanup = patcher.stop

    def teardown_method(self):
        self.addCleanup()

    def _setup_case(self, status="Pending Paralegal Review", assigned="", exists=True):
        """Wire the mock Firestore client to return the given case state."""
        snap = _make_snap(status=status, assigned=assigned, exists=exists)
        self.mock_db.collection.return_value.document.return_value.get.return_value = snap

    # ── subject / routing guards ───────────────────────────────────────────

    def test_skips_non_cases_collection(self):
        """Events whose subject is not a cases document should be ignored."""
        event = _make_event(collection="staff")
        with patch("main.assign_case") as mock_assign:
            from main import case_assignment
            case_assignment(event)
        mock_assign.assert_not_called()

    def test_skips_on_document_not_found(self):
        """If the case document no longer exists in Firestore (e.g. delete), skip."""
        self._setup_case(exists=False)
        event = _make_event()
        with patch("main.assign_case") as mock_assign:
            from main import case_assignment
            case_assignment(event)
        mock_assign.assert_not_called()

    # ── status / assignment guards ─────────────────────────────────────────

    def test_skips_non_target_status(self):
        self._setup_case(status="Pending Attorney Review")
        event = _make_event()
        with patch("main.assign_case") as mock_assign:
            from main import case_assignment
            case_assignment(event)
        mock_assign.assert_not_called()

    def test_skips_already_assigned(self):
        self._setup_case(status="Pending Paralegal Review", assigned="existing-uid")
        event = _make_event()
        with patch("main.assign_case") as mock_assign:
            from main import case_assignment
            case_assignment(event)
        mock_assign.assert_not_called()

    # ── happy path ─────────────────────────────────────────────────────────

    def test_calls_assign_case_on_valid_transition(self):
        self._setup_case(status="Pending Paralegal Review")
        event = _make_event()
        with patch("main.assign_case", return_value="p1") as mock_assign, \
             patch("main.publish_assignment_notification") as mock_notify:
            from main import case_assignment
            case_assignment(event)

        mock_assign.assert_called_once()
        _, call_case_id = mock_assign.call_args[0]
        assert call_case_id == "ZAD-2024-01-0001"
        mock_notify.assert_called_once()

    def test_no_notification_when_no_paralegal_available(self):
        self._setup_case(status="Pending Paralegal Review")
        event = _make_event()
        with patch("main.assign_case", return_value=None), \
             patch("main.publish_assignment_notification") as mock_notify, \
             patch("main._write_no_paralegal_timeline") as mock_timeline:
            from main import case_assignment
            case_assignment(event)

        mock_notify.assert_not_called()
        mock_timeline.assert_called_once_with(self.mock_db, "ZAD-2024-01-0001")
