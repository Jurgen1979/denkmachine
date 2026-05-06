"""tests voor de IngestAgent."""

import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("DM_USER", "testuser")
os.environ.setdefault("DM_SECRET_KEY", "test-secret-key")
os.environ.setdefault("DM_PASSWORD_HASH", "")
os.environ.setdefault("OPENROUTER_API_KEY", "test-key")
os.environ.setdefault("FIRECRAWL_API_KEY", "test-firecrawl-key")

_BASE_DIR = Path(__file__).parent.parent
_PROJECTS_DIR = _BASE_DIR / "projects"

_MOCK_LLM_RESULT = {
    "content": (
        "# bundel\n\n## src_001: testbron\n\ntekst.\n\n## opvallende verbanden\n\n- patroon 1"
    ),
    "input_tokens": 100,
    "output_tokens": 200,
    "cost_eur": 0.01,
    "model_used": "test-model",
    "duration_ms": 500,
}


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
    return project_id


def _setup_project_dirs(project_id: str) -> Path:
    """Maak de benodigde projectmappen aan."""
    project_dir = _PROJECTS_DIR / project_id
    (project_dir / "inputs" / "documents").mkdir(parents=True, exist_ok=True)
    (project_dir / "ingested").mkdir(parents=True, exist_ok=True)
    return project_dir


def test_ingest_with_one_document():
    """IngestAgent verwerkt één document en genereert src_001_*.md plus bundle.md."""
    from src.agents.ingest import IngestAgent
    from src.llm_client import LLMClient

    project_id = _create_project("ingesting")
    project_dir = _setup_project_dirs(project_id)

    doc_file = project_dir / "inputs" / "documents" / "rapport.txt"
    doc_file.write_text("inhoud van het rapport", encoding="utf-8")

    with patch("src.llm_client.LLMClient.chat", return_value=_MOCK_LLM_RESULT):
        agent = IngestAgent(LLMClient(), project_id)
        agent.run()

    ingested = list((project_dir / "ingested").iterdir())
    src_files = [f for f in ingested if f.name.startswith("src_001")]
    bundle = project_dir / "ingested" / "bundle.md"

    assert len(src_files) == 1
    assert bundle.exists()


def test_ingest_with_one_url():
    """IngestAgent verwerkt één url en genereert src_001_*.md."""
    from src.agents.ingest import IngestAgent
    from src.llm_client import LLMClient

    project_id = _create_project("ingesting")
    project_dir = _setup_project_dirs(project_id)

    urls_file = project_dir / "inputs" / "urls.txt"
    urls_file.write_text("https://www.example.com/pagina", encoding="utf-8")

    mock_markdown = "# https://www.example.com/pagina\n\npagina-inhoud"

    with (
        patch("src.agents.ingest.scrape_url", return_value=mock_markdown),
        patch("src.llm_client.LLMClient.chat", return_value=_MOCK_LLM_RESULT),
    ):
        agent = IngestAgent(LLMClient(), project_id)
        agent.run()

    ingested = list((project_dir / "ingested").iterdir())
    src_files = [f for f in ingested if f.name.startswith("src_001")]
    assert len(src_files) == 1


def test_ingest_no_input_sets_failed():
    """IngestAgent zet status op failed als er geen documenten en urls zijn."""
    from src.agents.ingest import IngestAgent
    from src.llm_client import LLMClient
    from src.models import Flag, Project
    from src.state import get_session

    project_id = _create_project("ingesting")
    _setup_project_dirs(project_id)

    agent = IngestAgent(LLMClient(), project_id)
    agent.run()

    with get_session() as session:
        project = session.get(Project, project_id)
        assert project.status == "failed"
        flag = (
            session.query(Flag)
            .filter(Flag.project_id == project_id, Flag.type == "ingest_failed")
            .first()
        )
        assert flag is not None


def test_ingest_partial_failure_continues():
    """Bij één falend document van twee: tweede slaagt, flag aangemaakt, status ingested."""
    from src.agents.ingest import IngestAgent
    from src.llm_client import LLMClient
    from src.models import Flag, Project
    from src.state import get_session

    project_id = _create_project("ingesting")
    project_dir = _setup_project_dirs(project_id)

    # twee documenten – alfabetisch: a_fout.txt en b_ok.txt
    (project_dir / "inputs" / "documents" / "a_fout.txt").write_text("fout", encoding="utf-8")
    (project_dir / "inputs" / "documents" / "b_ok.txt").write_text("ok inhoud", encoding="utf-8")

    call_count = 0

    def mock_parse(file_path, source_id):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise ValueError("gesimuleerde parse-fout")
        return f"# {file_path.name}\n\nok inhoud"

    with (
        patch("src.agents.ingest.parse_document", side_effect=mock_parse),
        patch("src.llm_client.LLMClient.chat", return_value=_MOCK_LLM_RESULT),
    ):
        agent = IngestAgent(LLMClient(), project_id)
        agent.run()

    ingested = list((project_dir / "ingested").iterdir())
    src_002_files = [f for f in ingested if f.name.startswith("src_002")]
    assert len(src_002_files) == 1

    with get_session() as session:
        project = session.get(Project, project_id)
        assert project.status == "ingested"
        flag = (
            session.query(Flag)
            .filter(
                Flag.project_id == project_id,
                Flag.type == "ingest_source_failed",
            )
            .first()
        )
        assert flag is not None
