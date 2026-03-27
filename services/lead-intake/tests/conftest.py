"""
tests/conftest.py — Shared pytest fixtures.
"""
from __future__ import annotations
import os
import pytest

# Set test env vars before any imports
os.environ.setdefault("GCP_PROJECT_ID", "test-project")
os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("VCF_WINDOW_START", "2001-09-11")
os.environ.setdefault("VCF_WINDOW_END", "2011-05-30")
os.environ.setdefault("JWT_AUDIENCE", "test-audience")
os.environ.setdefault("JWT_ISSUER", "https://test-issuer.example.com")
os.environ.setdefault("JWKS_URI", "https://test.example.com/.well-known/jwks.json")
os.environ.setdefault("CLOUD_TASKS_HANDLER_URL", "https://test.example.com")
os.environ.setdefault("RATE_LIMIT_REQUESTS", "100")
os.environ.setdefault("FOLLOWUP_DELAY_HOURS", "48")


@pytest.fixture
def sample_lead_data():
    return {
        "firstName": "John",
        "lastName": "Doe",
        "email": "john.doe@example.com",
        "phone": "+12125551234",
        "exposureLocation": "World Trade Center",
        "exposureDateStart": "2001-09-11",
        "exposureDateEnd": "2002-06-30",
        "wtcHealthProgramStatus": "enrolled",
        "priorAttorney": False,
        "conditions": ["respiratory", "asthma"],
        "marketingSource": "google_ads",
    }


@pytest.fixture
def ineligible_lead_data():
    return {
        "firstName": "Jane",
        "lastName": "Smith",
        "email": "jane.smith@example.com",
        "phone": "+12125559999",
        "exposureLocation": "Los Angeles",
        "exposureDateStart": "2015-01-01",
        "exposureDateEnd": "2016-01-01",
        "wtcHealthProgramStatus": "not_applied",
        "priorAttorney": True,
        "conditions": [],
        "marketingSource": "facebook",
    }


@pytest.fixture
def needs_review_lead_data():
    return {
        "firstName": "Bob",
        "lastName": "Review",
        "email": "bob.review@example.com",
        "phone": "+12125550001",
        "exposureLocation": "World Trade Center",
        "exposureDateStart": "2001-09-11",
        "exposureDateEnd": "2002-01-01",
        "wtcHealthProgramStatus": "not_applied",
        "priorAttorney": True,
        "conditions": ["cancer"],
        "marketingSource": "organic",
    }
