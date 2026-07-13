"""
test_smoke.py — Basic smoke tests confirming the FastAPI app starts and responds.
"""
from __future__ import annotations

import os
import sys
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


@pytest.fixture()
def client():
    with patch("services.firestore_client.get_db"), patch("main.get_db"):
        from main import app
        return TestClient(app)


def test_app_imports():
    """The FastAPI application object must be importable without errors."""
    with patch("services.firestore_client.get_db"), patch("main.get_db"):
        from main import app
        assert app is not None


def test_root_responds(client):
    """GET / must return a non-500 response (service is alive)."""
    resp = client.get("/")
    assert resp.status_code < 500
    assert resp.json()["service"] == "ZAD Settlement Financial Service"
