"""
tests/unit/test_lead_models.py — Unit tests for Pydantic models.
"""
from __future__ import annotations
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../api'))

import pytest
from datetime import date
from pydantic import ValidationError
from models.lead import LeadRequest, ExposureDates, CaseDocument, CaseStatus, VCFEligibility


@pytest.fixture
def valid_lead_payload():
    return {
        "firstName": "John",
        "lastName": "Doe",
        "email": "john.doe@example.com",
        "phone": "+12125551234",
        "exposureLocation": "World Trade Center",
        "exposureDates": {"start": "2001-09-11", "end": "2002-06-30"},
        "wtcHealthProgramStatus": "enrolled",
        "priorAttorney": False,
        "conditions": ["respiratory", "asthma"],
        "marketingSource": "google_ads",
    }


class TestLeadRequest:
    def test_valid_payload_accepted(self, valid_lead_payload):
        lead = LeadRequest(**valid_lead_payload)
        assert lead.firstName == "John"
        assert lead.email == "john.doe@example.com"

    def test_phone_normalized_to_e164(self):
        lead = LeadRequest(
            firstName="John", lastName="Doe", email="j@j.com",
            phone="212-555-1234",
            exposureLocation="WTC",
            exposureDates={"start": "2001-09-11", "end": "2002-01-01"},
            wtcHealthProgramStatus="enrolled", priorAttorney=False,
            marketingSource="test",
        )
        assert lead.phone == "+12125551234"

    def test_email_lowercased(self, valid_lead_payload):
        valid_lead_payload["email"] = "JOHN.DOE@EXAMPLE.COM"
        lead = LeadRequest(**valid_lead_payload)
        assert lead.email == "john.doe@example.com"

    def test_whitespace_stripped(self, valid_lead_payload):
        valid_lead_payload["firstName"] = "  John  "
        lead = LeadRequest(**valid_lead_payload)
        assert lead.firstName == "John"

    def test_invalid_phone_raises(self, valid_lead_payload):
        valid_lead_payload["phone"] = "not-a-phone"
        with pytest.raises(ValidationError):
            LeadRequest(**valid_lead_payload)

    def test_invalid_email_raises(self, valid_lead_payload):
        valid_lead_payload["email"] = "not-an-email"
        with pytest.raises(ValidationError):
            LeadRequest(**valid_lead_payload)

    def test_exposure_end_before_start_raises(self, valid_lead_payload):
        valid_lead_payload["exposureDates"] = {"start": "2002-01-01", "end": "2001-01-01"}
        with pytest.raises(ValidationError):
            LeadRequest(**valid_lead_payload)

    def test_empty_conditions_allowed(self, valid_lead_payload):
        valid_lead_payload["conditions"] = []
        lead = LeadRequest(**valid_lead_payload)
        assert lead.conditions == []

    def test_conditions_normalized_lowercase(self, valid_lead_payload):
        valid_lead_payload["conditions"] = ["RESPIRATORY", "  Asthma  "]
        lead = LeadRequest(**valid_lead_payload)
        assert "respiratory" in lead.conditions
        assert "asthma" in lead.conditions

    def test_invalid_state_code_raises(self, valid_lead_payload):
        valid_lead_payload["address"] = {"state": "ZZZ"}  # Invalid state
        with pytest.raises(ValidationError):
            LeadRequest(**valid_lead_payload)

    def test_valid_address_accepted(self, valid_lead_payload):
        valid_lead_payload["address"] = {"city": "New York", "state": "NY", "zip": "10001"}
        lead = LeadRequest(**valid_lead_payload)
        assert lead.address.state == "NY"


class TestCaseDocument:
    def test_default_status_is_new_lead(self):
        from datetime import datetime, timezone
        case = CaseDocument(
            caseId="ZAD-2025-03-0001",
            firstName="John", lastName="Doe",
            email="j@j.com", phone="+12125551234",
            exposureLocation="WTC",
            exposureDateStart=date(2001, 9, 11),
            exposureDateEnd=date(2002, 1, 1),
            wtcHealthProgramStatus="enrolled",
            priorAttorney=False,
            marketingSource="test",
            partnerId="partner_abc",
            createdAt=datetime.now(timezone.utc),
            updatedAt=datetime.now(timezone.utc),
            requestId="req-123",
        )
        assert case.status == CaseStatus.NEW_LEAD
        assert case.vcfEligibility == VCFEligibility.PENDING
