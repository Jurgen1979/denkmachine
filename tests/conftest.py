"""gedeelde pytest-fixtures en setup voor alle tests."""

import os
import shutil
import tempfile
from pathlib import Path

# tijdelijke db aanmaken vóór src-modules geladen worden
_tmp_db_dir = tempfile.mkdtemp(prefix="dm_test_")
_tmp_db_path = os.path.join(_tmp_db_dir, "test.db")
os.environ["DM_DB_URL"] = f"sqlite:///{_tmp_db_path}"

# overige testomgevingsvariabelen
os.environ.setdefault("DM_USER", "testuser")
os.environ.setdefault("DM_SECRET_KEY", "test-secret-key")
os.environ.setdefault("DM_PASSWORD_HASH", "")
os.environ.setdefault("OPENROUTER_API_KEY", "test-key")


def pytest_configure(config):
    """Initialiseer de tijdelijke test-database vóór alle tests."""
    from src.state import init_db

    init_db()


def pytest_sessionfinish(session, exitstatus):
    """Ruim test-projectmappen en de tijdelijke db op na alle tests."""
    # projectmappen
    base = Path(__file__).parent.parent / "projects"
    if base.exists():
        for child in base.iterdir():
            if not child.is_dir():
                continue
            name = child.name
            if len(name) == 36 and name.count("-") == 4:
                try:
                    shutil.rmtree(child, ignore_errors=True)
                except Exception:
                    pass

    # tijdelijke db-map
    try:
        shutil.rmtree(_tmp_db_dir, ignore_errors=True)
    except Exception:
        pass
