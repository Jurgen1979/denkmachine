"""output-routes: starten van de analyse en bekijken van het eindrapport."""

from pathlib import Path

from flask import Blueprint, abort, redirect, render_template, url_for
from flask_login import login_required

from src.models import Flag, Project
from src.state import get_session

_BASE_DIR = Path(__file__).parent.parent.parent
_PROJECTS_DIR = _BASE_DIR / "projects"

output_bp = Blueprint("output", __name__)

_ANALYSIS_STATUSES = {
    "analysing", "drafting", "synthesising", "done", "failed",
}


def _get_project_or_abort(project_id: str) -> Project:
    """Haal project op of geef 404."""
    with get_session() as session:
        project = session.get(Project, project_id)
    if project is None:
        abort(404)
    return project


@output_bp.route("/project/<project_id>/analyse/start", methods=["POST"])
@login_required
def analyse_start(project_id: str):
    """Start de analyse-pipeline als de status evidence_approved is."""
    from datetime import datetime, timezone

    from src.background import start_analysis_thread

    with get_session() as session:
        project = session.get(Project, project_id)
        if project is None:
            abort(404)
        if project.status not in ("evidence_approved",):
            return redirect(url_for("evidence.evidence_view", project_id=project_id))
        now = datetime.now(timezone.utc).isoformat()
        project.status = "analysing"
        project.updated_at = now
        session.commit()

    start_analysis_thread(project_id)
    return redirect(url_for("progress.progress_view", project_id=project_id))


@output_bp.route("/project/<project_id>/output")
@login_required
def output_view(project_id: str):
    """Toon het eindrapport en actieplan als de pipeline klaar is."""
    project = _get_project_or_abort(project_id)

    if project.status not in _ANALYSIS_STATUSES:
        return redirect(url_for("evidence.evidence_view", project_id=project_id))

    if project.status in ("analysing", "drafting", "synthesising"):
        return redirect(url_for("progress.progress_view", project_id=project_id))

    final_dir = _PROJECTS_DIR / project_id / "final"
    output_md = final_dir / "output.md"
    action_plan_md = final_dir / "action_plan.md"

    output_content = (
        output_md.read_text(encoding="utf-8") if output_md.exists() else None
    )
    action_plan_content = (
        action_plan_md.read_text(encoding="utf-8") if action_plan_md.exists() else None
    )

    with get_session() as session:
        flags = (
            session.query(Flag)
            .filter(Flag.project_id == project_id, Flag.resolved == False)  # noqa: E712
            .order_by(Flag.id.desc())
            .all()
        )

    return render_template(
        "output.html",
        project=project,
        output_content=output_content,
        action_plan_content=action_plan_content,
        flags=flags,
    )


@output_bp.route("/project/<project_id>/output/download")
@login_required
def download_output(project_id: str):
    """Download output.md als bestand."""
    from flask import send_file

    project = _get_project_or_abort(project_id)
    if project.status != "done":
        abort(404)

    output_path = _PROJECTS_DIR / project_id / "final" / "output.md"
    if not output_path.exists():
        abort(404)

    return send_file(
        output_path,
        as_attachment=True,
        download_name=f"rapport_{project_id[:8]}.md",
        mimetype="text/markdown",
    )
