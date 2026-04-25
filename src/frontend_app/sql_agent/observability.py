"""Request-level observability: correlation IDs and LangChain timing callbacks."""

from __future__ import annotations

import time
import uuid
from contextvars import ContextVar, Token
from datetime import datetime, timezone
from typing import Any, Callable
from uuid import UUID

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.outputs import LLMResult

from common.logging_setup import get_logger, register_request_id_getter

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


def reset_request_id(token: Token[str]) -> None:
    """Reset the request ID ContextVar to its previous value using the token."""
    _REQUEST_ID.reset(token)


register_request_id_getter(get_request_id)

log = get_logger(__name__)


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

    def __init__(
        self,
        *,
        progress_sink: Callable[[dict[str, Any]], None] | None = None,
        phase: str = "primary",
    ) -> None:
        super().__init__()
        # run_id -> {"started_at": float, "name": str}
        self._runs: dict[UUID, dict[str, Any]] = {}
        self._progress_sink = progress_sink
        self._phase = phase

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
        self._emit_progress(
            {
                "step_key": "llm_start",
                "phase": self._phase,
                "model": model,
            }
        )
        log.debug(
            "task=llm_start model={} previous=agent_stage_ready next=await_llm_response",
            model,
        )

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
        self._emit_progress(
            {
                "step_key": "llm_start",
                "phase": self._phase,
                "model": model,
            }
        )
        log.debug(
            "task=llm_start model={} previous=agent_stage_ready next=await_llm_response",
            model,
        )

    def on_llm_end(
        self,
        response: LLMResult,
        *,
        run_id: UUID,
        **kwargs: Any,
    ) -> None:
        meta = self._pop_run(run_id)
        log.info(
            "llm_complete model={} elapsed_ms={:.0f}",
            meta["name"],
            meta["elapsed_ms"],
        )
        self._emit_progress(
            {
                "step_key": "llm_done",
                "phase": self._phase,
                "model": meta["name"],
                "elapsed_ms": round(meta["elapsed_ms"]),
            }
        )

    def on_llm_error(
        self,
        error: BaseException,
        *,
        run_id: UUID,
        **kwargs: Any,
    ) -> None:
        meta = self._pop_run(run_id)
        log.info(
            "llm_failed model={} elapsed_ms={:.0f} error={}",
            meta["name"],
            meta["elapsed_ms"],
            error,
        )
        self._emit_progress(
            {
                "step_key": "llm_error",
                "phase": self._phase,
                "model": meta["name"],
                "elapsed_ms": round(meta["elapsed_ms"]),
                "error": str(error),
            }
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
        self._emit_progress(
            {
                "step_key": "tool_start",
                "phase": self._phase,
                "tool": name,
                "args_preview": input_str[:_TRUNCATE_ARGS],
            }
        )
        log.debug(
            "task=tool_start tool={} previous=llm_selected_tool next=invoke_tool args={}",
            name,
            input_str[:_TRUNCATE_ARGS],
        )

    def on_tool_end(
        self,
        output: Any,
        *,
        run_id: UUID,
        **kwargs: Any,
    ) -> None:
        meta = self._pop_run(run_id)
        log.info(
            "tool_complete tool={} elapsed_ms={:.0f} output={}",
            meta["name"],
            meta["elapsed_ms"],
            str(output)[:_TRUNCATE_OUTPUT],
        )
        self._emit_progress(
            {
                "step_key": "tool_done",
                "phase": self._phase,
                "tool": meta["name"],
                "elapsed_ms": round(meta["elapsed_ms"]),
            }
        )

    def on_tool_error(
        self,
        error: BaseException,
        *,
        run_id: UUID,
        **kwargs: Any,
    ) -> None:
        meta = self._pop_run(run_id)
        log.info(
            "tool_failed tool={} elapsed_ms={:.0f} error={}",
            meta["name"],
            meta["elapsed_ms"],
            error,
        )
        self._emit_progress(
            {
                "step_key": "tool_error",
                "phase": self._phase,
                "tool": meta["name"],
                "elapsed_ms": round(meta["elapsed_ms"]),
                "error": str(error),
            }
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

    def _emit_progress(self, payload: dict[str, Any]) -> None:
        if self._progress_sink is None:
            return
        event = dict(payload)
        event.setdefault("ts", datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"))
        try:
            self._progress_sink(event)
        except Exception:
            # Progress reporting must never break the agent flow.
            return
