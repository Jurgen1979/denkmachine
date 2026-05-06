"""integratietests voor de flask-routes."""

import os

import pytest
from werkzeug.security import generate_password_hash

# stel minimale omgevingsvariabelen in voor tests
os.environ.setdefault("DM_USER", "testuser")
os.environ.setdefault("DM_SECRET_KEY", "test-secret-key")
os.environ.setdefault("DM_PASSWORD_HASH", "")


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


def test_login_correct_password_redirects(client, monkeypatch):
    """Controleer dat een correcte login een 302-redirect naar / geeft."""
    hashed = generate_password_hash("testpw", method="pbkdf2:sha256")
    monkeypatch.setenv("DM_USER", "testuser")
    monkeypatch.setenv("DM_PASSWORD_HASH", hashed)

    response = client.post(
        "/login",
        data={"username": "testuser", "password": "testpw"},
    )
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/")


def test_login_wrong_password_returns_401(client, monkeypatch):
    """Controleer dat een foute login een 401-status teruggeeft."""
    hashed = generate_password_hash("testpw", method="pbkdf2:sha256")
    monkeypatch.setenv("DM_USER", "testuser")
    monkeypatch.setenv("DM_PASSWORD_HASH", hashed)

    response = client.post(
        "/login",
        data={"username": "testuser", "password": "foutwachtwoord"},
    )
    assert response.status_code == 401
