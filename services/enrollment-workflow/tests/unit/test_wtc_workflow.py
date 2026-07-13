"""
Unit tests for services/wtc_workflow.py
"""

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest


def _make_case_snap(data: dict, exists: bool = True):
    snap = MagicMock()
    snap.exists = exists
    snap.to_dict.return_value = data
    return snap


def test_trigger_workflow_case_not_found(mock_db):
    from services.wtc_workflow import trigger_wtc_workflow

    mock_case_ref = MagicMock()
    mock_case_ref.get.return_value = _make_case_snap({}, exists=False)
    mock_db.collection.return_value.document.return_value = mock_case_ref

    with pytest.raises(ValueError, match="not found"):
        trigger_wtc_workflow(db=mock_db, case_id="FAKE-001")


def test_trigger_workflow_skips_already_enrolled(mock_db, case_enrolled):
    from services.wtc_workflow import trigger_wtc_workflow

    mock_case_ref = MagicMock()
    mock_case_ref.get.return_value = _make_case_snap(case_enrolled)
    mock_db.collection.return_value.document.return_value = mock_case_ref

    result = trigger_wtc_workflow(db=mock_db, case_id="ZAD-001")
    assert result["triggered"] is False
    assert "already enrolled" in result["message"].lower()


def test_trigger_workflow_skips_deceased(mock_db):
    from services.wtc_workflow import trigger_wtc_workflow

    case_data = {
        "status": "Closed - Deceased",
        "enrollment": {},
        "assignment": {},
    }
    mock_case_ref = MagicMock()
    mock_case_ref.get.return_value = _make_case_snap(case_data)
    mock_db.collection.return_value.document.return_value = mock_case_ref

    # Write skip event also needs a timeline sub-collection reference
    mock_timeline_ref = MagicMock()
    mock_timeline_ref.id = "timeline-001"
    mock_case_ref.collection.return_value.document.return_value = mock_timeline_ref

    result = trigger_wtc_workflow(db=mock_db, case_id="ZAD-001")
    assert result["triggered"] is False
    assert "deceased" in result["message"].lower()


def test_trigger_workflow_succeeds_for_unenrolled(mock_db, case_not_enrolled):
    from services.wtc_workflow import trigger_wtc_workflow

    mock_case_ref = MagicMock()
    mock_case_ref.get.return_value = _make_case_snap(case_not_enrolled)

    mock_task_ref = MagicMock()
    mock_task_ref.id = "task-123"
    mock_timeline_ref = MagicMock()
    mock_timeline_ref.id = "timeline-456"

    # tasks and timeline sub-collection
    mock_case_ref.collection.return_value.document.side_effect = [
        mock_task_ref, mock_timeline_ref, mock_timeline_ref
    ]
    mock_db.collection.return_value.document.return_value = mock_case_ref

    result = trigger_wtc_workflow(db=mock_db, case_id="ZAD-001")
    assert result["triggered"] is True
    assert result["task_id"] is not None


def test_valid_transitions_not_enrolled_to_application_pending():
    from models.wtc_models import WTCEnrollmentStatus
    from services.wtc_workflow import VALID_TRANSITIONS

    allowed = VALID_TRANSITIONS[WTCEnrollmentStatus.NOT_ENROLLED]
    assert WTCEnrollmentStatus.APPLICATION_PENDING in allowed


def test_valid_transitions_application_pending_to_enrolled():
    from models.wtc_models import WTCEnrollmentStatus
    from services.wtc_workflow import VALID_TRANSITIONS

    allowed = VALID_TRANSITIONS[WTCEnrollmentStatus.APPLICATION_PENDING]
    assert WTCEnrollmentStatus.ENROLLED in allowed


def test_invalid_transition_raises(mock_db):
    from models.wtc_models import WTCEnrollmentStatus, UpdateWTCStatusRequest
    from services.wtc_workflow import update_wtc_status

    case_data = {
        "status": "Approved for Filing",
        "enrollment": {"wtcEnrollmentStatus": "Not Enrolled"},
        "assignment": {},
    }
    mock_case_ref = MagicMock()
    mock_case_ref.get.return_value = _make_case_snap(case_data)
    mock_db.collection.return_value.document.return_value = mock_case_ref

    request = UpdateWTCStatusRequest(
        status=WTCEnrollmentStatus.ENROLLED,  # invalid: skip Application Pending
        performed_by="test-user",
    )

    with pytest.raises(ValueError, match="Invalid WTC status transition"):
        update_wtc_status(db=mock_db, case_id="ZAD-001", request=request)
