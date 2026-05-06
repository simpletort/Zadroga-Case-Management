import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def mock_gcs_signing_credentials():
    """Prevent real GCP auth calls during tests."""
    with patch("app.services.gcs_service._get_signing_credentials", return_value=MagicMock()):
        yield


@pytest.fixture(autouse=True)
def bypass_auth(monkeypatch):
    """Bypass AuthMiddleware in all tests — no real tokens or Firestore role lookups."""
    async def _passthrough(self, request, call_next):
        request.state.user = {"uid": "test-uid", "role": "admin_staff", "email": "test@simpletort.com"}
        return await call_next(request)
    monkeypatch.setattr("shared.middlewares.auth.AuthMiddleware.dispatch", _passthrough)


@pytest.fixture(autouse=True)
def mock_cloud_logger():
    """
    Prevent real Cloud Logging calls during tests.

    Patches get_cloud_logger in the audit module so every call to
    log_audit_event() uses a MagicMock logger instead of attempting
    to connect to GCP.  The mock is yielded so individual tests can
    assert on it (e.g. mock_cloud_logger.log_struct.assert_called()).
    """
    with patch("app.utils.audit.get_cloud_logger") as mock_fn:
        mock_logger = MagicMock()
        mock_fn.return_value = mock_logger
        yield mock_logger


@pytest.fixture
def mock_gcs_client():
    with patch("app.utils.gcs_client.get_gcs_client") as mock:
        client = MagicMock()
        mock.return_value = client
        yield client


@pytest.fixture
def mock_firestore_client():
    with patch("app.utils.firestore.get_firestore_client") as mock:
        db = MagicMock()
        mock.return_value = db
        yield db


@pytest.fixture
def client(mock_gcs_client, mock_firestore_client):
    from main import app
    return TestClient(app)
