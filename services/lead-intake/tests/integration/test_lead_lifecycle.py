"""
tests/integration/test_lead_lifecycle.py — Integration tests for lead lifecycle.
Uses mocked Firestore, Pub/Sub, and Cloud Tasks — no live GCP connections.
"""
from __future__ import annotations
import sys
import os
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../api'))

import pytest
from httpx import AsyncClient, ASGITransport
from fastapi import status

# We patch GCP clients before importing app
os.environ["GCP_PROJECT_ID"] = "test-project"
os.environ["APP_ENV"] = "test"


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
    """Mock async Firestore client."""
    db = MagicMock()

    # Mock transaction
    mock_transaction = MagicMock()
    mock_transaction.get = AsyncMock(return_value=MagicMock(exists=False, to_dict=lambda: {}))
    db.transaction.return_value = mock_transaction

    # Mock collection queries (no duplicate)
    mock_query = MagicMock()
    mock_query.where.return_value = mock_query
    mock_query.limit.return_value = mock_query
    mock_query.stream.return_value = _async_empty_iter()
    db.collection.return_value = MagicMock(
        document=MagicMock(return_value=MagicMock(
            get=AsyncMock(return_value=MagicMock(exists=False)),
            set=MagicMock(),
            update=AsyncMock(),
        )),
        where=MagicMock(return_value=mock_query),
        stream=_async_empty_iter,
    )

    return db


async def _async_empty_iter():
    """Async generator that yields nothing."""
    return
    yield  # Makes it an async generator


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


@pytest.mark.asyncio
async def test_health_check():
    """Health endpoint returns 200 without auth."""
    with patch("services.firestore_client.get_db"), \
         patch("services.pubsub_service._get_publisher"), \
         patch("services.tasks_service._get_client"):
        from main import app
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/health")
            assert resp.status_code == 200
            assert resp.json()["status"] == "healthy"


@pytest.mark.asyncio
async def test_create_lead_unauthorized_without_auth():
    """POST /api/v1/leads without auth returns 401."""
    with patch("services.firestore_client.get_db"), \
         patch("services.pubsub_service._get_publisher"), \
         patch("services.tasks_service._get_client"):
        from main import app
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/api/v1/leads", json={"firstName": "Test"})
            assert resp.status_code == status.HTTP_401_UNAUTHORIZED


@pytest.mark.asyncio
async def test_validation_error_returns_400(valid_lead_payload, mock_partner_context):
    """Invalid lead payload returns 400 with error details."""
    with patch("middleware.auth.get_partner", return_value=mock_partner_context), \
         patch("services.firestore_client.get_db"), \
         patch("services.pubsub_service._get_publisher"), \
         patch("services.tasks_service._get_client"):
        from main import app

        # Break the payload
        bad_payload = {**valid_lead_payload, "email": "not-an-email"}

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/api/v1/leads",
                json=bad_payload,
                headers={"X-API-Key": "test-key"},
            )
            assert resp.status_code in (400, 422)
