"""unit-tests voor de ontleder-agent (zonder echte api-call)."""

import json
import os
import uuid
from datetime import datetime, timezone
from unittest.mock import patch

import pytest

os.environ.setdefault("DM_USER", "testuser")
os.environ.setdefault("DM_SECRET_KEY", "test-secret-key")
os.environ.setdefault("DM_PASSWORD_HASH", "")
os.environ.setdefault("OPENROUTER_API_KEY", "test-key")


_VALID_PLAN = {
    "primary_category": "diagnose",
    "secondary_category": None,
    "category_confidence": 0.9,
    "interpreted_goal": "testdoel voor diagnose",
    "scope": "testscope voor diagnose",
    "scope_clarity_score": 0.85,
    "assumptions": ["aanname 1"],
    "missing_inputs": [],
    "clarifying_questions": [],
    "active_role_pack": {
        "analyst_roles": ["situatie_analist"],
        "critique_roles": ["bewijs_vrager"],
    },
    "research_plan": {
        "interview_questions": ["vraag 1"],
        "sources_to_research": [
            {"type": "topic", "value": "marktpositie", "rationale": "referentie"},
        ],
        "frameworks_to_apply": ["swot"],
        "report_sections": [
            {
                "id": "situatie",
                "title": "huidige situatie",
                "purpose": "vertrekpunt",
                "estimated_length_words": 300,
            }
        ],
    },
    "output_type": "diagnose_report",
    "estimated_runtime_minutes": 45,
    "estimated_cost_eur": 12.50,
}


def _chat_response(content: str) -> dict:
    """Maak een nep-llm-response met de gegeven tekst als content."""
    return {
        "content": content,
        "input_tokens": 100,
        "output_tokens": 50,
        "cost_eur": 0.01,
        "model_used": "test/model",
        "duration_ms": 200,
    }


def _create_project(status: str = "created") -> str:
    """Maak een testproject aan in de db en geef het id terug."""
    from src.models import Project
    from src.state import get_session

    project_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    project = Project(
        id=project_id,
        created_at=now,
        updated_at=now,
        user_question="wat zijn de zwaktes in ons huidige proces",
        status=status,
    )
    with get_session() as session:
        session.add(project)
        session.commit()
    return project_id


def test_prompt_renders_correctly():
    """Controleer dat de ontleder-prompt correct rendert zonder resterende placeholders."""
    from src.prompts import load_prompt, render_prompt

    template = load_prompt("ontleder")
    rendered = render_prompt(template, {
        "user_question": "testproject",
        "user_context": "geen extra context",
        "category_hint": "diagnose",
        "role_packs": "diagnose:\n  analyst_roles: a\n  critique_roles: b",
        "available_output_types": "diagnose_report, prd",
    })
    assert "{{" not in rendered
    assert "}}" not in rendered
    assert "testproject" in rendered


def test_run_with_mocked_llm_returns_valid_plan():
    """Controleer dat run() een geldig Plan teruggeeft bij correcte llm-response."""
    from src.agents.ontleder import OntlederAgent
    from src.llm_client import LLMClient
    from src.schemas.plan import Plan

    project_id = _create_project()
    client = LLMClient()

    with patch.object(LLMClient, "chat", return_value=_chat_response(json.dumps(_VALID_PLAN))):
        agent = OntlederAgent(client, project_id)
        result = agent.run(user_question="wat zijn de zwaktes in ons huidige proces")

    assert isinstance(result, Plan)
    assert result.primary_category == "diagnose"
    assert result.output_type == "diagnose_report"


def test_run_low_confidence_triggers_clarifying():
    """Controleer dat lage confidence leidt tot awaiting_clarification en vragen."""
    from src.agents.ontleder import OntlederAgent
    from src.llm_client import LLMClient
    from src.models import Project
    from src.state import get_session

    low_confidence_plan = {
        **_VALID_PLAN,
        "category_confidence": 0.5,
        "scope_clarity_score": 0.6,
        "clarifying_questions": ["wat is de scope precies?"],
    }

    project_id = _create_project()
    client = LLMClient()

    with patch.object(
        LLMClient, "chat", return_value=_chat_response(json.dumps(low_confidence_plan))
    ):
        agent = OntlederAgent(client, project_id)
        result = agent.run(user_question="iets vaags")

    assert len(result.clarifying_questions) > 0

    with get_session() as session:
        project = session.get(Project, project_id)
        assert project.status == "awaiting_clarification"


def test_run_high_cost_creates_flag():
    """Controleer dat een hoge kostenschatting een cost_estimate_high-vlag aanmaakt."""
    from src.agents.ontleder import OntlederAgent
    from src.llm_client import LLMClient
    from src.models import Flag
    from src.state import get_session

    high_cost_plan = {**_VALID_PLAN, "estimated_cost_eur": 35.0}

    project_id = _create_project()
    client = LLMClient()

    with patch.object(
        LLMClient, "chat", return_value=_chat_response(json.dumps(high_cost_plan))
    ):
        agent = OntlederAgent(client, project_id)
        agent.run(user_question="een enorm complex vraagstuk met veel dimensies")

    with get_session() as session:
        flags = (
            session.query(Flag)
            .filter(
                Flag.project_id == project_id,
                Flag.type == "cost_estimate_high",
            )
            .all()
        )
    assert len(flags) >= 1
    assert flags[0].severity == "high"


def test_invalid_json_retries_then_fails():
    """Controleer dat OntlederFailure wordt gegooid na twee invalide json-responses."""
    from src.agents.ontleder import OntlederAgent, OntlederFailure
    from src.llm_client import LLMClient

    project_id = _create_project()
    client = LLMClient()

    with patch.object(
        LLMClient, "chat", return_value=_chat_response("dit is geen valide json {{{")
    ):
        agent = OntlederAgent(client, project_id)
        with pytest.raises(OntlederFailure):
            agent.run(user_question="testproject")
