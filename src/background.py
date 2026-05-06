"""achtergrond-threads voor langlopende agent-taken."""

import threading

from loguru import logger


def start_ingest_thread(project_id: str) -> None:
    """Start de ingest-agent in een achtergrond-thread."""

    def _run() -> None:
        try:
            from src.agents.ingest import IngestAgent
            from src.llm_client import LLMClient

            agent = IngestAgent(LLMClient(), project_id)
            agent.run()
        except Exception:
            logger.exception(f"ingest thread crashed: project={project_id}")

    t = threading.Thread(target=_run, daemon=True)
    t.start()
