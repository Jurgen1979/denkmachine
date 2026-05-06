"""integratietests voor de plan-routes."""

import json
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

_BASE_DIR = Path(__file__).parent.parent
_PROJECTS_DIR = _BASE_DIR / "projects"

_SAMPLE_PLAN = {
    "primary_category": "diagnose",
    "secondary_category": None,
    "category_confidence": 0.9,
    "interpreted_goal": "testdoel",
    "scope": "testscope",
    "scope_clarity_score": 0.85,
    "assumptions": ["aanname 1"],
    "missing_inputs": [],
    "clarifying_questions": ["wat is de scope?"],
    "active_role_pack": {
        "analyst_roles": ["situatie_analist"],
        "critique_roles": ["bewijs_vrager"],
    },
    "research_plan": {
        "interview_questions": ["vraag 1"],
        "sources_to_research": [
            {"type": "topic", "value": "markt", "rationale": "referentie"},
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
    return project_id


def _write_plan_json(project_id: str, plan: dict) -> None:
    """Schrijf plan.json naar de projectmap."""
    plan_path = _PROJECTS_DIR / project_id / "plan.json"
    plan_path.parent.mkdir(parents=True, exist_ok=True)
    plan_path.write_text(json.dumps(plan), encoding="utf-8")


@pytest.mark.parametrize(
    "status,needs_plan,expected_text",
    [
        ("created", False, "ontleder werkt"),
        ("classifying", False, "ontleder werkt"),
        ("awaiting_clarification", True, "aanvullende vragen"),
        ("plan_review", True, "plan goedkeuren"),
        ("plan_approved", True, "plan bevroren"),
    ],
)
def test_plan_page_renders_for_each_status(
    logged_in_client, status, needs_plan, expected_text
):
    """Controleer dat /project/<id>/plan 200 teruggeeft voor elk geldig status."""
    project_id = _create_project(status)
    if needs_plan:
        _write_plan_json(project_id, _SAMPLE_PLAN)

    response = logged_in_client.get(f"/project/{project_id}/plan")
    assert response.status_code == 200
    assert expected_text in response.data.decode("utf-8")


def test_post_answers_triggers_intake(logged_in_client):
    """Controleer dat POST /plan/answers de intake-agent aanroept en redirect geeft."""
    from src.schemas.plan import IntakePlan

    project_id = _create_project("awaiting_clarification")
    _write_plan_json(project_id, _SAMPLE_PLAN)

    frozen_plan_data = {**_SAMPLE_PLAN, "frozen": True, "clarifying_questions": []}
    mock_intake_plan = IntakePlan.model_validate(frozen_plan_data)

    with patch("src.routes.plan.IntakeAgent.run", return_value=mock_intake_plan):
        response = logged_in_client.post(
            f"/project/{project_id}/plan/answers",
            data={"answer_0": "kmo's in de bouwsector"},
        )

    assert response.status_code == 302
