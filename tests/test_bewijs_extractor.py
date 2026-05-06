"""tests voor de BewijsExtractorAgent."""

import json
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


def _make_card_response(n: int, source_type: str = "document") -> dict:
    """Maak een mock-llm-response met n kaarten."""
    cards = [
        {
            "source_type": source_type,
            "claim": f"claim nummer {i}",
            "claim_type": "observation",
            "quote": None,
            "context": None,
            "confidence": "medium",
            "tags": [],
            "category_relevance": [],
        }
        for i in range(n)
    ]
    return {"cards": cards}


def _make_llm_result(content: str) -> dict:
    """Wikkel een string in het llm-result-formaat."""
    return {
        "content": content,
        "input_tokens": 100,
        "output_tokens": 50,
        "cost_eur": 0.01,
        "model_used": "test-model",
        "duration_ms": 200,
    }


def _create_project(status: str = "ingested") -> str:
    """Maak een testproject aan in de db."""
    from src.models import Project
    from src.state import get_session

    project_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    project = Project(
        id=project_id,
        created_at=now,
        updated_at=now,
        user_question="testproject bewijs",
        status=status,
        primary_category="diagnose",
        secondary_category=None,
    )
    with get_session() as session:
        session.add(project)
        session.commit()
    return project_id


def _setup_dirs(project_id: str) -> Path:
    """Maak de vereiste projectmappen aan."""
    project_dir = _PROJECTS_DIR / project_id
    (project_dir / "ingested").mkdir(parents=True, exist_ok=True)
    (project_dir / "evidence").mkdir(parents=True, exist_ok=True)
    return project_dir


def test_extractor_with_one_source():
    """Agent verwerkt één bronbestand en schrijft 3 kaarten naar db en cards.json."""
    from src.agents.bewijs_extractor import BewijsExtractorAgent
    from src.llm_client import LLMClient
    from src.models import EvidenceCard
    from src.state import get_session

    project_id = _create_project()
    project_dir = _setup_dirs(project_id)

    src_file = project_dir / "ingested" / "src_001_testbron.md"
    src_file.write_text("# document\n\ntestinhoud", encoding="utf-8")

    response_json = json.dumps(_make_card_response(3))
    llm_result = _make_llm_result(response_json)

    with patch("src.llm_client.LLMClient.chat", return_value=llm_result):
        agent = BewijsExtractorAgent(LLMClient(), project_id)
        agent.run()

    with get_session() as session:
        cards = (
            session.query(EvidenceCard)
            .filter(EvidenceCard.project_id == project_id)
            .all()
        )
        assert len(cards) == 3

    cards_json_path = project_dir / "evidence" / "cards.json"
    assert cards_json_path.exists()
    saved = json.loads(cards_json_path.read_text(encoding="utf-8"))
    assert len(saved) == 3

    from src.models import Project
    from src.state import get_session
    with get_session() as session:
        project = session.get(Project, project_id)
        assert project.status == "awaiting_evidence_review"


