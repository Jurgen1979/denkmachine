"""gedeelde pytest-fixtures en setup voor alle tests."""

import os

# stel testomgevingsvariabelen in vóór src-modules geïmporteerd worden
os.environ.setdefault("DM_USER", "testuser")
os.environ.setdefault("DM_SECRET_KEY", "test-secret-key")
os.environ.setdefault("DM_PASSWORD_HASH", "")
os.environ.setdefault("OPENROUTER_API_KEY", "test-key")


def pytest_configure(config):
    """Initialiseer de database vóór alle tests."""
    from src.state import init_db

    init_db()
