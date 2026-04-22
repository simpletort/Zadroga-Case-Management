"""
conftest.py — Shared pytest fixtures for enrollment-workflow tests.
"""

import os
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

# Set env vars before imports
os.environ.setdefault("GCP_PROJECT_ID", "test-project")
os.environ.setdefault("FIRESTORE_DATABASE_ID", "(default)")
os.environ.setdefault("APP_ENV", "development")


@pytest.fixture
def mock_db():
    """Mock Firestore client."""
    db = MagicMock()
    return db


@pytest.fixture
def case_not_enrolled():
    """Case document with WTC status Not Enrolled."""
    return {
        "status": "Approved for Filing",
        "enrollment": {
            "wtcEnrollmentStatus": "Not Enrolled",
            "wtcWorkflowStep": "paralegal_task_created",
        },
        "assignment": {
            "assignedParalegal": "paralegal-uid-001",
            "supervisingAttorney": "attorney-uid-001",
        },
        "medicalInfo": {
            "certificationDate": "2023-03-15",
            "certifiedCondition": "Aerodigestive Disorder",
        },
        "exposureInfo": {
            "location": "World Trade Center",
            "startDate": "2001-09-11",
            "endDate": "2002-05-30",
        },
    }


@pytest.fixture
def case_enrolled():
    """Case document with WTC status Enrolled."""
    return {
        "status": "Approved for Filing",
        "enrollment": {
            "wtcEnrollmentStatus": "Enrolled",
            "wtcWorkflowStep": "workflow_complete",
            "wtcEnrollmentDate": datetime.now(tz=timezone.utc),
            "wtcMemberId": "WTC-12345",
        },
        "assignment": {
            "assignedParalegal": "paralegal-uid-001",
        },
        "medicalInfo": {
            "certificationDate": "2023-03-15",
        },
    }


@pytest.fixture
def case_not_registered():
    """Case document with VCF status Not Registered."""
    return {
        "status": "Approved for Filing",
        "enrollment": {
            "vcfRegistrationStatus": "Not Registered",
            "vcfRegistrationStep": "eligibility_review",
        },
        "assignment": {
            "assignedParalegal": "paralegal-uid-001",
        },
        "medicalInfo": {
            "certificationDate": "2023-06-01",
        },
    }
