"""integratietests voor de upload- en progress-routes."""

import io
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest
from werkzeug.security import generate_password_hash

os.environ.setdefault("DM_USER", "testuser")
os.environ.setdefault("DM_SECRET_KEY", "test-secret-key")
os.environ.setdefault("DM_PASSWORD_HASH", "")
os.environ.setdefault("OPENROUTER_API_KEY", "test-key")
os.environ.setdefault("FIRECRAWL_API_KEY", "test-firecrawl-key")

_BASE_DIR = Path(__file__).parent.parent
_PROJECTS_DIR = _BASE_DIR / "projects"


@pytest.fixture
def client():
    """Geef een flask-testclient terug."""
    from src.app import app

    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


@pytest.fixture
def logged_in_client(client, monkeypatch):
    """Geef een ingelogde flask-testclient terug."""
    hashed = generate_password_hash("testpw", method="pbkdf2:sha256")
    monkeypatch.setenv("DM_USER", "testuser")
    monkeypatch.setenv("DM_PASSWORD_HASH", hashed)
    client.post("/login", data={"username": "testuser", "password": "testpw"})
    return client


def _create_project(status: str) -> str:
    """Maak een testproject aan in de db met de gegeven status."""
    from src.models import Project
    from src.state import get_session

    project_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    project = Project(
        id=project_id,
        created_at=now,
        updated_at=now,
        user_question="testproject",
        status=status,
    )
    with get_session() as session:
        session.add(project)
        session.commit()

    project_dir = _PROJECTS_DIR / project_id
    (project_dir / "inputs" / "documents").mkdir(parents=True, exist_ok=True)
    (project_dir / "ingested").mkdir(parents=True, exist_ok=True)

    return project_id


def test_upload_page_renders(logged_in_client):
    """GET /upload geeft 200 terug met het formulier voor een plan_approved project."""
    project_id = _create_project("plan_approved")

    response = logged_in_client.get(f"/project/{project_id}/upload")

    assert response.status_code == 200
    body = response.data.decode("utf-8")
    assert "documenten" in body
    assert "urls" in body
    assert "start pipeline" in body


def test_upload_files_saves_to_disk(logged_in_client):
    """POST /upload/files slaat het bestand op in inputs/documents/."""
    project_id = _create_project("plan_approved")

    data = {
        "documents": (io.BytesIO(b"testinhoud"), "rapport.txt"),
    }
    response = logged_in_client.post(
        f"/project/{project_id}/upload/files",
        data=data,
        content_type="multipart/form-data",
    )

    assert response.status_code == 302
    saved = _PROJECTS_DIR / project_id / "inputs" / "documents" / "rapport.txt"
    assert saved.exists()
    assert saved.read_bytes() == b"testinhoud"


def test_upload_urls_writes_to_file(logged_in_client):
    """POST /upload/urls schrijft urls.txt naar de projectmap."""
    project_id = _create_project("plan_approved")

    response = logged_in_client.post(
        f"/project/{project_id}/upload/urls",
        data={"urls": "https://www.example.com\nhttps://www.test.be"},
    )

    assert response.status_code == 302
    urls_file = _PROJECTS_DIR / project_id / "inputs" / "urls.txt"
    assert urls_file.exists()
    lines = [u for u in urls_file.read_text(encoding="utf-8").splitlines() if u]
    assert "https://www.example.com" in lines
    assert "https://www.test.be" in lines


def test_upload_start_changes_status(logged_in_client):
    """POST /upload/start zet status op ingesting en redirect naar /progress."""
    from src.models import Project
    from src.state import get_session

    project_id = _create_project("plan_approved")

    docs_dir = _PROJECTS_DIR / project_id / "inputs" / "documents"
    (docs_dir / "doc.txt").write_text("inhoud", encoding="utf-8")

    with patch("src.routes.upload.start_ingest_thread"):
        response = logged_in_client.post(f"/project/{project_id}/upload/start")

    assert response.status_code == 302
    assert f"/project/{project_id}/progress" in response.headers["Location"]

    with get_session() as session:
        project = session.get(Project, project_id)
        assert project.status == "ingesting"
