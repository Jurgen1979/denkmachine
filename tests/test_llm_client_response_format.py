"""uitbreiding van llm-client tests: response_format kwarg."""

import os
from unittest.mock import MagicMock, patch

os.environ.setdefault("DM_USER", "testuser")
os.environ.setdefault("DM_SECRET_KEY", "test-secret-key")
os.environ.setdefault("DM_PASSWORD_HASH", "")
os.environ.setdefault("OPENROUTER_API_KEY", "test-key")
os.environ.setdefault("FIRECRAWL_API_KEY", "test-firecrawl-key")


def _fake_raw(content: str = "ok") -> dict:
    return {
        "choices": [{"message": {"content": content}}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 2, "cost": 0.0},
    }


def test_chat_with_response_format_passes_to_payload():
    """chat() met response_format stuurt de key door in de http-payload."""
    import httpx
    from src.llm_client import LLMClient

    captured = {}

    def mock_post(url, headers, json, **kwargs):
        captured["payload"] = json
        resp = MagicMock(spec=httpx.Response)
        resp.raise_for_status = MagicMock()
        resp.json.return_value = _fake_raw()
        return resp

    mock_write = MagicMock()

    with (
        patch("httpx.Client") as mock_client_cls,
        patch.object(LLMClient, "_write_call_record", mock_write),
    ):
        mock_ctx = MagicMock()
        mock_ctx.__enter__ = MagicMock(return_value=mock_ctx)
        mock_ctx.__exit__ = MagicMock(return_value=False)
        mock_ctx.post = mock_post
        mock_client_cls.return_value = mock_ctx

        client = LLMClient()
        client.chat(
            profile="reasoning_model",
            messages=[{"role": "user", "content": "test"}],
            response_format={"type": "json_object"},
        )

    assert "response_format" in captured["payload"]
    assert captured["payload"]["response_format"] == {"type": "json_object"}


def test_chat_without_response_format_no_key_in_payload():
    """chat() zonder response_format stuurt de key niet mee in de http-payload."""
    import httpx
    from src.llm_client import LLMClient

    captured = {}

    def mock_post(url, headers, json, **kwargs):
        captured["payload"] = json
        resp = MagicMock(spec=httpx.Response)
        resp.raise_for_status = MagicMock()
        resp.json.return_value = _fake_raw()
        return resp

    mock_write = MagicMock()

    with (
        patch("httpx.Client") as mock_client_cls,
        patch.object(LLMClient, "_write_call_record", mock_write),
    ):
        mock_ctx = MagicMock()
        mock_ctx.__enter__ = MagicMock(return_value=mock_ctx)
        mock_ctx.__exit__ = MagicMock(return_value=False)
        mock_ctx.post = mock_post
        mock_client_cls.return_value = mock_ctx

        client = LLMClient()
        client.chat(
            profile="reasoning_model",
            messages=[{"role": "user", "content": "test"}],
        )

    assert "response_format" not in captured["payload"]
