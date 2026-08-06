"""
conftest.py — Shared pytest fixtures for enrollment-workflow tests.
"""

import os
import sys
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

# Set env vars before imports
os.environ.setdefault("GCP_PROJECT_ID", "test-project")
os.environ.setdefault("FIRESTORE_DATABASE_ID", "(default)")
os.environ.setdefault("APP_ENV", "development")

# ---------------------------------------------------------------------------
# Stub shared middleware package — not installed in the test environment.
# Uses a no-op ASGI pass-through so FastAPI can still wrap and call it.
# ---------------------------------------------------------------------------

class _NoopMiddleware:
    def __init__(self, app, **kwargs):
        self.app = app

    async def __call__(self, scope, receive, send):
        await self.app(scope, receive, send)


def _get_cors_origins_stub(environment: str, gcp_project_id: str) -> list:
    return ["http://localhost:3000"]


_shared_auth_mod = MagicMock()
_shared_auth_mod.AuthMiddleware = _NoopMiddleware

_shared_cors_mod = MagicMock()
_shared_cors_mod.get_cors_origins = _get_cors_origins_stub

_shared_error_mod = MagicMock()
_shared_error_mod.ErrorHandlerMiddleware = _NoopMiddleware

_shared_logging_mod = MagicMock()
_shared_logging_mod.LoggingMiddleware = _NoopMiddleware

_shared_middlewares_mod = MagicMock()
_shared_middlewares_mod.AuthMiddleware = _NoopMiddleware
_shared_middlewares_mod.ErrorHandlerMiddleware = _NoopMiddleware
_shared_middlewares_mod.LoggingMiddleware = _NoopMiddleware
_shared_middlewares_mod.get_cors_origins = _get_cors_origins_stub
_shared_middlewares_mod.auth = _shared_auth_mod
_shared_middlewares_mod.cors = _shared_cors_mod
_shared_middlewares_mod.error_handler = _shared_error_mod
_shared_middlewares_mod.logging = _shared_logging_mod

_shared_mod = MagicMock()
_shared_mod.middlewares = _shared_middlewares_mod

sys.modules.setdefault("shared", _shared_mod)
sys.modules.setdefault("shared.middlewares", _shared_middlewares_mod)
sys.modules.setdefault("shared.middlewares.auth", _shared_auth_mod)
sys.modules.setdefault("shared.middlewares.cors", _shared_cors_mod)
sys.modules.setdefault("shared.middlewares.error_handler", _shared_error_mod)
sys.modules.setdefault("shared.middlewares.logging", _shared_logging_mod)


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
