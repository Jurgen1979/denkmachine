"""unit-tests voor de intake-agent (zonder echte api-call)."""

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

_BASE_DIR = Path(__file__).parent.parent
_PROJECTS_DIR = _BASE_DIR / "projects"

_PREVIOUS_PLAN = {
    "primary_category": "haalbaarheid",
    "secondary_category": None,
    "category_confidence": 0.6,
    "interpreted_goal": "beoordeel haalbaarheid van nieuwe saas",
    "scope": "initieel, te verfijnen",
    "scope_clarity_score": 0.55,
    "assumptions": ["aanname 1"],
    "missing_inputs": ["doelgroep ontbreekt"],
    "clarifying_questions": ["wie is de primaire doelgroep?"],
    "active_role_pack": {
        "analyst_roles": ["commerciele_realist"],
        "critique_roles": ["optimisme_doorprikker"],
    },
    "research_plan": {
        "interview_questions": ["vraag 1"],
        "sources_to_research": [
            {"type": "topic", "value": "saas markt", "rationale": "referentie"},
        ],
        "frameworks_to_apply": ["lean canvas"],
        "report_sections": [
            {
                "id": "context",
                "title": "context en aannames",
                "purpose": "vertrekpunt",
                "estimated_length_words": 400,
            }
        ],
    },
    "output_type": "feasibility_study",
    "estimated_runtime_minutes": 60,
    "estimated_cost_eur": 18.0,
}


def _chat_response(content: str) -> dict:
    """Maak een nep-llm-response."""
    return {
        "content": content,
        "input_tokens": 150,
        "output_tokens": 80,
        "cost_eur": 0.015,
        "model_used": "test/model",
        "duration_ms": 300,
    }


def _create_project_with_plan(status: str) -> str:
    """Maak een testproject aan met plan.json in de projectmap."""
    from src.models import Project
    from src.state import get_session

    project_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    project = Project(
        id=project_id,
        created_at=now,
        updated_at=now,
        user_question="is een nieuwe saas haalbaar",
        status=status,
    )
    with get_session() as session:
        session.add(project)
        session.commit()

    plan_path = _PROJECTS_DIR / project_id / "plan.json"
    plan_path.parent.mkdir(parents=True, exist_ok=True)
    plan_path.write_text(json.dumps(_PREVIOUS_PLAN), encoding="utf-8")

    return project_id


def test_intake_with_answers_freezes_plan():
    """Controleer dat frozen=true leidt tot status plan_approved."""
    from src.agents.intake import IntakeAgent
    from src.llm_client import LLMClient
    from src.models import Project
    from src.state import get_session

    frozen_plan = {**_PREVIOUS_PLAN, "frozen": True, "category_confidence": 0.85,
                   "scope_clarity_score": 0.80, "clarifying_questions": []}

    project_id = _create_project_with_plan("awaiting_clarification")
    client = LLMClient()

    with patch.object(
        LLMClient, "chat", return_value=_chat_response(json.dumps(frozen_plan))
    ):
        agent = IntakeAgent(client, project_id)
        result = agent.run(
            previous_plan=_PREVIOUS_PLAN,
            user_answers={"answer_0": "kmo's in de bouwsector"},
        )

    assert result.frozen is True

    with get_session() as session:
        project = session.get(Project, project_id)
        assert project.status == "plan_approved"


def test_intake_still_uncertain_returns_new_questions():
    """Controleer dat frozen=false leidt tot status awaiting_clarification met nieuwe vragen."""
    from src.agents.intake import IntakeAgent
    from src.llm_client import LLMClient
    from src.models import Project
    from src.state import get_session

    uncertain_plan = {
        **_PREVIOUS_PLAN,
        "frozen": False,
        "category_confidence": 0.6,
        "scope_clarity_score": 0.55,
        "clarifying_questions": ["wat is het budget?"],
    }

    project_id = _create_project_with_plan("awaiting_clarification")
    client = LLMClient()

    with patch.object(
        LLMClient, "chat", return_value=_chat_response(json.dumps(uncertain_plan))
    ):
        agent = IntakeAgent(client, project_id)
        result = agent.run(
            previous_plan=_PREVIOUS_PLAN,
            user_answers={"answer_0": "onduidelijk"},
        )

    assert result.frozen is False
    assert len(result.clarifying_questions) > 0

    with get_session() as session:
        project = session.get(Project, project_id)
        assert project.status == "awaiting_clarification"
