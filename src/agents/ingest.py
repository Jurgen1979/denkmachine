"""ingest-agent: verwerkt documenten en urls naar markdown-bronnen plus een bundel."""

import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from loguru import logger

from src.agents.base import Agent
from src.models import AgentCall, Flag, Project
from src.parsing import ParsingFailure, parse_document
from src.prompts import load_prompt, render_prompt
from src.scraping import ScrapingFailure, scrape_url
from src.state import get_session

_BASE_DIR = Path(__file__).parent.parent.parent
_PROJECTS_DIR = _BASE_DIR / "projects"


def _make_slug(name: str) -> str:
    """Zet een bestandsnaam of url-pad om naar een veilige slug (max 40 tekens)."""
    name = name.lower()
    name = re.sub(r"[^a-z0-9]+", "_", name)
    name = re.sub(r"_+", "_", name)
    name = name.strip("_")
    return name[:40]


def _load_plan_json(project_id: str) -> dict | None:
    """Laad plan.json voor het gegeven project. Geeft None als het bestand ontbreekt."""
    plan_path = _PROJECTS_DIR / project_id / "plan.json"
    if not plan_path.exists():
        return None
    return json.loads(plan_path.read_text(encoding="utf-8"))


class IngestAgent(Agent):
    """Verwerkt documenten en urls naar markdown-bronnen en genereert een bundel."""

    agent_name = "ingest"

    def _write_source_record(
        self,
        source_id: str,
        model_used: str,
        status: str,
        duration_ms: int,
        error_message: str | None = None,
    ) -> None:
        """Schrijf een agent_calls-record voor een bron-verwerkingsstap."""
        record = AgentCall(
            project_id=self.project_id,
            agent_name=self.agent_name,
            role_name=source_id,
            model_used=model_used,
            profile=None,
            input_tokens=None,
            output_tokens=None,
            cost_eur=None,
            duration_ms=duration_ms,
            status=status,
            error_message=error_message,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )
        with get_session() as session:
            session.add(record)
            session.commit()

    def _set_status(self, status: str) -> None:
        """Zet de projectstatus in de database."""
        now = datetime.now(timezone.utc).isoformat()
        with get_session() as session:
            project = session.get(Project, self.project_id)
            if project is not None:
                project.status = status
                project.updated_at = now
                session.commit()
        logger.info(f"project status bijgewerkt: project={self.project_id} status={status}")

    def _add_flag(self, flag_type: str, severity: str, description: str) -> None:
        """Voeg een vlag toe aan het project."""
        flag = Flag(
            project_id=self.project_id,
            type=flag_type,
            severity=severity,
            description=description,
            resolved=False,
            created_at=datetime.now(timezone.utc).isoformat(),
        )
        with get_session() as session:
            session.add(flag)
            session.commit()

    def run(self) -> None:
        """Verwerk alle bronnen en genereer de bundel."""
        project_dir = _PROJECTS_DIR / self.project_id
        ingested_dir = project_dir / "ingested"
        ingested_dir.mkdir(parents=True, exist_ok=True)

        plan = _load_plan_json(self.project_id)
        if plan and plan.get("research_plan"):
            research_plan_text = json.dumps(plan["research_plan"], ensure_ascii=False)
        else:
            research_plan_text = ""

        # verzamel documenten (alfabetisch)
        docs_dir = project_dir / "inputs" / "documents"
        documents: list[Path] = sorted(docs_dir.glob("*")) if docs_dir.exists() else []

        # verzamel urls
        urls_file = project_dir / "inputs" / "urls.txt"
        urls: list[str] = []
        if urls_file.exists():
            lines = urls_file.read_text(encoding="utf-8").splitlines()
            urls = [u.strip() for u in lines if u.strip()]

        if not documents and not urls:
            logger.error(f"geen bronnen voor project={self.project_id}")
            self._set_status("failed")
            self._add_flag("ingest_failed", "high", "geen bronnen aanwezig om te verwerken")
            return

        counter = 1
        successful_sources: list[tuple[str, str]] = []

        # verwerk documenten
        for doc_path in documents:
            source_id = f"src_{counter:03d}"
            slug = _make_slug(doc_path.stem)
            out_name = f"{source_id}_{slug}.md"
            start = time.time()
            try:
                markdown = parse_document(doc_path, source_id)
                (ingested_dir / out_name).write_text(markdown, encoding="utf-8")
                duration_ms = int((time.time() - start) * 1000)
                self._write_source_record(source_id, "local", "ok", duration_ms)
                logger.info(
                    f"ingest document klaar: project={self.project_id} "
                    f"source={source_id} file={doc_path.name}"
                )
                successful_sources.append((source_id, markdown))
            except (ParsingFailure, Exception) as e:
                duration_ms = int((time.time() - start) * 1000)
                self._write_source_record(source_id, "local", "error", duration_ms, str(e))
                logger.error(
                    f"ingest document mislukt: project={self.project_id} "
                    f"source={source_id} file={doc_path.name} fout={e}"
                )
                self._add_flag(
                    "ingest_source_failed",
                    "medium",
                    f"source {source_id} ({doc_path.name}) mislukt: {e}",
                )
            counter += 1

        # verwerk urls
        for url in urls:
            source_id = f"src_{counter:03d}"
            parsed = urlparse(url)
            netloc_path = parsed.netloc + parsed.path
            slug = _make_slug(netloc_path)
            out_name = f"{source_id}_{slug}.md"
            start = time.time()
            try:
                markdown = scrape_url(url, source_id)
                (ingested_dir / out_name).write_text(markdown, encoding="utf-8")
                duration_ms = int((time.time() - start) * 1000)
                self._write_source_record(source_id, "firecrawl", "ok", duration_ms)
                logger.info(
                    f"ingest url klaar: project={self.project_id} "
                    f"source={source_id} url={url}"
                )
                successful_sources.append((source_id, markdown))
            except (ScrapingFailure, Exception) as e:
                duration_ms = int((time.time() - start) * 1000)
                self._write_source_record(source_id, "firecrawl", "error", duration_ms, str(e))
                logger.error(
                    f"ingest url mislukt: project={self.project_id} "
                    f"source={source_id} url={url} fout={e}"
                )
                self._add_flag(
                    "ingest_source_failed",
                    "medium",
                    f"source {source_id} ({url}) mislukt: {e}",
                )
            counter += 1

        if not successful_sources:
            logger.error(f"alle bronnen mislukt: project={self.project_id}")
            self._set_status("failed")
            self._add_flag("ingest_failed", "high", "alle bronnen zijn mislukt")
            return

        # genereer bundle via llm
        sources_text = "\n\n".join(
            f"## {sid}\n\n{md}" for sid, md in successful_sources
        )
        prompt_template = load_prompt("ingest_bundle")
        user_prompt = render_prompt(
            prompt_template,
            {"research_plan": research_plan_text, "sources": sources_text},
        )
        logger.info(f"bundle genereren: project={self.project_id}")
        bundle_md = self._call_llm(
            "longform_model",
            user_prompt,
            role_name="bundle",
        )
        (ingested_dir / "bundle.md").write_text(bundle_md, encoding="utf-8")
        logger.info(f"bundle klaar: project={self.project_id}")

        self._set_status("ingested")
