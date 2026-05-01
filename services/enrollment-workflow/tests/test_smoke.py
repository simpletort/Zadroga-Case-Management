import pytest
from fastapi.testclient import TestClient
from app import app


@pytest.fixture()
def client():
    # FastAPI uses Starlette's TestClient — no .config["TESTING"]
    with TestClient(app) as c:
        yield c


def test_app_imports():
    """The FastAPI application object must be importable without errors."""
    from app import app as imported_app
    assert imported_app is not None


def test_root_responds(client):
    """GET / must return a non-500 response (service is alive)."""
    resp = client.get("/")
    assert resp.status_code < 500
