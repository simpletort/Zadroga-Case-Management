import pytest
from app import app as flask_app


@pytest.fixture()
def client():
    flask_app.config["TESTING"] = True
    with flask_app.test_client() as c:
        yield c


def test_app_imports():
    """The Flask application object must be importable without errors."""
    from app import app
    assert app is not None


def test_root_responds(client):
    """GET / must return a non-500 response (service is alive)."""
    resp = client.get("/")
    assert resp.status_code < 500
