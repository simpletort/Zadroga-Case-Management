"""
Unit tests for services/vcf_workflow.py
"""

from datetime import date
from unittest.mock import MagicMock

import pytest


def _make_case_snap(data: dict, exists: bool = True):
    snap = MagicMock()
    snap.exists = exists
    snap.to_dict.return_value = data
    return snap


def test_initiate_vcf_registration_case_not_found(mock_db):
    from services.vcf_workflow import initiate_vcf_registration

    mock_case_ref = MagicMock()
    mock_case_ref.get.return_value = _make_case_snap({}, exists=False)
    mock_db.collection.return_value.document.return_value = mock_case_ref

    with pytest.raises(ValueError, match="not found"):
        initiate_vcf_registration(db=mock_db, case_id="FAKE-001")


def test_initiate_vcf_skips_already_registered(mock_db):
    from services.vcf_workflow import initiate_vcf_registration

    case_data = {
        "status": "Approved for Filing",
        "enrollment": {
            "vcfRegistrationStatus": "Registered",
            "vcfClaimNumber": "VCF-999",
        },
        "assignment": {},
        "medicalInfo": {},
    }
    mock_case_ref = MagicMock()
    mock_case_ref.get.return_value = _make_case_snap(case_data)
    mock_db.collection.return_value.document.return_value = mock_case_ref

    result = initiate_vcf_registration(db=mock_db, case_id="ZAD-001")
    assert result["initiated"] is False
    assert "already registered" in result["message"].lower()


def test_initiate_vcf_success(mock_db, case_not_registered):
    from services.vcf_workflow import initiate_vcf_registration

    mock_case_ref = MagicMock()
    mock_case_ref.get.return_value = _make_case_snap(case_not_registered)

    mock_task_ref = MagicMock()
    mock_task_ref.id = "task-vcf-001"
    mock_timeline_ref = MagicMock()
    mock_timeline_ref.id = "timeline-vcf-001"

    mock_case_ref.collection.return_value.document.side_effect = [
        mock_task_ref, mock_timeline_ref, mock_timeline_ref
    ]
    mock_db.collection.return_value.document.return_value = mock_case_ref

    result = initiate_vcf_registration(db=mock_db, case_id="ZAD-001")
    assert result["initiated"] is True
    assert result["task_id"] is not None


def test_update_vcf_status_requires_claim_number_for_registered(mock_db):
    from models.vcf_models import VCFRegistrationStatus, UpdateVCFStatusRequest
    from services.vcf_workflow import update_vcf_status

    case_data = {
        "status": "Approved for Filing",
        "enrollment": {"vcfRegistrationStatus": "Registration Pending"},
        "assignment": {},
        "medicalInfo": {},
    }
    mock_case_ref = MagicMock()
    mock_case_ref.get.return_value = _make_case_snap(case_data)
    mock_db.collection.return_value.document.return_value = mock_case_ref

    request = UpdateVCFStatusRequest(
        status=VCFRegistrationStatus.REGISTERED,
        vcf_claim_number=None,   # missing — should raise
        performed_by="test-user",
    )

    with pytest.raises(ValueError, match="vcf_claim_number is required"):
        update_vcf_status(db=mock_db, case_id="ZAD-001", request=request)


def test_valid_transitions_not_registered_to_pending():
    from models.vcf_models import VCFRegistrationStatus
    from services.vcf_workflow import VALID_TRANSITIONS

    allowed = VALID_TRANSITIONS[VCFRegistrationStatus.NOT_REGISTERED]
    assert VCFRegistrationStatus.REGISTRATION_PENDING in allowed


def test_invalid_transition_raises(mock_db):
    from models.vcf_models import VCFRegistrationStatus, UpdateVCFStatusRequest
    from services.vcf_workflow import update_vcf_status

    case_data = {
        "status": "Approved for Filing",
        "enrollment": {"vcfRegistrationStatus": "Not Registered"},
        "assignment": {},
        "medicalInfo": {},
    }
    mock_case_ref = MagicMock()
    mock_case_ref.get.return_value = _make_case_snap(case_data)
    mock_db.collection.return_value.document.return_value = mock_case_ref

    request = UpdateVCFStatusRequest(
        status=VCFRegistrationStatus.REGISTERED,  # skip Registration Pending
        vcf_claim_number="VCF-123",
        performed_by="test-user",
    )

    with pytest.raises(ValueError, match="Invalid VCF status transition"):
        update_vcf_status(db=mock_db, case_id="ZAD-001", request=request)


def test_vcf_deadline_calculated_on_registration(mock_db):
    """When status set to Registered, deadline should be calculated."""
    from models.vcf_models import VCFRegistrationStatus, UpdateVCFStatusRequest
    from services.vcf_workflow import update_vcf_status

    case_data = {
        "status": "Approved for Filing",
        "enrollment": {"vcfRegistrationStatus": "Registration Pending"},
        "assignment": {"assignedParalegal": "paralegal-001"},
        "medicalInfo": {"certificationDate": "2023-06-01"},
    }
    mock_case_ref = MagicMock()
    mock_case_ref.get.return_value = _make_case_snap(case_data)

    mock_task_ref = MagicMock()
    mock_task_ref.id = "task-001"
    mock_timeline_ref = MagicMock()
    mock_timeline_ref.id = "timeline-001"
    mock_case_ref.collection.return_value.document.side_effect = [
        mock_timeline_ref, mock_task_ref, mock_timeline_ref, mock_timeline_ref
    ]
    mock_db.collection.return_value.document.return_value = mock_case_ref

    request = UpdateVCFStatusRequest(
        status=VCFRegistrationStatus.REGISTERED,
        vcf_claim_number="VCF-2024-001",
        performed_by="test-user",
    )

    result = update_vcf_status(db=mock_db, case_id="ZAD-001", request=request)

    # Deadline should be cert date + 2 years
    assert result["vcf_filing_deadline"] == "2025-06-01"
