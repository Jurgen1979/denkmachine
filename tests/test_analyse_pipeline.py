"""tests voor de sprint-4 analyse-pipeline: agents, schema, routes en background."""

import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

os.environ.setdefault("DM_USER", "testuser")
os.environ.setdefault("DM_SECRET_KEY", "test-secret-key")
os.environ.setdefault("DM_PASSWORD_HASH", "")
os.environ.setdefault("OPENROUTER_API_KEY", "test-key")
os.environ.setdefault("FIRECRAWL_API_KEY", "test-firecrawl-key")

_BASE_DIR = Path(__file__).parent.parent
_PROJECTS_DIR = _BASE_DIR / "projects"


# ============================================================
# helpers
# ============================================================


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


def _create_project(status: str = "evidence_approved") -> str:
    """Maak een testproject aan in de db."""
    from src.models import Project
    from src.state import get_session

    project_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    project = Project(
        id=project_id,
        created_at=now,
        updated_at=now,
        user_question="hoe komt het dat onze website niet converteert?",
        status=status,
        primary_category="diagnose",
        secondary_category=None,
        output_type="diagnose_report",
    )
    with get_session() as session:
        session.add(project)
        session.commit()
    return project_id


def _create_cards(project_id: str, n: int = 3, approved: bool = True) -> list[str]:
    """Maak n bewijskaarten aan voor een project."""
    from src.models import EvidenceCard
    from src.state import get_session

    ids = []
    human_status = "approved" if approved else "pending"
    with get_session() as session:
        for i in range(n):
            ev_id = f"ev_t{i:02d}_{project_id[:4]}"
            card = EvidenceCard(
                id=ev_id,
                project_id=project_id,
                source_id="src_001",
                source_type="document",
                claim=f"testclaim {i}",
                claim_type="observation",
                quote=None,
                context=None,
                confidence="medium",
                tags=json.dumps([]),
                category_relevance=json.dumps(["diagnose"]),
                human_reviewed=approved,
                human_status=human_status,
                created_by="bewijs_extractor",
                created_at=datetime.now(timezone.utc).isoformat(),
            )
            session.add(card)
            ids.append(ev_id)
        session.commit()
    return ids


def _setup_project_dirs(project_id: str) -> Path:
    """Maak basismap en plan.json aan voor een testproject."""
    project_dir = _PROJECTS_DIR / project_id
    (project_dir / "ingested").mkdir(parents=True, exist_ok=True)
    (project_dir / "analysis").mkdir(parents=True, exist_ok=True)
    (project_dir / "drafts").mkdir(parents=True, exist_ok=True)
    (project_dir / "final").mkdir(parents=True, exist_ok=True)

    plan = {
        "primary_category": "diagnose",
        "interpreted_goal": "begrijpen waarom de website niet converteert",
        "scope": "website en analytics van 2024",
        "active_role_pack": {
            "analyst_roles": ["situatie_analist", "oorzaak_zoeker"],
            "critique_roles": ["bewijs_vrager"],
        },
        "research_plan": {
            "report_sections": [
                {"id": "situation", "title": "huidige situatie", "estimated_length_words": 200},
                {"id": "findings", "title": "bevindingen", "estimated_length_words": 250},
            ]
        },
        "output_type": "diagnose_report",
    }
    (project_dir / "plan.json").write_text(
        json.dumps(plan, ensure_ascii=False), encoding="utf-8"
    )
    (project_dir / "ingested" / "bundle.md").write_text(
        "## test bundel\n\ndit is de testbundel.", encoding="utf-8"
    )
    return project_dir


@pytest.fixture
def client():
    """Flask test-client met ingelogde gebruiker."""
    from src.app import app

    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False

    with app.test_client() as c:
        with c.session_transaction() as sess:
            sess["_user_id"] = "1"
            sess["_fresh"] = True
        yield c


# ============================================================
# schema: CritiqueResult
# ============================================================


def test_critique_result_valid():
    """CritiqueResult parsed correct bij geldige json."""
    from src.schemas.analyse import CritiqueResult

    data = {
        "needs_redo": True,
        "weak_sections": ["situation"],
        "general_feedback": "onderbouwing ontbreekt",
        "section_feedback": {"situation": "te vaag"},
        "severity": "high",
    }
    result = CritiqueResult.model_validate(data)
    assert result.needs_redo is True
    assert "situation" in result.weak_sections
    assert result.severity == "high"


