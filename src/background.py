"""achtergrond-threads voor langlopende agent-taken."""

import threading

from loguru import logger


def start_analysis_thread(project_id: str) -> None:
    """Start de volledige analyse-pipeline in een achtergrond-thread.

    Volgorde: analyst_runner -> critique_runner -> draft_agent -> synthese_agent
    """

    def _run() -> None:
        try:
            from src.agents.analyst_runner import AnalystRunner
            from src.agents.critique_runner import CritiqueRunner
            from src.agents.draft_agent import DraftAgent
            from src.agents.synthese_agent import SyntheseAgent
            from src.llm_client import LLMClient

            client = LLMClient()

            # stap 1: analist-rollen
            analyst = AnalystRunner(client, project_id)
            analyst_outputs = analyst.run()
            if not analyst_outputs:
                logger.error(f"analyst runner leeg resultaat: project={project_id}")
                _set_failed(project_id, "analyst_runner leverde geen output")
                return

            # stap 2: critique-rollen
            critique = CritiqueRunner(client, project_id)
            critiques = critique.run(analyst_outputs)

            # stap 3: sectie-drafts (met redo voor high-severity secties)
            draft = DraftAgent(client, project_id)
            section_drafts = draft.run(analyst_outputs, critiques)
            if not section_drafts:
                logger.error(f"draft agent leeg resultaat: project={project_id}")
                _set_failed(project_id, "draft_agent leverde geen secties")
                return

            # stap 4: synthese + actieplan
            synthese = SyntheseAgent(client, project_id)
            synthese.run(section_drafts)

        except Exception:
            logger.exception(f"analyse thread crashed: project={project_id}")
            _set_failed(project_id, "onverwachte fout in analyse-pipeline")

    t = threading.Thread(target=_run, daemon=True)
    t.start()


def _set_failed(project_id: str, reason: str) -> None:
    """Zet project-status op failed en voeg een vlag toe."""
    from datetime import datetime, timezone

    from src.models import Flag, Project
    from src.state import get_session

    now = datetime.now(timezone.utc).isoformat()
    with get_session() as session:
        project = session.get(Project, project_id)
        if project is not None:
            project.status = "failed"
            project.updated_at = now
            session.commit()
    with get_session() as session:
        session.add(Flag(
            project_id=project_id,
            type="pipeline_failed",
            severity="high",
            description=reason,
            resolved=False,
            created_at=now,
        ))
        session.commit()
    logger.error(f"project op failed gezet: project={project_id} reden={reason}")


def start_pipeline_thread(project_id: str) -> None:
    """Start de ingest-pipeline gevolgd door bewijs-extractie in één achtergrond-thread."""

    def _run() -> None:
        try:
            from src.agents.bewijs_extractor import BewijsExtractorAgent
            from src.agents.ingest import IngestAgent
            from src.llm_client import LLMClient

            client = LLMClient()
            ingest = IngestAgent(client, project_id)
            ingest.run()

            # alleen doorgaan met bewijs-extractie als ingest succesvol was
            from src.models import Project
            from src.state import get_session
            with get_session() as session:
                project = session.get(Project, project_id)
                status = project.status if project else None
            if status != "ingested":
                logger.warning(
                    f"ingest niet ingested (status={status}), bewijs-extractie overgeslagen: "
                    f"project={project_id}"
                )
                return

            extractor = BewijsExtractorAgent(client, project_id)
            extractor.run()
        except Exception:
            logger.exception(f"pipeline thread crashed: project={project_id}")

    t = threading.Thread(target=_run, daemon=True)
    t.start()


def start_extraction_thread(project_id: str) -> None:
    """Start alleen de bewijs-extractie (na een herstart of voor al ingested projecten)."""

    def _run() -> None:
        try:
            from src.agents.bewijs_extractor import BewijsExtractorAgent
            from src.llm_client import LLMClient

            client = LLMClient()
            extractor = BewijsExtractorAgent(client, project_id)
            extractor.run()
        except Exception:
            logger.exception(f"extractie thread crashed: project={project_id}")

    t = threading.Thread(target=_run, daemon=True)
    t.start()
