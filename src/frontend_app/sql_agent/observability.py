"""Request-level observability: correlation IDs and LangChain timing callbacks."""

from __future__ import annotations

import logging
import time
import uuid
from contextvars import ContextVar, Token
from typing import Any
from uuid import UUID

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.outputs import LLMResult

# ---------------------------------------------------------------------------
# Request-ID ContextVar
# ---------------------------------------------------------------------------

_REQUEST_ID: ContextVar[str] = ContextVar("_REQUEST_ID", default="-")


def new_request_id() -> str:
    """Generate a short random 8-hex-char request ID."""
    return uuid.uuid4().hex[:8]


def set_request_id(req_id: str) -> Token[str]:
    """Set the request ID for the current context and return the reset token."""
    return _REQUEST_ID.set(req_id)


def get_request_id() -> str:
    """Return the current request ID (``"-"`` if none has been set)."""
    return _REQUEST_ID.get()


# ---------------------------------------------------------------------------
# Logging filter
# ---------------------------------------------------------------------------


def reset_request_id(token: Token[str]) -> None:
    """Reset the request ID ContextVar to its previous value using the token."""
    _REQUEST_ID.reset(token)


class RequestIdFilter(logging.Filter):
    """Inject ``req_id`` from the ContextVar into every LogRecord."""

    def filter(self, record: logging.LogRecord) -> bool:  # noqa: A003
        record.req_id = _REQUEST_ID.get()  # type: ignore[attr-defined]
        return True


# ---------------------------------------------------------------------------
# LangChain callback handler
# ---------------------------------------------------------------------------

_TRUNCATE_ARGS = 120
_TRUNCATE_OUTPUT = 80


class AgentObservabilityHandler(BaseCallbackHandler):
    """LangChain callback handler that emits INFO-level timing logs.

    Covers both chat models (``on_chat_model_start``) and legacy text LLMs
    (``on_llm_start``), plus tool calls.  Stores per-``run_id`` metadata so
    that ``on_*_end`` / ``on_*_error`` can emit complete log lines.
    """

    def __init__(self) -> None:
        super().__init__()
        # run_id -> {"started_at": float, "name": str}
        self._runs: dict[UUID, dict[str, Any]] = {}

    # ------------------------------------------------------------------
    # Chat model (LangChain ≥ 0.1)
    # ------------------------------------------------------------------

    def on_chat_model_start(
        self,
        serialized: dict[str, Any],
        messages: list[list[Any]],
        *,
        run_id: UUID,
        **kwargs: Any,
    ) -> None:
        model = self._extract_model(serialized)
        self._runs[run_id] = {"started_at": time.perf_counter(), "name": model}
        logging.getLogger(__name__).info("LLM call start | model=%s", model)

    # ------------------------------------------------------------------
    # Legacy text LLM
    # ------------------------------------------------------------------

    def on_llm_start(
        self,
        serialized: dict[str, Any],
        prompts: list[str],
        *,
        run_id: UUID,
        **kwargs: Any,
    ) -> None:
        model = self._extract_model(serialized)
        self._runs[run_id] = {"started_at": time.perf_counter(), "name": model}
        logging.getLogger(__name__).info("LLM call start | model=%s", model)

    def on_llm_end(
        self,
        response: LLMResult,
        *,
        run_id: UUID,
        **kwargs: Any,
    ) -> None:
        meta = self._pop_run(run_id)
        logging.getLogger(__name__).info("LLM call end — %.0f ms", meta["elapsed_ms"])

    def on_llm_error(
        self,
        error: BaseException,
        *,
        run_id: UUID,
        **kwargs: Any,
    ) -> None:
        meta = self._pop_run(run_id)
        logging.getLogger(__name__).error(
            "LLM call error — %.0f ms: %s", meta["elapsed_ms"], error
        )

    # ------------------------------------------------------------------
    # Tools
    # ------------------------------------------------------------------

    def on_tool_start(
        self,
        serialized: dict[str, Any],
        input_str: str,
        *,
        run_id: UUID,
        **kwargs: Any,
    ) -> None:
        name = serialized.get("name") or "unknown_tool"
        self._runs[run_id] = {"started_at": time.perf_counter(), "name": name}
        logging.getLogger(__name__).info(
            "Tool call start: %s | args=%s", name, input_str[:_TRUNCATE_ARGS]
        )

    def on_tool_end(
        self,
        output: Any,
        *,
        run_id: UUID,
        **kwargs: Any,
    ) -> None:
        meta = self._pop_run(run_id)
        logging.getLogger(__name__).info(
            "Tool call end: %s — %.0f ms | output=%s",
            meta["name"],
            meta["elapsed_ms"],
            str(output)[:_TRUNCATE_OUTPUT],
        )

    def on_tool_error(
        self,
        error: BaseException,
        *,
        run_id: UUID,
        **kwargs: Any,
    ) -> None:
        meta = self._pop_run(run_id)
        logging.getLogger(__name__).error(
            "Tool call error: %s — %.0f ms: %s", meta["name"], meta["elapsed_ms"], error
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_model(serialized: dict[str, Any]) -> str:
        return (
            (serialized.get("kwargs") or {}).get("model")
            or serialized.get("name")
            or "unknown"
        )

    def _pop_run(self, run_id: UUID) -> dict[str, Any]:
        meta = self._runs.pop(run_id, {})
        started_at = meta.get("started_at")
        elapsed_ms = (time.perf_counter() - started_at) * 1000 if started_at else 0.0
        return {"name": meta.get("name", "unknown"), "elapsed_ms": elapsed_ms}
