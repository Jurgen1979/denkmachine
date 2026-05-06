"""project-routes: aanmaken van nieuwe projecten en openrouter-ping."""

import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from flask import Blueprint, jsonify, redirect, render_template, request, url_for
from flask_login import login_required
from loguru import logger

from src.models import Project
from src.state import get_session

_BASE_DIR = Path(__file__).parent.parent.parent
_PROJECTS_DIR = _BASE_DIR / "projects"

projects_bp = Blueprint("projects", __name__)


@projects_bp.route("/new", methods=["GET", "POST"])
@login_required
def new_project():
    """Toon het formulier voor een nieuw project of verwerk de aanvraag."""
    if request.method == "POST":
        user_question = request.form.get("user_question", "").strip()
        client_name = request.form.get("client_name", "").strip() or None

        if not user_question:
            return render_template("new_project.html", error="vul een vraag in"), 400

        project_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()

        # maak project-folder aan met lege subfolders
        project_dir = _PROJECTS_DIR / project_id
        for subfolder in ("inputs", "evidence", "drafts", "final"):
            (project_dir / subfolder).mkdir(parents=True, exist_ok=True)

        project = Project(
            id=project_id,
            created_at=now,
            updated_at=now,
            user_question=user_question,
            status="created",
            client_name=client_name,
        )

        with get_session() as session:
            session.add(project)
            session.commit()

        logger.info(f"nieuw project aangemaakt: id={project_id} status=created")
        return redirect(url_for("dashboard.index"))

    return render_template("new_project.html")


@projects_bp.route("/ping-openrouter")
@login_required
def ping_openrouter():
    """Test de verbinding met openrouter en geef de latentie terug."""
    from src.llm_client import LLMClient

    start = time.time()
    try:
        client = LLMClient()
        result = client.chat(
            profile="reasoning_model",
            messages=[{"role": "user", "content": "zeg alleen 'ok'"}],
            max_tokens=5,
            project_id="ping",
            agent_name="ping",
        )
        latency_ms = int((time.time() - start) * 1000)
        logger.info(
            f"openrouter-ping geslaagd: model={result['model_used']} latency_ms={latency_ms}"
        )
        return jsonify({"ok": True, "model": result["model_used"], "latency_ms": latency_ms})
    except Exception as exc:
        latency_ms = int((time.time() - start) * 1000)
        logger.error(f"openrouter-ping mislukt: {exc}")
        return jsonify({"ok": False, "error": str(exc)}), 500
