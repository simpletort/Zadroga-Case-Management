"""
conftest.py — Shared pytest fixtures for the settlement-financial service.
"""
from __future__ import annotations

import os
import sys
from unittest.mock import patch, AsyncMock

import pytest

# Make the service root importable
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

os.environ.setdefault("APP_ENV", "development")
os.environ.setdefault("GCP_PROJECT_ID", "test-project")
os.environ.setdefault("FIRESTORE_DATABASE_ID", "(default)")


# ── Auth bypass for unit tests ────────────────────────────────────────────────

async def _passthrough_dispatch(self, request, call_next):
    """Replace AuthMiddleware.dispatch so unit tests don't need real credentials."""
    request.state.user = {"uid": "test-user", "role": "admin", "email": "test@example.com"}
    return await call_next(request)


@pytest.fixture(autouse=True, scope="session")
def bypass_auth():
    """Patch AuthMiddleware to always authenticate as an admin test user."""
    with patch("shared.middlewares.auth.AuthMiddleware.dispatch", _passthrough_dispatch):
        yield
