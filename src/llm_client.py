"""llm-client voor openrouter-calls met retry-logica en logging naar agent_calls."""

import os
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx
from loguru import logger
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from src.utils import load_yaml

_BASE_DIR = Path(__file__).parent.parent
_OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
_TIMEOUT_SECONDS = 60


def _is_retryable(exc: BaseException) -> bool:
    """Bepaal of een uitzondering in aanmerking komt voor herhaling."""
    if isinstance(exc, httpx.TimeoutException):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code >= 500
    return False


class LLMClient:
    """Client voor llm-calls via openrouter."""

    def __init__(self) -> None:
        """Laad de model-configuratie uit config/models.yaml."""
        config_path = _BASE_DIR / "config" / "models.yaml"
        self.config = load_yaml(str(config_path))

    def _get_headers(self) -> dict:
        """Stel de http-headers samen voor openrouter."""
        api_key = os.environ["OPENROUTER_API_KEY"]
        return {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://denkmachine.jrgndwvr.be",
            "X-Title": "denkmachine",
        }

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(min=1, max=4),
        retry=retry_if_exception(_is_retryable),
        reraise=True,
    )
    def _call_model(self, model: str, messages: list, max_tokens: int, temperature: float) -> dict:
        """Doe een enkele http-call naar openrouter, met retry op 5xx en timeouts."""
        with httpx.Client(timeout=_TIMEOUT_SECONDS) as client:
            response = client.post(
                _OPENROUTER_URL,
                headers=self._get_headers(),
                json={
                    "model": model,
                    "messages": messages,
                    "max_tokens": max_tokens,
                    "temperature": temperature,
                },
            )
            response.raise_for_status()
            return response.json()

    def _write_call_record(
        self,
        project_id: str,
        agent_name: str,
        profile: str,
        model_used: str,
        result: dict,
        duration_ms: int,
        status: str = "ok",
        error_message: str | None = None,
    ) -> None:
        """Schrijf een agent_calls-record naar de database."""
        from src.models import AgentCall
        from src.state import get_session

        usage = result.get("usage", {})
        cost_eur = usage.get("cost", 0.0) or 0.0

        record = AgentCall(
            project_id=project_id,
            agent_name=agent_name,
            model_used=model_used,
            profile=profile,
            input_tokens=usage.get("prompt_tokens"),
            output_tokens=usage.get("completion_tokens"),
            cost_eur=cost_eur,
            duration_ms=duration_ms,
            status=status,
            error_message=error_message,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )
        with get_session() as session:
            session.add(record)
            session.commit()

    def chat(
        self,
        profile: str,
        messages: list,
        max_tokens: int | None = None,
        project_id: str = "ping",
        agent_name: str = "ping",
    ) -> dict:
        """
        Stuur berichten naar het opgegeven model-profiel en geef het resultaat terug.

        geeft terug: {content, input_tokens, output_tokens, cost_eur, model_used, duration_ms}
        """
        profiles = self.config.get("profiles", {})
        if profile not in profiles:
            raise ValueError(f"onbekend profiel: {profile}")

        profile_cfg = profiles[profile]
        primary_model = profile_cfg["primary"]
        fallback_model = profile_cfg["fallback"]
        temperature = profile_cfg.get("temperature", 0.5)
        effective_max_tokens = max_tokens or profile_cfg.get("max_output_tokens", 1024)

        # primaire poging met retry
        start = time.time()
        raw: dict = {}
        model_used = primary_model

        try:
            raw = self._call_model(primary_model, messages, effective_max_tokens, temperature)
        except Exception as primary_exc:
            duration_ms = int((time.time() - start) * 1000)
            logger.warning(
                f"primaire model {primary_model} mislukt na retries: {primary_exc}. "
                f"fallback naar {fallback_model}."
            )
            self._write_call_record(
                project_id=project_id,
                agent_name=agent_name,
                profile=profile,
                model_used=primary_model,
                result={},
                duration_ms=duration_ms,
                status="error",
                error_message=str(primary_exc),
            )
            # een enkele fallback-poging, geen retry
            start = time.time()
            model_used = fallback_model
            raw = self._call_model.__wrapped__(
                self, fallback_model, messages, effective_max_tokens, temperature
            )

        duration_ms = int((time.time() - start) * 1000)
        usage = raw.get("usage", {})
        content = raw["choices"][0]["message"]["content"]
        cost_eur = usage.get("cost", 0.0) or 0.0

        self._write_call_record(
            project_id=project_id,
            agent_name=agent_name,
            profile=profile,
            model_used=model_used,
            result=raw,
            duration_ms=duration_ms,
            status="ok",
        )

        return {
            "content": content,
            "input_tokens": usage.get("prompt_tokens", 0),
            "output_tokens": usage.get("completion_tokens", 0),
            "cost_eur": cost_eur,
            "model_used": model_used,
            "duration_ms": duration_ms,
        }
