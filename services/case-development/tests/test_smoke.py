"""Smoke test — verifies the FastAPI app is importable and health endpoint works."""

import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient


def test_app_imports():
    """The FastAPI application object must be importable without errors."""
    with patch("app.utils.firestore.get_firestore_client", return_value=MagicMock()), \
         patch("firebase_admin._apps", [True]):
        from main import app
    assert app is not None


def test_health_endpoint():
    """GET /health must return 200 with status ok."""
    with patch("app.utils.firestore.get_firestore_client", return_value=MagicMock()), \
         patch("firebase_admin._apps", [True]):
        from main import app
    client = TestClient(app)
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"
    assert resp.json()["service"] == "case-development"
