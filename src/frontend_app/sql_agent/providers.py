"""LLM provider — OpenRouter only — using LangChain ``ChatOpenRouter``.

This module exposes:

* ``build_chat_model(model)`` — the canonical factory used by the LangGraph agent.
* ``complete(prompt, provider, model)`` — backward-compatible thin shim that
  delegates to ``ChatOpenRouter.invoke``. Accepts and silently ignores the
  ``provider`` argument when it equals ``"openrouter"``.
* ``_iter_answer_stream(provider, model, prompt)`` — backward-compatible thin
  shim that delegates to ``ChatOpenRouter.stream``.
* ``_llm_request_error`` — error mapper for HTTP status / timeout / connection
  failures; preserves the existing JSON error shape.

Ollama support has been removed. Calls with ``provider != "openrouter"`` raise
``ValueError``.
"""

from __future__ import annotations

import logging
from typing import Any, Iterator

import requests
from langchain_core.messages import HumanMessage
from langchain_openrouter import ChatOpenRouter

from .llm_runtime_config import get_llm_settings

log = logging.getLogger(__name__)

KNOWN_PROVIDERS: frozenset[str] = frozenset({"openrouter"})
_PROVIDER_DISPLAY = {"openrouter": "OpenRouter"}


class ProviderConfigurationError(RuntimeError):
    """Raised when the OpenRouter API key is not configured."""


def _require_api_key(api_key: str) -> str:
    if not api_key:
        raise ProviderConfigurationError(
            "OpenRouter is not configured. "
            "Set the API key under Club Settings or OPENROUTER_API_KEY in the environment."
        )
    return api_key


def build_chat_model(
    model: str,
    *,
    streaming: bool = False,
    temperature: float | None = None,
    tools: list[Any] | None = None,
) -> ChatOpenRouter:
    """Construct a ``ChatOpenRouter`` instance configured from runtime settings.

    Parameters
    ----------
    model:
        OpenRouter model identifier (e.g. ``"deepseek/deepseek-v3.2"``).
    streaming:
        When ``True``, configures the chat model for token streaming.
    temperature:
        Optional temperature override.
    tools:
        Optional list of LangChain tools to bind via ``bind_tools``.
    """
    s = get_llm_settings()
    api_key = _require_api_key(s.get("openrouter_api_key", ""))
    kwargs: dict[str, Any] = {
        "openrouter_api_key": api_key,
        "openrouter_api_base": s["openrouter_base_url"],
        "model_name": model,
        "request_timeout": int(s["openrouter_timeout"]),
        "streaming": streaming,
    }
    if temperature is not None:
        kwargs["temperature"] = float(temperature)
    chat = ChatOpenRouter(**kwargs)
    if tools:
        return chat.bind_tools(tools)  # type: ignore[return-value]
    return chat


def _check_provider(provider: str) -> None:
    if provider not in KNOWN_PROVIDERS:
        raise ValueError(
            f"Unknown provider '{provider}'. Only 'openrouter' is supported."
        )


def complete(prompt: str, provider: str, model: str) -> str:
    """Backward-compatible single-shot completion via OpenRouter.

    The ``provider`` argument must be ``"openrouter"``; other values raise
    ``ValueError``. Returns the assistant message text, stripped.
    """
    _check_provider(provider)
    chat = build_chat_model(model)
    msg = chat.invoke([HumanMessage(content=prompt)])
    text = msg.content if isinstance(msg.content, str) else str(msg.content)
    return text.strip()


def _iter_answer_stream(provider: str, model: str, answer_prompt: str) -> Iterator[str]:
    """Backward-compatible streaming of an answer prompt via OpenRouter."""
    _check_provider(provider)
    chat = build_chat_model(model, streaming=True)
    for chunk in chat.stream([HumanMessage(content=answer_prompt)]):
        text = chunk.content if isinstance(chunk.content, str) else ""
        if text:
            yield text


def _llm_request_error(
    provider_label: str,
    stage: str,
    exc: Exception,
) -> tuple[str, int]:
    """Map provider request failures to clearer API responses.

    Accepts both ``requests.exceptions.RequestException`` (legacy) and any
    ``Exception`` raised by the LangChain client. The mapping inspects the
    exception's HTTP-status attribute when present.
    """
    response = getattr(exc, "response", None)
    status_code = getattr(response, "status_code", None)
    if status_code is None:
        status_code = getattr(exc, "status_code", None)
    if status_code == 429:
        return (
            f"{provider_label} hit a rate limit during the {stage} step. "
            "Wait a moment, switch model, or check your rate limits.",
            429,
        )
    if status_code in {401, 403}:
        return (
            f"{provider_label} rejected the request during the {stage} step. "
            "Check the server-side API key and model access.",
            503,
        )
    if isinstance(exc, requests.exceptions.Timeout):
        return (f"{provider_label} timed out during the {stage} step.", 504)
    if isinstance(exc, requests.exceptions.ConnectionError):
        return (
            f"{provider_label} is unreachable during the {stage} step. "
            "Check the provider connection and try again.",
            503,
        )
    return (f"{provider_label} request failed during the {stage} step: {exc}", 503)
