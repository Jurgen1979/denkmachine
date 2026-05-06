"""progress-routes: live voortgang van de ingest-pipeline."""

from pathlib import Path

from flask import Blueprint, abort, redirect, render_template, url_for
from flask_login import login_required

from src.models import AgentCall, Flag, Project
from src.state import get_session

_BASE_DIR = Path(__file__).parent.parent.parent
_PROJECTS_DIR = _BASE_DIR / "projects"

progress_bp = Blueprint("progress", __name__)


def _count_sources(project_id: str) -> tuple[int, int]:
    """Geef (verwerkt, totaal) terug op basis van inputs en ingested-map.

    totaal = aantal documenten + aantal urls
    verwerkt = aantal src_xxx_*.md bestanden in ingested/
    """
    project_dir = _PROJECTS_DIR / project_id

    docs_dir = project_dir / "inputs" / "documents"
    doc_count = len(list(docs_dir.iterdir())) if docs_dir.exists() else 0

    urls_file = project_dir / "inputs" / "urls.txt"
    url_count = 0
    if urls_file.exists():
        url_count = len(
            [u for u in urls_file.read_text(encoding="utf-8").splitlines() if u.strip()]
        )

    total = doc_count + url_count

    ingested_dir = project_dir / "ingested"
    done = 0
    if ingested_dir.exists():
        done = len(
            [
                f
                for f in ingested_dir.iterdir()
                if f.name.startswith("src_") and f.suffix == ".md"
            ]
        )

    return done, total


def _load_recent_calls(project_id: str, limit: int = 20) -> list:
    """Laad de laatste agent_calls voor dit project."""
    with get_session() as session:
        calls = (
            session.query(AgentCall)
            .filter(AgentCall.project_id == project_id)
            .order_by(AgentCall.id.desc())
            .limit(limit)
            .all()
        )
        return list(reversed(calls))


def _load_flags(project_id: str) -> list:
    """Laad alle vlaggen voor dit project."""
    with get_session() as session:
        flags = (
            session.query(Flag)
            .filter(Flag.project_id == project_id)
            .order_by(Flag.id.desc())
            .all()
        )
        return list(flags)


@progress_bp.route("/project/<project_id>/progress")
@login_required
def progress_view(project_id: str):
    """Toon de voortgangspagina met htmx-polling."""
    with get_session() as session:
        project = session.get(Project, project_id)

    if project is None:
        abort(404)

    done, total = _count_sources(project_id)
    pct = int((done / total) * 100) if total > 0 else 0

    return render_template(
        "progress.html",
        project=project,
        done=done,
        total=total,
        pct=pct,
    )


@progress_bp.route("/project/<project_id>/progress/restart", methods=["POST"])
@login_required
def progress_restart(project_id: str):
    """Herstart de pipeline of alleen de bewijs-extractie voor dit project."""
    from datetime import datetime, timezone

    from src.background import start_extraction_thread, start_pipeline_thread

    with get_session() as session:
        project = session.get(Project, project_id)
        if project is None:
            abort(404)
        status = project.status
        now = datetime.now(timezone.utc).isoformat()

        # controleer of ingested-bestanden beschikbaar zijn
        ingested_dir = _PROJECTS_DIR / project_id / "ingested"
        has_ingested = ingested_dir.exists() and any(
            f for f in ingested_dir.glob("src_*.md")
        )

        if status in ("extracting_evidence", "ingested") and has_ingested:
            # ingest is al klaar, alleen extractie herstarten
            project.status = "ingested"
            project.updated_at = now
            session.commit()
            start_extraction_thread(project_id)
        elif status in ("ingesting", "failed") or (
            status in ("extracting_evidence", "ingested") and not has_ingested
        ):
            # volledige pipeline herstarten (ook als ingested-bestanden ontbreken)
            project.status = "plan_approved"
            project.updated_at = now
            session.commit()
            start_pipeline_thread(project_id)

    return redirect(url_for("progress.progress_view", project_id=project_id))


@progress_bp.route("/project/<project_id>/progress/fragment")
@login_required
def progress_fragment(project_id: str):
    """Geef het htmx-fragment terug met status en log-entries."""
    with get_session() as session:
        project = session.get(Project, project_id)

    if project is None:
        abort(404)

    done, total = _count_sources(project_id)
    pct = int((done / total) * 100) if total > 0 else 0
    calls = _load_recent_calls(project_id)
    flags = _load_flags(project_id)

    return render_template(
        "progress_fragment.html",
        project=project,
        done=done,
        total=total,
        pct=pct,
        calls=calls,
        flags=flags,
    )