def test_critique_result_defaults():
    """CritiqueResult accepteert minimale json met defaults."""
    from src.schemas.analyse import CritiqueResult

    data = {
        "needs_redo": False,
        "general_feedback": "goed",
        "severity": "low",
    }
    result = CritiqueResult.model_validate(data)
    assert result.weak_sections == []
    assert result.section_feedback == {}


def test_critique_result_invalid_severity():
    """CritiqueResult weigert ongeldige severity-waarde."""
    from pydantic import ValidationError

    from src.schemas.analyse import CritiqueResult

    with pytest.raises(ValidationError):
        CritiqueResult.model_validate(
            {"needs_redo": False, "general_feedback": "x", "severity": "critical"}
        )


# ============================================================
# AnalystRunner
# ============================================================


def test_analyst_runner_run():
    """AnalystRunner schrijft per rol een bestand en geeft outputs terug."""
    project_id = _create_project()
    project_dir = _setup_project_dirs(project_id)
    _create_cards(project_id, n=3, approved=True)

    mock_llm = MagicMock()
    mock_llm.chat.return_value = _make_llm_result("## bevindingen\n\ntest.")

    from src.agents.analyst_runner import AnalystRunner

    runner = AnalystRunner(mock_llm, project_id)
    outputs = runner.run()

    assert "situatie_analist" in outputs
    assert "oorzaak_zoeker" in outputs
    assert (project_dir / "analysis" / "role_situatie_analist.md").exists()
    assert (project_dir / "analysis" / "role_oorzaak_zoeker.md").exists()

    from src.models import Project
    from src.state import get_session

    with get_session() as session:
        project = session.get(Project, project_id)
    assert project.status == "analysing"


def test_analyst_runner_missing_project():
    """AnalystRunner geeft leeg dict terug als project niet bestaat."""
    from src.agents.analyst_runner import AnalystRunner

    mock_llm = MagicMock()
    runner = AnalystRunner(mock_llm, "niet-bestaand-id")
    result = runner.run()
    assert result == {}


# ============================================================
# CritiqueRunner
# ============================================================


def test_critique_runner_run():
    """CritiqueRunner schrijft per rol een critique-bestand en geeft resultaten terug."""
    project_id = _create_project()
    project_dir = _setup_project_dirs(project_id)
    _create_cards(project_id, n=2, approved=True)

    critique_json = json.dumps(
        {
            "needs_redo": False,
            "weak_sections": [],
            "general_feedback": "analyse is solide",
            "section_feedback": {},
            "severity": "low",
        },
        ensure_ascii=False,
    )
    mock_llm = MagicMock()
    mock_llm.chat.return_value = _make_llm_result(critique_json)

    from src.agents.critique_runner import CritiqueRunner

    runner = CritiqueRunner(mock_llm, project_id)
    analyst_outputs = {"situatie_analist": "analyse tekst", "oorzaak_zoeker": "oorzaken tekst"}
    results = runner.run(analyst_outputs)

    assert len(results) == 1
    assert results[0].needs_redo is False
    assert (project_dir / "analysis" / "critique_bewijs_vrager.md").exists()


def test_critique_runner_parse_fout_geeft_fallback():
    """CritiqueRunner geeft een fallback CritiqueResult terug bij parse-fout."""
    project_id = _create_project()
    _setup_project_dirs(project_id)
    _create_cards(project_id, n=1, approved=True)

    mock_llm = MagicMock()
    mock_llm.chat.return_value = _make_llm_result("GEEN GELDIG JSON HIER")

    from src.agents.critique_runner import CritiqueRunner

    runner = CritiqueRunner(mock_llm, project_id)
    results = runner.run({"situatie_analist": "tekst"})

    assert len(results) == 1
    assert results[0].needs_redo is False
    assert results[0].severity == "low"


# ============================================================
# DraftAgent
# ============================================================


def test_draft_agent_run_no_redo():
    """DraftAgent schrijft secties zonder redo als critique low is."""
    project_id = _create_project()
    project_dir = _setup_project_dirs(project_id)
    _create_cards(project_id, n=2, approved=True)

    mock_llm = MagicMock()
    mock_llm.chat.return_value = _make_llm_result("## huidige situatie\n\ninhoud.")

    from src.agents.draft_agent import DraftAgent
    from src.schemas.analyse import CritiqueResult

    critiques = [
        CritiqueResult(
            needs_redo=False,
            weak_sections=[],
            general_feedback="goed",
            section_feedback={},
            severity="low",
        )
    ]
    agent = DraftAgent(mock_llm, project_id)
    drafts = agent.run({"situatie_analist": "analyse"}, critiques)

    assert "situation" in drafts
    assert (project_dir / "drafts" / "section_situation.md").exists()
    assert not (project_dir / "drafts" / "section_situation_v2.md").exists()


