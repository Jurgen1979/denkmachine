"""gedeelde pytest-fixtures en setup voor alle tests."""

import os
import shutil
from pathlib import Path

# stel testomgevingsvariabelen in vóór src-modules geïmporteerd worden
os.environ.setdefault("DM_USER", "testuser")
os.environ.setdefault("DM_SECRET_KEY", "test-secret-key")
os.environ.setdefault("DM_PASSWORD_HASH", "")
os.environ.setdefault("OPENROUTER_API_KEY", "test-key")


def pytest_configure(config):
    """Initialiseer de database vóór alle tests."""
    from src.state import init_db

    init_db()


def pytest_sessionfinish(session, exitstatus):
    """Verwijder test-projects/<uuid>/-mappen na alle tests."""
    base = Path(__file__).parent.parent / "projects"
    if not base.exists():
        return
    for child in base.iterdir():
        if not child.is_dir():
            continue
        # uuid-formaat: 8-4-4-4-12 hex chars
        name = child.name
        if len(name) == 36 and name.count("-") == 4:
            try:
                shutil.rmtree(child, ignore_errors=True)
            except Exception:
                pass
