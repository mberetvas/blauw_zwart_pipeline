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
    """Generate a short random request ID for log correlation.

    Returns:
        Eight-character hexadecimal request identifier.
    """
    return uuid.uuid4().hex[:8]


def set_request_id(req_id: str) -> Token[str]:
    """Set the active request ID for the current execution context.

    Args:
        req_id: Correlation ID to expose through logging helpers.

    Returns:
        ContextVar token that can later restore the previous value.
    """
    return _REQUEST_ID.set(req_id)


def get_request_id() -> str:
    """Return the current request ID, or ``"-"`` when unset."""
    return _REQUEST_ID.get()


def reset_request_id(token: Token[str]) -> None:
    """Restore the previous request ID using a saved ContextVar token."""
    _REQUEST_ID.reset(token)


register_request_id_getter(get_request_id)

log = get_logger(__name__)


# ---------------------------------------------------------------------------
# LangChain callback handler
# ---------------------------------------------------------------------------

_TRUNCATE_ARGS = 120
_TRUNCATE_OUTPUT = 80


class AgentObservabilityHandler(BaseCallbackHandler):
    """LangChain callback handler for request-scoped timing and progress events.

    The handler records per-run timing for chat-model calls, legacy LLM calls,
    and tool invocations. It logs structured timing data and can optionally push
    lightweight progress payloads to an SSE stream.
    """

    def __init__(
        self,
        *,
        progress_sink: Callable[[dict[str, Any]], None] | None = None,
        phase: str = "primary",
    ) -> None:
        """Initialize the callback handler.

        Args:
            progress_sink: Optional callback that receives progress payloads.
            phase: Pipeline phase label attached to emitted progress events.
        """
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
        """Record the start of a chat-model invocation."""
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
        """Record the start of a legacy text-LLM invocation."""
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
        """Log completion details for an LLM invocation."""
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
        """Log failure details for an LLM invocation."""
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
        """Record the start of a tool invocation."""
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
        """Log completion details for a tool invocation."""
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
        """Log failure details for a tool invocation."""
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
        """Extract a display-friendly model name from LangChain metadata."""
        return (serialized.get("kwargs") or {}).get("model") or serialized.get("name") or "unknown"

    def _pop_run(self, run_id: UUID) -> dict[str, Any]:
        """Remove a tracked run and compute its elapsed time in milliseconds."""
        meta = self._runs.pop(run_id, {})
        started_at = meta.get("started_at")
        elapsed_ms = (time.perf_counter() - started_at) * 1000 if started_at else 0.0
        return {"name": meta.get("name", "unknown"), "elapsed_ms": elapsed_ms}

    def _emit_progress(self, payload: dict[str, Any]) -> None:
        """Forward one progress payload to the optional SSE sink."""
        if self._progress_sink is None:
            return
        event = dict(payload)
        event.setdefault("ts", datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"))
        try:
            self._progress_sink(event)
        except Exception:
            # Progress reporting must never break the agent flow.
            return