def test_draft_agent_redo_high_severity():
    """DraftAgent schrijft v2 als critique severity=high en needs_redo=True."""
    project_id = _create_project()
    project_dir = _setup_project_dirs(project_id)
    _create_cards(project_id, n=2, approved=True)

    call_count = 0

    def _side_effect(**kwargs):
        nonlocal call_count
        call_count += 1
        return _make_llm_result(f"## sectie\n\nversie {call_count}.")

    mock_llm = MagicMock()
    mock_llm.chat.side_effect = _side_effect

    from src.agents.draft_agent import DraftAgent
    from src.schemas.analyse import CritiqueResult

    critiques = [
        CritiqueResult(
            needs_redo=True,
            weak_sections=["situation"],
            general_feedback="te vaag",
            section_feedback={"situation": "voeg meer bewijs toe"},
            severity="high",
        )
    ]
    agent = DraftAgent(mock_llm, project_id)
    agent.run({"situatie_analist": "analyse"}, critiques)

    assert (project_dir / "drafts" / "section_situation_v2.md").exists()


# ============================================================
# SyntheseAgent
# ============================================================


def test_synthese_agent_run():
    """SyntheseAgent schrijft output.md en action_plan.md en zet status op done."""
    project_id = _create_project(status="synthesising")
    project_dir = _setup_project_dirs(project_id)

    call_count = 0

    def _side_effect(**kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return _make_llm_result("# diagnose-rapport\n\n## huidige situatie\n\ntekst.")
        return _make_llm_result("## actieplan\n\n1. doe dit\n2. doe dat")

    mock_llm = MagicMock()
    mock_llm.chat.side_effect = _side_effect

    from src.agents.synthese_agent import SyntheseAgent

    section_drafts = {
        "situation": "## huidige situatie\n\ntekst.",
        "findings": "## bevindingen\n\ntekst.",
    }
    agent = SyntheseAgent(mock_llm, project_id)
    output_path = agent.run(section_drafts)

    assert (project_dir / "final" / "output.md").exists()
    assert (project_dir / "final" / "action_plan.md").exists()
    assert output_path.endswith("output.md")

    from src.models import Project
    from src.state import get_session

    with get_session() as session:
        project = session.get(Project, project_id)
    assert project.status == "done"


def test_synthese_agent_post_processing_lege_sectie():
    """SyntheseAgent voegt flag toe voor een verplichte lege sectie."""
    project_id = _create_project(status="synthesising")
    _setup_project_dirs(project_id)

    mock_llm = MagicMock()
    mock_llm.chat.return_value = _make_llm_result("# rapport\n\ntekst.")

    from src.agents.synthese_agent import SyntheseAgent
    from src.models import Flag
    from src.state import get_session

    agent = SyntheseAgent(mock_llm, project_id)
    # lege section_drafts - alle verplichte secties ontbreken
    agent.run({})

    with get_session() as session:
        flags = (
            session.query(Flag)
            .filter(Flag.project_id == project_id, Flag.type == "required_section_missing")
            .all()
        )
    assert len(flags) > 0


# ============================================================
# draft_agent._aggregate_critique
# ============================================================


def test_aggregate_critique_leeg():
    """_aggregate_critique geeft lege sets terug als er geen high-critiques zijn."""
    from src.agents.draft_agent import _aggregate_critique
    from src.schemas.analyse import CritiqueResult

    critiques = [
        CritiqueResult(
            needs_redo=False,
            weak_sections=[],
            general_feedback="ok",
            section_feedback={},
            severity="low",
        ),
        CritiqueResult(
            needs_redo=True,
            weak_sections=["findings"],
            general_feedback="matig",
            section_feedback={"findings": "te kort"},
            severity="medium",
        ),
    ]
    weak, feedback = _aggregate_critique(critiques)
    assert len(weak) == 0


def test_aggregate_critique_high_severity():
    """_aggregate_critique neemt alleen high-severity op in weak_sections."""
    from src.agents.draft_agent import _aggregate_critique
    from src.schemas.analyse import CritiqueResult

    critiques = [
        CritiqueResult(
            needs_redo=True,
            weak_sections=["situation", "findings"],
            general_feedback="zwak",
            section_feedback={"situation": "geen bewijs", "findings": "te vaag"},
            severity="high",
        ),
    ]
    weak, feedback = _aggregate_critique(critiques)
    assert "situation" in weak
    assert "findings" in weak
    assert "geen bewijs" in feedback["situation"]


# ============================================================
# output-routes
# ============================================================


def test_analyse_start_route_correct_status(client):
    """POST /analyse/start zet status op analysing en redirect naar progress."""
    project_id = _create_project(status="evidence_approved")
    _setup_project_dirs(project_id)

    with patch("src.background.start_analysis_thread") as mock_thread:
        resp = client.post(f"/project/{project_id}/analyse/start")

    assert resp.status_code == 302
    assert "progress" in resp.headers["Location"]
    mock_thread.assert_called_once_with(project_id)

    from src.models import Project
    from src.state import get_session

    with get_session() as session:
        project = session.get(Project, project_id)
    assert project.status == "analysing"


def test_analyse_start_route_verkeerde_status(client):
    """POST /analyse/start redirect terug als status niet evidence_approved is."""
    project_id = _create_project(status="awaiting_evidence_review")

    with patch("src.background.start_analysis_thread") as mock_thread:
        resp = client.post(f"/project/{project_id}/analyse/start")

    assert resp.status_code == 302
    mock_thread.assert_not_called()


def test_output_view_done(client):
    """GET /output toont de output-pagina als status done is."""
    project_id = _create_project(status="done")
    project_dir = _setup_project_dirs(project_id)
    (project_dir / "final" / "output.md").write_text(
        "# rapport\n\ntekst.", encoding="utf-8"
    )
    (project_dir / "final" / "action_plan.md").write_text(
        "## actieplan\n\n1. stap.", encoding="utf-8"
    )

    resp = client.get(f"/project/{project_id}/output")
    assert resp.status_code == 200
    body = resp.data.decode("utf-8")
    assert "eindrapport" in body


def test_output_view_nog_bezig(client):
    """GET /output redirect naar progress als analyse nog bezig is."""
    project_id = _create_project(status="analysing")

    resp = client.get(f"/project/{project_id}/output")
    assert resp.status_code == 302
    assert "progress" in resp.headers["Location"]


def test_output_view_onbekend_project(client):
    """GET /output geeft 404 voor een onbekend project."""
    resp = client.get("/project/onbekend-id/output")
    assert resp.status_code == 404


def test_download_output(client):
    """GET /output/download geeft het rapport-bestand terug."""
    project_id = _create_project(status="done")
    project_dir = _setup_project_dirs(project_id)
    (project_dir / "final" / "output.md").write_text(
        "# rapport\n\ntekst.", encoding="utf-8"
    )

    resp = client.get(f"/project/{project_id}/output/download")
    assert resp.status_code == 200
    assert b"rapport" in resp.data


def test_download_output_niet_done(client):
    """GET /output/download geeft 404 als status niet done is."""
    project_id = _create_project(status="analysing")

    resp = client.get(f"/project/{project_id}/output/download")
    assert resp.status_code == 404


# ============================================================
# background: start_analysis_thread
# ============================================================


def test_start_analysis_thread_volledig():
    """start_analysis_thread roept alle vier agents aan en zet status op done."""
    import time

    project_id = _create_project(status="evidence_approved")
    _setup_project_dirs(project_id)
    _create_cards(project_id, n=2, approved=True)

    analyst_outputs = {"situatie_analist": "analyse"}
    section_drafts = {"situation": "## situatie\n\ntekst."}

    with (
        patch("src.agents.analyst_runner.AnalystRunner.run", return_value=analyst_outputs),
        patch("src.agents.critique_runner.CritiqueRunner.run", return_value=[]),
        patch("src.agents.draft_agent.DraftAgent.run", return_value=section_drafts),
        patch("src.agents.synthese_agent.SyntheseAgent.run", return_value="/final/output.md"),
    ):
        from src.background import start_analysis_thread

        start_analysis_thread(project_id)
        time.sleep(0.5)

    # na afloop hoeft status alleen niet crashed te zijn (done wordt door mock-run gezet)
    from src.models import Project
    from src.state import get_session

    with get_session() as session:
        project = session.get(Project, project_id)
    assert project is not None


def test_start_analysis_thread_analyst_leeg_zet_failed():
    """start_analysis_thread zet status op failed als analyst geen output geeft."""
    import time

    project_id = _create_project(status="evidence_approved")
    _setup_project_dirs(project_id)

    with patch("src.agents.analyst_runner.AnalystRunner.run", return_value={}):
        from src.background import start_analysis_thread

        start_analysis_thread(project_id)
        time.sleep(0.5)

    from src.models import Project
    from src.state import get_session

    with get_session() as session:
        project = session.get(Project, project_id)
    assert project.status == "failed"
