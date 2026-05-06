"""unit-tests voor de llm-client (zonder echte api-call)."""

from unittest.mock import MagicMock, patch


def test_llmclient_init_loads_config():
    """Controleer dat LLMClient correct initialiseert en de config inlaadt zonder api-call."""
    from src.llm_client import LLMClient

    client = LLMClient()
    assert "profiles" in client.config
    assert "reasoning_model" in client.config["profiles"]
    assert "primary" in client.config["profiles"]["reasoning_model"]
    assert "fallback" in client.config["profiles"]["reasoning_model"]


def test_llmclient_chat_returns_expected_fields():
    """Controleer dat chat() de verwachte velden teruggeeft (gemockt op _call_model)."""
    from src.llm_client import LLMClient

    fake_raw = {
        "choices": [{"message": {"content": "ok"}}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 2, "cost": 0.0},
    }
    mock_write = MagicMock()

    with (
        patch.object(LLMClient, "_call_model", return_value=fake_raw),
        patch.object(LLMClient, "_write_call_record", mock_write),
    ):
        client = LLMClient()
        result = client.chat(
            profile="reasoning_model",
            messages=[{"role": "user", "content": "test"}],
            max_tokens=5,
        )

    assert result["content"] == "ok"
    assert result["input_tokens"] == 10
    assert result["output_tokens"] == 2
    assert "model_used" in result
    assert "duration_ms" in result
