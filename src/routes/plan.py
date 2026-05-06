"""plan-routes: weergave en beheer van het plan per project."""

import json
from datetime import datetime, timezone
from pathlib import Path

from flask import Blueprint, abort, redirect, render_template, request, url_for
from flask_login import login_required
from loguru import logger

from src.agents.intake import IntakeAgent
from src.llm_client import LLMClient
from src.models import Flag, Project
from src.state import get_session
from src.utils import get_cost_caps

_BASE_DIR = Path(__file__).parent.parent.parent
_PROJECTS_DIR = _BASE_DIR / "projects"

plan_bp = Blueprint("plan", __name__)


def _load_plan_json(project_id: str) -> dict | None:
    """Laad plan.json voor het gegeven project. Geeft None als het bestand ontbreekt."""
    plan_path = _PROJECTS_DIR / project_id / "plan.json"
    if not plan_path.exists():
        return None
    return json.loads(plan_path.read_text(encoding="utf-8"))


def _has_cost_flag(project_id: str) -> bool:
    """Controleer of er een onopgeloste cost_estimate_high-vlag bestaat."""
    with get_session() as session:
        flag = (
            session.query(Flag)
            .filter(
                Flag.project_id == project_id,
                Flag.type == "cost_estimate_high",
                Flag.resolved == False,  # noqa: E712
            )
            .first()
        )
    return flag is not None


_PIPELINE_STATUSES = {
    "ingesting", "ingested", "extracting_evidence",
    "awaiting_evidence_review", "evidence_approved", "failed",
}


@plan_bp.route("/project/<project_id>/plan")
@login_required
def plan_view(project_id: str):
    """Toon het plan voor het gegeven project op basis van de huidige status."""
    with get_session() as session:
        project = session.get(Project, project_id)

    if project is None:
        abort(404)

    # stuur door naar de juiste pagina als de pipeline al gestart is
    if project.status in {"awaiting_evidence_review", "evidence_approved"}:
        return redirect(url_for("evidence.evidence_view", project_id=project_id))
    if project.status in {"ingesting", "ingested", "extracting_evidence", "failed"}:
        return redirect(url_for("progress.progress_view", project_id=project_id))

    plan = _load_plan_json(project_id)
    hard_cap, alert_at = get_cost_caps()
    has_cost_warning = _has_cost_flag(project_id)

    return render_template(
        "plan.html",
        project=project,
        plan=plan,
        has_cost_warning=has_cost_warning,
        hard_cap=hard_cap,
        alert_at=alert_at,
    )


@plan_bp.route("/project/<project_id>/plan/answers", methods=["POST"])
@login_required
def plan_answers(project_id: str):
    """Verwerk antwoorden op clarifying questions via de intake-agent."""
    with get_session() as session:
        project = session.get(Project, project_id)

    if project is None:
        abort(404)

    if project.status != "awaiting_clarification":
        abort(409)

    previous_plan = _load_plan_json(project_id)
    if previous_plan is None:
        abort(400)

    user_answers: dict[str, str] = {}
    for key, value in request.form.items():
        if key.startswith("answer_"):
            user_answers[key] = value.strip()

    agent = IntakeAgent(LLMClient(), project_id)
    try:
        agent.run(previous_plan=previous_plan, user_answers=user_answers)
    except Exception as exc:
        logger.error(
            f"intake mislukt: project={project_id} fout={exc}", exc_info=True
        )
        abort(500)

    return redirect(url_for("plan.plan_view", project_id=project_id))


@plan_bp.route("/project/<project_id>/plan/approve", methods=["POST"])
@login_required
def plan_approve(project_id: str):
    """Keur het plan goed en zet de status op plan_approved."""
    with get_session() as session:
        project = session.get(Project, project_id)

    if project is None:
        abort(404)

    if project.status != "plan_review":
        abort(409)

    plan = _load_plan_json(project_id)
    now = datetime.now(timezone.utc).isoformat()

    with get_session() as session:
        project = session.get(Project, project_id)
        project.status = "plan_approved"
        project.updated_at = now
        session.commit()

    if plan is not None:
        plan["frozen"] = True
        plan_path = _PROJECTS_DIR / project_id / "plan.json"
        plan_path.write_text(
            json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    logger.info(f"plan goedgekeurd: project={project_id}")
    return redirect(url_for("plan.plan_view", project_id=project_id))


@plan_bp.route("/project/<project_id>/plan/revise", methods=["POST"])
@login_required
def plan_revise(project_id: str):
    """Zet de status terug op awaiting_clarification voor herziening van het plan."""
    with get_session() as session:
        project = session.get(Project, project_id)

    if project is None:
        abort(404)

    if project.status != "plan_review":
        abort(409)

    now = datetime.now(timezone.utc).isoformat()
    with get_session() as session:
        project = session.get(Project, project_id)
        project.status = "awaiting_clarification"
        project.updated_at = now
        session.commit()

    logger.info(f"plan revisie aangevraagd: project={project_id}")
    return redirect(url_for("plan.plan_view", project_id=project_id))
