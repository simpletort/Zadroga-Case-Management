"""
tests/conftest.py — Shared pytest fixtures for the Notification Service test suite.

Fixture hierarchy
-----------------
settings         → patched Settings object with safe test values
mock_db          → AsyncMock Firestore client with pre-wired collection/document stubs
mock_twilio_msg  → a fake Twilio message object (sid, status)
app_client       → FastAPI TestClient with OIDC verification bypassed

All fixtures patch at the lowest useful level so individual tests can
override specific return values without re-patching the whole chain.
"""
from __future__ import annotations

import sys
import os
from typing import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio

# ── Make the notification service importable from the tests directory ─────────
# (In CI the PYTHONPATH is set; locally this covers running pytest from /tests)
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ── Env-var defaults so Settings() doesn't fail on missing required fields ────
os.environ.setdefault("TWILIO_ACCOUNT_SID", "ACtest00000000000000000000000000000")
os.environ.setdefault("TWILIO_AUTH_TOKEN", "test_auth_token_32chars_xxxxxxxxxx")
os.environ.setdefault("TWILIO_FROM_NUMBER", "+15005550006")  # Twilio test number
os.environ.setdefault("GCP_PROJECT_ID", "test-project")
os.environ.setdefault("APP_ENV", "development")  # disables OIDC/Twilio sig checks
os.environ.setdefault("NOTIFICATION_SERVICE_URL", "https://notification-test.run.app")
os.environ.setdefault("NOTIFICATION_SA_EMAIL", "test-sa@test-project.iam.gserviceaccount.com")


# ── Settings fixture ──────────────────────────────────────────────────────────

@pytest.fixture()
def settings():
    """Return a fresh (uncached) Settings instance for test isolation."""
    from config import Settings
    return Settings()


# ── Firestore mock helpers ────────────────────────────────────────────────────

def _make_doc_snapshot(exists: bool, data: dict | None = None) -> MagicMock:
    """Build a fake Firestore DocumentSnapshot."""
    snap = MagicMock()
    snap.exists = exists
    snap.to_dict.return_value = data or {}
    return snap


def _make_doc_ref(snap: MagicMock) -> AsyncMock:
    """Build a fake Firestore DocumentReference whose .get() returns *snap*."""
    ref = AsyncMock()
    ref.get = AsyncMock(return_value=snap)
    ref.set = AsyncMock()
    ref.update = AsyncMock()
    return ref


def _make_collection(doc_ref: AsyncMock) -> MagicMock:
    """Build a fake Firestore CollectionReference."""
    col = MagicMock()
    col.document = MagicMock(return_value=doc_ref)
    return col


@pytest.fixture()
def mock_db():
    """
    Return a minimal AsyncMock Firestore client.

    Individual tests should call ``mock_db.collection.return_value.document
    .return_value.get.return_value = _make_doc_snapshot(...)`` to set up
    specific document responses, or use the helper fixtures below.
    """
    db = AsyncMock()
    db.collection = MagicMock()
    return db


# ── Twilio mock ───────────────────────────────────────────────────────────────

@pytest.fixture()
def mock_twilio_msg():
    """A fake Twilio message object returned by client.messages.create()."""
    msg = MagicMock()
    msg.sid = "SM1234567890abcdef1234567890abcdef"
    msg.status = "queued"
    return msg


@pytest.fixture()
def mock_twilio_client(mock_twilio_msg):
    """Patch twilio_client._client so no real Twilio calls are made."""
    import services.twilio_client as tc
    fake_client = MagicMock()
    fake_client.messages.create.return_value = mock_twilio_msg

    # Reset module-level singleton before and after each test
    original = tc._client
    tc._client = fake_client
    yield fake_client
    tc._client = original


# ── FastAPI TestClient ────────────────────────────────────────────────────────

@pytest.fixture()
def app_client():
    """
    Return a Starlette TestClient for the FastAPI app.

    Firestore init is bypassed by patching get_db().
    OIDC verification is bypassed because APP_ENV=development.
    """
    from fastapi.testclient import TestClient
    from unittest.mock import patch, AsyncMock

    fake_db = AsyncMock()
    fake_db.collection = MagicMock()

    with patch("app.get_db", return_value=fake_db):
        from app import app
        with TestClient(app, raise_server_exceptions=False) as client:
            yield client, fake_db
