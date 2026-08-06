"""
conftest.py — Shared pytest fixtures for the settlement-financial service.
"""
from __future__ import annotations

import os
import sys
from unittest.mock import patch, AsyncMock, MagicMock

import pytest

# Make the service root importable
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

os.environ.setdefault("APP_ENV", "development")
os.environ.setdefault("GCP_PROJECT_ID", "test-project")
os.environ.setdefault("FIRESTORE_DATABASE_ID", "(default)")

# get_cors_origins() now fetches from GCP Secret Manager at import time (see
# shared/shared/middlewares/cors.py). Stub it so tests don't make a real
# network call / hang without live GCP credentials.
_cors_stub_mod = MagicMock()
_cors_stub_mod.get_cors_origins = lambda environment, gcp_project_id: ["http://localhost:3000"]
sys.modules.setdefault("shared.middlewares.cors", _cors_stub_mod)


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
