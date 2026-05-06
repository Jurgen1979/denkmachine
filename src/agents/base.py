"""abstracte basisklasse voor alle denkmachine-agents."""

from abc import ABC, abstractmethod

from loguru import logger

from src.llm_client import LLMClient


class Agent(ABC):
    """basisklasse met gedeelde llm-call logica voor alle agents."""

    agent_name: str

    def __init__(self, llm_client: LLMClient, project_id: str) -> None:
        """Initialiseer de agent met een llm-client en project-id."""
        self.llm_client = llm_client
        self.project_id = project_id

    def _log_call(
        self,
        profile: str,
        model_used: str,
        duration_ms: int,
        input_tokens: int,
        output_tokens: int,
        cost_eur: float,
    ) -> None:
        """Log een agent-call naar dm.log met gestructureerde velden."""
        logger.info(
            f"agent_call agent={self.agent_name} project={self.project_id} "
            f"model={model_used} profile={profile} duration_ms={duration_ms} "
            f"input_tokens={input_tokens} output_tokens={output_tokens} "
            f"cost_eur={cost_eur:.4f}"
        )

    def _call_llm(
        self,
        profile: str,
        user_prompt: str,
        system_prompt: str | None = None,
        role_name: str | None = None,
    ) -> str:
        """Roep het llm aan, log de call en geef de tekst-response terug."""
        messages: list[dict] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": user_prompt})

        result = self.llm_client.chat(
            profile=profile,
            messages=messages,
            project_id=self.project_id,
            agent_name=self.agent_name,
            role_name=role_name,
        )

        self._log_call(
            profile=profile,
            model_used=result["model_used"],
            duration_ms=result["duration_ms"],
            input_tokens=result["input_tokens"],
            output_tokens=result["output_tokens"],
            cost_eur=result["cost_eur"],
        )

        return result["content"]

    @abstractmethod
    def run(self, *args, **kwargs):
        """Voer de agent-logica uit. Subklasse implementeert dit."""
        raise NotImplementedError
