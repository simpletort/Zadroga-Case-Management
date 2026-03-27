import pytest
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient


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


@pytest.fixture(autouse=True)
def mock_firebase():
    """Prevent real Firebase initialisation during tests."""
    with patch("firebase_admin.initialize_app"), \
         patch("firebase_admin._apps", {"[DEFAULT]": MagicMock()}), \
         patch("firebase_admin.auth.verify_id_token") as mock_verify:
        mock_verify.return_value = {
            "uid": "test-uid-001",
            "email": "paralegal@simpletort.com",
            "role": "paralegal",
        }
        yield mock_verify


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
def client(mock_firebase, mock_gcs_client, mock_firestore_client):
    from main import app
    return TestClient(app)