def test_extractor_invalid_json_retries():
    """Bij ongeldige json op eerste poging en geldige json op tweede: kaarten worden opgeslagen."""
    from src.agents.bewijs_extractor import BewijsExtractorAgent
    from src.llm_client import LLMClient
    from src.models import EvidenceCard, Flag
    from src.state import get_session

    project_id = _create_project()
    project_dir = _setup_dirs(project_id)
    (project_dir / "ingested" / "src_001_bron.md").write_text("inhoud", encoding="utf-8")

    valid_json = json.dumps(_make_card_response(2))
    call_count = 0

    def mock_chat(**kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return _make_llm_result("dit is geen geldige json {{{")
        return _make_llm_result(valid_json)

    with patch("src.llm_client.LLMClient.chat", side_effect=mock_chat):
        agent = BewijsExtractorAgent(LLMClient(), project_id)
        agent.run()

    with get_session() as session:
        cards = (
            session.query(EvidenceCard)
            .filter(EvidenceCard.project_id == project_id)
            .all()
        )
        assert len(cards) == 2

        flag = (
            session.query(Flag)
            .filter(
                Flag.project_id == project_id,
                Flag.type == "evidence_source_failed",
            )
            .first()
        )
        assert flag is None


def test_extractor_invalid_twice_skips_source():
    """Bij twee keer ongeldige json: flag aangemaakt, geen kaarten, status failed als enige bron."""
    from src.agents.bewijs_extractor import BewijsExtractorAgent
    from src.llm_client import LLMClient
    from src.models import EvidenceCard, Flag, Project
    from src.state import get_session

    project_id = _create_project()
    project_dir = _setup_dirs(project_id)
    (project_dir / "ingested" / "src_001_bron.md").write_text("inhoud", encoding="utf-8")

    def mock_chat(**kwargs):
        return _make_llm_result("geen json")

    with patch("src.llm_client.LLMClient.chat", side_effect=mock_chat):
        agent = BewijsExtractorAgent(LLMClient(), project_id)
        agent.run()

    with get_session() as session:
        cards = (
            session.query(EvidenceCard)
            .filter(EvidenceCard.project_id == project_id)
            .all()
        )
        assert len(cards) == 0

        flag = (
            session.query(Flag)
            .filter(
                Flag.project_id == project_id,
                Flag.type == "evidence_source_failed",
            )
            .first()
        )
        assert flag is not None

        project = session.get(Project, project_id)
        assert project.status == "failed"


def test_extractor_invalid_twice_second_source_ok():
    """Bij twee bronnen: eerste bron faalt twee keer, tweede slaagt – status awaiting_review."""
    from src.agents.bewijs_extractor import BewijsExtractorAgent
    from src.llm_client import LLMClient
    from src.models import EvidenceCard, Project
    from src.state import get_session

    project_id = _create_project()
    project_dir = _setup_dirs(project_id)
    (project_dir / "ingested" / "src_001_fout.md").write_text("inhoud fout", encoding="utf-8")
    (project_dir / "ingested" / "src_002_ok.md").write_text("inhoud ok", encoding="utf-8")

    valid_json = json.dumps(_make_card_response(2))
    call_count = 0

    def mock_chat(**kwargs):
        nonlocal call_count
        call_count += 1
        if call_count <= 2:
            return _make_llm_result("geen json")
        return _make_llm_result(valid_json)

    with patch("src.llm_client.LLMClient.chat", side_effect=mock_chat):
        agent = BewijsExtractorAgent(LLMClient(), project_id)
        agent.run()

    with get_session() as session:
        cards = (
            session.query(EvidenceCard)
            .filter(EvidenceCard.project_id == project_id)
            .all()
        )
        assert len(cards) == 2

        project = session.get(Project, project_id)
        assert project.status == "awaiting_evidence_review"


def test_extractor_cap_at_250():
    """Agent stopt bij 250 kaarten en maakt flag evidence_cap_reached aan."""
    from src.agents.bewijs_extractor import BewijsExtractorAgent
    from src.llm_client import LLMClient
    from src.models import EvidenceCard, Flag
    from src.state import get_session

    project_id = _create_project()
    project_dir = _setup_dirs(project_id)

    # twee bronnen die elk 200 kaarten produceren
    for i in range(1, 3):
        src = project_dir / "ingested" / f"src_{i:03d}_bron.md"
        src.write_text(f"inhoud bron {i}", encoding="utf-8")

    response_json = json.dumps(_make_card_response(200))
    llm_result = _make_llm_result(response_json)

    with patch("src.llm_client.LLMClient.chat", return_value=llm_result):
        agent = BewijsExtractorAgent(LLMClient(), project_id)
        agent.run()

    with get_session() as session:
        count = (
            session.query(EvidenceCard)
            .filter(EvidenceCard.project_id == project_id)
            .count()
        )
        assert count == 250

        flag = (
            session.query(Flag)
            .filter(
                Flag.project_id == project_id,
                Flag.type == "evidence_cap_reached",
            )
            .first()
        )
        assert flag is not None


def test_extractor_skips_bundle_md():
    """bundle.md wordt overgeslagen, alleen src_001_x.md wordt verwerkt."""
    from src.agents.bewijs_extractor import BewijsExtractorAgent
    from src.llm_client import LLMClient
    from src.models import EvidenceCard
    from src.state import get_session

    project_id = _create_project()
    project_dir = _setup_dirs(project_id)

    (project_dir / "ingested" / "bundle.md").write_text("bundel", encoding="utf-8")
    (project_dir / "ingested" / "src_001_x.md").write_text("bron", encoding="utf-8")

    response_json = json.dumps(_make_card_response(2))
    call_log = []

    def mock_chat(**kwargs):
        call_log.append(kwargs)
        return _make_llm_result(response_json)

    with patch("src.llm_client.LLMClient.chat", side_effect=mock_chat):
        agent = BewijsExtractorAgent(LLMClient(), project_id)
        agent.run()

    # slechts één llm-call (voor src_001, niet voor bundle)
    assert len(call_log) == 1

    with get_session() as session:
        cards = (
            session.query(EvidenceCard)
            .filter(EvidenceCard.project_id == project_id)
            .all()
        )
        assert len(cards) == 2


def test_extractor_no_sources_fails():
    """Lege ingested-map leidt tot status failed en flag evidence_extraction_failed."""
    from src.agents.bewijs_extractor import BewijsExtractorAgent
    from src.llm_client import LLMClient
    from src.models import Flag, Project
    from src.state import get_session

    project_id = _create_project()
    _setup_dirs(project_id)
    # ingested-map leeg laten (geen .md-bestanden)

    agent = BewijsExtractorAgent(LLMClient(), project_id)
    agent.run()

    with get_session() as session:
        project = session.get(Project, project_id)
        assert project.status == "failed"

        flag = (
            session.query(Flag)
            .filter(
                Flag.project_id == project_id,
                Flag.type == "evidence_extraction_failed",
                Flag.severity == "high",
            )
            .first()
        )
        assert flag is not None
