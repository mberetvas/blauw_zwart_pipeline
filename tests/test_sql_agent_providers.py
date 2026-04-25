"""Unit tests for sql_agent.providers (OpenRouter chat model factory + helpers)."""

from __future__ import annotations

import importlib
from typing import Any
from unittest.mock import MagicMock

import pytest
import requests

from frontend_app.sql_agent import providers


@pytest.fixture()
def cfg(tmp_path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("LLM_CONFIG_PATH", str(tmp_path / "llm_config.json"))
    monkeypatch.setenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
    monkeypatch.setenv("OPENROUTER_MODEL", "deepseek/deepseek-v3.2")
    monkeypatch.setenv("OPENROUTER_TIMEOUT", "30")
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test-fixture-key")
    monkeypatch.delenv("OPENROUTER_AGENT_MODEL", raising=False)

    import frontend_app.sql_agent.llm_runtime_config as runtime_config

    importlib.reload(runtime_config)
    runtime_config.init_llm_config()
    importlib.reload(providers)
    return providers


# ---------------------------------------------------------------------------
# build_chat_model
# ---------------------------------------------------------------------------


def test_build_chat_model_passes_runtime_config(cfg, monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    def fake_chat(**kwargs: Any) -> MagicMock:
        captured.update(kwargs)
        m = MagicMock(name="ChatOpenRouter")
        return m

    monkeypatch.setattr(cfg, "ChatOpenRouter", fake_chat)
    cfg.build_chat_model("openai/gpt-4.1-mini", streaming=True, temperature=0.25)

    assert captured["openrouter_api_key"] == "sk-test-fixture-key"
    assert captured["openrouter_api_base"] == "https://openrouter.ai/api/v1"
    assert captured["model_name"] == "openai/gpt-4.1-mini"
    assert captured["streaming"] is True
    assert captured["temperature"] == 0.25
    # 30s in env → 30000 ms
    assert captured["request_timeout"] == 30_000


def test_build_chat_model_binds_tools_when_provided(cfg, monkeypatch: pytest.MonkeyPatch) -> None:
    chat = MagicMock(name="ChatOpenRouter")
    chat.bind_tools.return_value = "BOUND"
    monkeypatch.setattr(cfg, "ChatOpenRouter", lambda **_: chat)

    out = cfg.build_chat_model("m", tools=["t1", "t2"])
    assert out == "BOUND"
    chat.bind_tools.assert_called_once_with(["t1", "t2"])


def test_build_chat_model_raises_when_api_key_missing(cfg, monkeypatch: pytest.MonkeyPatch) -> None:
    import frontend_app.sql_agent.llm_runtime_config as runtime_config

    runtime_config.apply_llm_config_update({"openrouter_api_key": ""})
    with pytest.raises(cfg.ProviderConfigurationError, match=r"OpenRouter is not configured"):
        cfg.build_chat_model("m")


# ---------------------------------------------------------------------------
# _check_provider / complete / _iter_answer_stream
# ---------------------------------------------------------------------------


def test_check_provider_rejects_unknown(cfg) -> None:
    with pytest.raises(ValueError, match=r"Unknown provider"):
        cfg._check_provider("ollama")


def test_complete_invokes_chat_and_strips(cfg, monkeypatch: pytest.MonkeyPatch) -> None:
    chat = MagicMock()
    msg = MagicMock()
    msg.content = "  hello world  "
    chat.invoke.return_value = msg
    monkeypatch.setattr(cfg, "build_chat_model", lambda model: chat)

    out = cfg.complete("ping", "openrouter", "deepseek/deepseek-v3.2")
    assert out == "hello world"
    chat.invoke.assert_called_once()


def test_complete_handles_non_string_content(cfg, monkeypatch: pytest.MonkeyPatch) -> None:
    chat = MagicMock()
    msg = MagicMock()
    msg.content = ["chunk1", "chunk2"]
    chat.invoke.return_value = msg
    monkeypatch.setattr(cfg, "build_chat_model", lambda model: chat)

    out = cfg.complete("ping", "openrouter", "m")
    assert isinstance(out, str)


def test_iter_answer_stream_yields_text_chunks(cfg, monkeypatch: pytest.MonkeyPatch) -> None:
    def make_chunk(text: str) -> MagicMock:
        c = MagicMock()
        c.content = text
        return c

    chat = MagicMock()
    chat.stream.return_value = iter([make_chunk("hel"), make_chunk(""), make_chunk("lo")])

    monkeypatch.setattr(cfg, "build_chat_model", lambda model, streaming=False: chat)

    out = list(cfg._iter_answer_stream("openrouter", "m", "prompt"))
    assert out == ["hel", "lo"]


# ---------------------------------------------------------------------------
# _llm_request_error
# ---------------------------------------------------------------------------


class _Resp:
    def __init__(self, status_code: int) -> None:
        self.status_code = status_code


def _exc_with_response(status: int) -> Exception:
    e = RuntimeError("err")
    e.response = _Resp(status)  # type: ignore[attr-defined]
    return e


def test_llm_request_error_rate_limit() -> None:
    msg, code = providers._llm_request_error("OpenRouter", "agent", _exc_with_response(429))
    assert code == 429
    assert "rate limit" in msg.lower()


def test_llm_request_error_unauthorized_returns_503() -> None:
    msg, code = providers._llm_request_error("OpenRouter", "agent", _exc_with_response(401))
    assert code == 503
    assert "rejected" in msg.lower()


def test_llm_request_error_timeout() -> None:
    msg, code = providers._llm_request_error("OpenRouter", "answer", requests.exceptions.Timeout())
    assert code == 504
    assert "timed out" in msg.lower()


def test_llm_request_error_connection() -> None:
    msg, code = providers._llm_request_error(
        "OpenRouter", "answer", requests.exceptions.ConnectionError()
    )
    assert code == 503
    assert "unreachable" in msg.lower()


def test_llm_request_error_unknown_falls_back_to_503() -> None:
    msg, code = providers._llm_request_error("OpenRouter", "agent", RuntimeError("weird"))
    assert code == 503
    assert "request failed" in msg.lower()


def test_llm_request_error_uses_status_code_attr() -> None:
    e = RuntimeError("x")
    e.status_code = 429  # type: ignore[attr-defined]
    msg, code = providers._llm_request_error("OpenRouter", "agent", e)
    assert code == 429
