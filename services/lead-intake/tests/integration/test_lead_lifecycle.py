"""
tests/integration/test_lead_lifecycle.py — Integration tests for lead lifecycle.
Uses FastAPI dependency_overrides + mocked GCP clients — no live connections.
"""
from __future__ import annotations

import sys
import os
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../api"))

os.environ["GCP_PROJECT_ID"] = "test-project"
os.environ["APP_ENV"] = "test"
os.environ["VCF_WINDOW_START"] = "2001-09-11"
os.environ["VCF_WINDOW_END"] = "2011-05-30"
os.environ["JWT_AUDIENCE"] = "test-audience"
os.environ["JWT_ISSUER"] = "https://test-issuer.example.com"
os.environ["JWKS_URI"] = "https://test.example.com/.well-known/jwks.json"
os.environ["CLOUD_TASKS_HANDLER_URL"] = "https://test.example.com"
os.environ["RATE_LIMIT_REQUESTS"] = "100"

import pytest
from httpx import AsyncClient, ASGITransport
from fastapi import status


# ── Shared fixtures ───────────────────────────────────────────────────────────

@pytest.fixture
def mock_partner_context():
    from middleware.partner_auth import PartnerContext
    return PartnerContext(
        partner_id="test-partner",
        auth_method="api_key",
        partner_name="Test Partner",
    )


@pytest.fixture
def mock_db():
    """Async Firestore client where all queries return empty results."""
    db = MagicMock()

    mock_query = MagicMock()
    mock_query.where.return_value = mock_query
    mock_query.order_by.return_value = mock_query
    mock_query.limit.return_value = mock_query
    mock_query.start_after.return_value = mock_query
    mock_query.stream.return_value = _async_empty_iter()

    mock_doc_ref = MagicMock()
    mock_doc_ref.get = AsyncMock(return_value=MagicMock(exists=False, to_dict=lambda: {}))
    mock_doc_ref.set = AsyncMock()
    mock_doc_ref.update = AsyncMock()
    mock_doc_ref.id = "ZAD-2026-01-0001"

    db.collection.return_value = MagicMock(
        document=MagicMock(return_value=mock_doc_ref),
        where=MagicMock(return_value=mock_query),
        stream=_async_empty_iter,
    )
    db.transaction.return_value = MagicMock(
        get=AsyncMock(return_value=MagicMock(exists=False, to_dict=lambda: {})),
        set=MagicMock(),
    )
    return db


async def _async_empty_iter():
    return
    yield


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
        "conditions": ["respiratory"],
        "marketingSource": "google_ads",
    }


# ── Helper: build app with dependency overrides applied ───────────────────────

def _make_app(partner_ctx=None, db=None):
    """
    Import the app fresh and apply dependency_overrides so FastAPI uses
    our mocks instead of real GCP clients. Must be called inside a patch
    context that prevents GCP SDK initialisation at module import time.
    """
    from main import app
    from middleware.auth import get_partner
    from services.firestore_client import get_db

    if partner_ctx is not None:
        app.dependency_overrides[get_partner] = lambda: partner_ctx
    if db is not None:
        app.dependency_overrides[get_db] = lambda: db

    return app


def _clear_overrides(app):
    app.dependency_overrides.clear()


# ── Tests ─────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_health_check():
    """Health endpoint returns 200 without auth."""
    with patch("services.firestore_client.get_db"), \
         patch("services.pubsub_service._get_publisher"), \
         patch("services.tasks_service._get_client"):
        from main import app
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/health")
        _clear_overrides(app)

    assert resp.status_code == 200
    assert resp.json()["status"] == "healthy"


@pytest.mark.asyncio
async def test_create_lead_unauthorized_without_auth():
    """POST /api/v1/leads without any auth header returns 401."""
    with patch("services.firestore_client.get_db"), \
         patch("services.pubsub_service._get_publisher"), \
         patch("services.tasks_service._get_client"):
        from main import app
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post("/api/v1/leads", json={"firstName": "Test"})
        _clear_overrides(app)

    assert resp.status_code == status.HTTP_401_UNAUTHORIZED


@pytest.mark.asyncio
async def test_validation_error_returns_400(valid_lead_payload, mock_partner_context, mock_db):
    """
    Malformed payload (bad email) with valid auth returns 400/422.
    Uses dependency_overrides so get_partner and get_db never touch GCP.
    """
    with patch("services.pubsub_service._get_publisher"), \
         patch("services.tasks_service._get_client"):
        app = _make_app(partner_ctx=mock_partner_context, db=mock_db)
        bad_payload = {**valid_lead_payload, "email": "not-an-email"}

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/api/v1/leads",
                json=bad_payload,
                headers={"X-API-Key": "test-key"},
            )
        _clear_overrides(app)

    assert resp.status_code in (400, 422)
