"""integratietests voor de flask-routes."""

import os

import pytest

# stel minimale omgevingsvariabelen in voor tests
os.environ.setdefault("DM_USER", "testuser")
os.environ.setdefault("DM_SECRET_KEY", "test-secret-key")
os.environ.setdefault("DM_PASSWORD", "")


@pytest.fixture
def client():
    """Geef een flask-testclient terug."""
    from src.app import app

    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def test_login_returns_200(client):
    """Controleer dat /login een 200-status teruggeeft."""
    response = client.get("/login")
    assert response.status_code == 200
