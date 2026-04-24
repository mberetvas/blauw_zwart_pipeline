"""LLM provider calling: Ollama and OpenRouter (sync + streaming)."""

from __future__ import annotations

import json
import logging
from typing import Iterator

import requests

from .llm_runtime_config import get_llm_settings

log = logging.getLogger(__name__)

KNOWN_PROVIDERS: frozenset[str] = frozenset({"ollama", "openrouter"})
_PROVIDER_DISPLAY = {"ollama": "Ollama", "openrouter": "OpenRouter"}


def _call_ollama(prompt: str, model: str) -> str:
    """Send a prompt to Ollama /api/generate and return the response text."""
    s = get_llm_settings()
    resp = requests.post(
        f"{s['ollama_url']}/api/generate",
        json={"model": model, "prompt": prompt, "stream": False},
        timeout=int(s["ollama_timeout"]),
    )
    resp.raise_for_status()
    return resp.json()["response"].strip()


def _call_openrouter(prompt: str, model: str) -> str:
    """Send a prompt to OpenRouter chat/completions and return the response text."""
    s = get_llm_settings()
    resp = requests.post(
        f"{s['openrouter_base_url']}/chat/completions",
        headers={
            "Authorization": f"Bearer {s['openrouter_api_key']}",
            "Content-Type": "application/json",
        },
        json={"model": model, "messages": [{"role": "user", "content": prompt}]},
        timeout=int(s["openrouter_timeout"]),
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"].strip()


def complete(prompt: str, provider: str, model: str) -> str:
    """Call the selected LLM provider and return the plain-text response."""
    if provider == "openrouter":
        return _call_openrouter(prompt, model)
    return _call_ollama(prompt, model)


def _llm_request_error(
    provider_label: str,
    stage: str,
    exc: requests.exceptions.RequestException,
) -> tuple[str, int]:
    """Map provider request failures to clearer API responses."""
    status_code = getattr(getattr(exc, "response", None), "status_code", None)
    if status_code == 429:
        return (
            f"{provider_label} hit a rate limit during the {stage} step. "
            "Wait a moment, switch model, or try the other provider.",
            429,
        )
    if status_code in {401, 403}:
        return (
            f"{provider_label} rejected the request during the {stage} step. "
            "Check the server-side API key and model access.",
            503,
        )
    if isinstance(exc, requests.exceptions.Timeout):
        return (
            f"{provider_label} timed out during the {stage} step.",
            504,
        )
    if isinstance(exc, requests.exceptions.ConnectionError):
        return (
            f"{provider_label} is unreachable during the {stage} step. "
            "Check the provider connection and try again.",
            503,
        )
    return (f"{provider_label} request failed during the {stage} step: {exc}", 503)


def _streaming_timeout(total: int) -> tuple[int, int]:
    """(connect, read) for streaming requests; read uses full provider timeout."""
    c = min(30, max(1, total))
    return (c, total)


def _stream_ollama_answer(prompt: str, model: str) -> Iterator[str]:
    s = get_llm_settings()
    to = int(s["ollama_timeout"])
    timeout = _streaming_timeout(to)
    with requests.post(
        f"{s['ollama_url']}/api/generate",
        json={"model": model, "prompt": prompt, "stream": True},
        stream=True,
        timeout=timeout,
    ) as resp:
        resp.raise_for_status()
        for line in resp.iter_lines(decode_unicode=True):
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                log.warning("Ollama stream: skip non-JSON line: %s", line[:200])
                continue
            piece = obj.get("response") or ""
            if piece:
                yield piece


def _stream_openrouter_answer(prompt: str, model: str) -> Iterator[str]:
    s = get_llm_settings()
    to = int(s["openrouter_timeout"])
    timeout = _streaming_timeout(to)
    with requests.post(
        f"{s['openrouter_base_url']}/chat/completions",
        headers={
            "Authorization": f"Bearer {s['openrouter_api_key']}",
            "Content-Type": "application/json",
        },
        json={
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "stream": True,
        },
        stream=True,
        timeout=timeout,
    ) as resp:
        resp.raise_for_status()
        for line in resp.iter_lines(decode_unicode=True):
            if not line:
                continue
            if not line.startswith("data:"):
                continue
            data = line[5:].lstrip()
            if data == "[DONE]":
                break
            try:
                obj = json.loads(data)
            except json.JSONDecodeError:
                continue
            choices = obj.get("choices") or []
            if not choices:
                continue
            delta = choices[0].get("delta") or {}
            content = delta.get("content")
            if content:
                yield content


def _iter_answer_stream(provider: str, model: str, answer_prompt: str) -> Iterator[str]:
    """Yield non-empty UTF-8 text fragments from the provider's streaming answer API."""
    if provider == "openrouter":
        yield from _stream_openrouter_answer(answer_prompt, model)
    else:
        yield from _stream_ollama_answer(answer_prompt, model)
