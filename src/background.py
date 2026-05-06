"""achtergrond-threads voor langlopende agent-taken."""

import threading

from loguru import logger


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
