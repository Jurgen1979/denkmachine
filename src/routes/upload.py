"""upload-routes: bestanden en urls opladen, pipeline starten."""

import json
from pathlib import Path

from flask import (
    Blueprint,
    abort,
    flash,
    redirect,
    render_template,
    request,
    url_for,
)
from flask_login import login_required
from loguru import logger
from werkzeug.utils import secure_filename

from src.background import start_pipeline_thread
from src.models import Project
from src.state import get_session

_BASE_DIR = Path(__file__).parent.parent.parent
_PROJECTS_DIR = _BASE_DIR / "projects"

_ALLOWED_EXTENSIONS = {".pdf", ".docx", ".txt", ".md"}
_MAX_FILE_BYTES = 50 * 1024 * 1024  # 50 MB

upload_bp = Blueprint("upload", __name__)


def _load_plan_json(project_id: str) -> dict | None:
    """Laad plan.json voor het gegeven project."""
    plan_path = _PROJECTS_DIR / project_id / "plan.json"
    if not plan_path.exists():
        return None
    return json.loads(plan_path.read_text(encoding="utf-8"))


def _list_documents(project_id: str) -> list[str]:
    """Geef gesorteerde lijst van bestandsnamen in inputs/documents/."""
    docs_dir = _PROJECTS_DIR / project_id / "inputs" / "documents"
    if not docs_dir.exists():
        return []
    return sorted(p.name for p in docs_dir.iterdir() if p.is_file())


def _list_urls(project_id: str) -> list[str]:
    """Geef lijst van urls uit inputs/urls.txt."""
    urls_file = _PROJECTS_DIR / project_id / "inputs" / "urls.txt"
    if not urls_file.exists():
        return []
    return [u.strip() for u in urls_file.read_text(encoding="utf-8").splitlines() if u.strip()]


@upload_bp.route("/project/<project_id>/upload", methods=["GET"])
@login_required
def upload_view(project_id: str):
    """Toon het upload-formulier voor documenten en urls."""
    with get_session() as session:
        project = session.get(Project, project_id)

    if project is None:
        abort(404)

    if project.status not in ("plan_approved", "ingesting", "ingested"):
        abort(409)

    plan = _load_plan_json(project_id)
    sources_hint: list = []
    if plan and plan.get("research_plan", {}).get("sources_to_research"):
        sources_hint = plan["research_plan"]["sources_to_research"]

    documents = _list_documents(project_id)
    urls = _list_urls(project_id)

    return render_template(
        "upload.html",
        project=project,
        sources_hint=sources_hint,
        documents=documents,
        urls=urls,
    )


@upload_bp.route("/project/<project_id>/upload/files", methods=["POST"])
@login_required
def upload_files(project_id: str):
    """Sla geüploade bestanden op in inputs/documents/."""
    with get_session() as session:
        project = session.get(Project, project_id)

    if project is None:
        abort(404)

    if project.status != "plan_approved":
        abort(409)

    files = request.files.getlist("documents")
    docs_dir = _PROJECTS_DIR / project_id / "inputs" / "documents"
    docs_dir.mkdir(parents=True, exist_ok=True)

    for file in files:
        if not file or not file.filename:
            continue

        filename = secure_filename(file.filename)
        ext = Path(filename).suffix.lower()

        if ext not in _ALLOWED_EXTENSIONS:
            return (
                f"bestandstype niet toegestaan: {ext}. toegestaan: "
                + ", ".join(_ALLOWED_EXTENSIONS),
                400,
            )

        content = file.read()
        if len(content) > _MAX_FILE_BYTES:
            return f"bestand {filename} is groter dan 50 MB", 413

        (docs_dir / filename).write_bytes(content)
        logger.info(
            f"bestand opgeslagen: project={project_id} file={filename} "
            f"bytes={len(content)}"
        )

    return redirect(url_for("upload.upload_view", project_id=project_id))


@upload_bp.route("/project/<project_id>/upload/urls", methods=["POST"])
@login_required
def upload_urls(project_id: str):
    """Sla urls op in inputs/urls.txt."""
    with get_session() as session:
        project = session.get(Project, project_id)

    if project is None:
        abort(404)

    if project.status != "plan_approved":
        abort(409)

    raw = request.form.get("urls", "")
    validated: list[str] = []
    invalid: list[str] = []
    for line in raw.splitlines():
        url = line.strip()
        if not url:
            continue
        if url.startswith("http://") or url.startswith("https://"):
            validated.append(url)
        else:
            invalid.append(url)

    if invalid:
        flash(f"ongeldige urls overgeslagen: {', '.join(invalid)}")

    urls_file = _PROJECTS_DIR / project_id / "inputs" / "urls.txt"
    urls_file.parent.mkdir(parents=True, exist_ok=True)
    urls_file.write_text("\n".join(validated), encoding="utf-8")
    logger.info(f"urls opgeslagen: project={project_id} aantal={len(validated)}")

    return redirect(url_for("upload.upload_view", project_id=project_id))


@upload_bp.route("/project/<project_id>/upload/start", methods=["POST"])
@login_required
def upload_start(project_id: str):
    """Start de ingest-pipeline als achtergrond-thread."""
    with get_session() as session:
        project = session.get(Project, project_id)

    if project is None:
        abort(404)

    if project.status != "plan_approved":
        abort(409)

    documents = _list_documents(project_id)
    urls = _list_urls(project_id)

    if not documents and not urls:
        flash("geen input: upload minstens één document of url")
        return redirect(url_for("upload.upload_view", project_id=project_id))

    from datetime import datetime, timezone

    now = datetime.now(timezone.utc).isoformat()
    with get_session() as session:
        project = session.get(Project, project_id)
        project.status = "ingesting"
        project.updated_at = now
        session.commit()

    logger.info(f"ingest gestart: project={project_id}")

    start_pipeline_thread(project_id)

    return redirect(url_for("progress.progress_view", project_id=project_id))
