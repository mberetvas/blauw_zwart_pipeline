"""LangGraph orchestration for the SQL agent.

Architecture
------------

A two-stage flow:

1. **Primary agent** — a tool-calling ReAct agent built with
   ``langchain.agents.create_agent`` and the ``agent_model``. It is
   given the full read-only toolset from :mod:`frontend_app.sql_agent.tools`
   and discovers schema on demand. It is expected to end by calling
   ``execute_select`` and producing a Markdown answer.

2. **Repair pass** — when the primary agent did not call ``execute_select``
   successfully, a one-shot ``create_agent`` over the ``repair_model`` is
   invoked with a constrained toolset (``describe_table`` + ``execute_select``).
   At most one repair pass per request.

If the repair pass also fails, the request returns a 422-equivalent error to
the host. Otherwise the result of whichever stage succeeded becomes the
:class:`AgentResult`.

Public API
----------

``run_ask(request) -> AgentResult``
    Synchronous entrypoint used by ``POST /api/ask``.

``run_ask_stream(request) -> Iterator[StreamEvent]``
    Streaming entrypoint used by ``POST /api/ask/stream``. Runs the agent
    pipeline to completion (synchronously), then emits one ``meta`` event with
    the SQL + data preview, the answer text as ``answer_delta`` event(s), and
    a final ``done`` event. Errors mid-pipeline are surfaced as ``error``.
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any, Iterator

from langchain.agents import create_agent
from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    ToolMessage,
)
from langgraph.errors import GraphRecursionError

from .database import _json_default
from .llm_runtime_config import resolve_agent_model, resolve_repair_model
from .observability import AgentObservabilityHandler
from .prompts import (
    AGENT_SYSTEM_PROMPT,
    REPAIR_SYSTEM_PROMPT,
    build_repair_user_prompt,
    build_user_prompt,
)
from .providers import _PROVIDER_DISPLAY, build_chat_model
from .semantic_layer import build_answer_semantic_context, load_semantic_layer
from .tools import ALL_TOOLS, REPAIR_TOOLS, execute_select

log = logging.getLogger(__name__)


def _max_iterations() -> int:
    raw = os.environ.get("AGENT_MAX_TOOL_ITERATIONS", "8").strip()
    try:
        n = int(raw)
        return max(1, min(n, 25))
    except ValueError:
        return 8


@dataclass
class AgentRequest:
    """Inputs for one SQL-agent invocation."""

    question: str
    conversation_section: str = ""
    conversation_turn_count: int = 0
    agent_model: str | None = None
    repair_model: str | None = None


@dataclass
class AgentResult:
    """Successful agent run."""

    answer: str
    sql: str
    rows: list[dict[str, Any]]
    data_preview: list[dict[str, Any]]
    agent_model: str
    repair_model: str
    repaired: bool
    notes: list[str] = field(default_factory=list)


@dataclass
class AgentFailure:
    """Agent run that could not produce a successful execute_select call."""

    error: str
    phase: str  # "validation" | "execution" | "no_sql" | "iteration_cap"
    sql: str | None
    agent_model: str
    repair_model: str
    notes: list[str] = field(default_factory=list)


@dataclass
class StreamEvent:
    """SSE event payload as ``(event_name, data_dict)``."""

    name: str
    data: dict[str, Any]


# ---------------------------------------------------------------------------
# Helpers: extract last execute_select result from a message history
# ---------------------------------------------------------------------------


def _last_execute_select_result(
    messages: list[BaseMessage],
) -> tuple[dict[str, Any] | None, str | None]:
    """Return ``(parsed_result, raw_sql_arg)`` from the most recent execute_select call.

    ``parsed_result`` is the JSON-decoded tool message content (which itself may
    carry an ``"error"`` field). ``raw_sql_arg`` is the SQL the agent passed in.
    Returns ``(None, None)`` when no ``execute_select`` was attempted.
    """
    last_call_id_to_sql: dict[str, str] = {}
    for msg in messages:
        if isinstance(msg, AIMessage) and getattr(msg, "tool_calls", None):
            for tc in msg.tool_calls:
                if tc.get("name") == "execute_select":
                    args = tc.get("args") or {}
                    sql = args.get("sql") if isinstance(args, dict) else None
                    if isinstance(sql, str) and tc.get("id"):
                        last_call_id_to_sql[tc["id"]] = sql

    last: tuple[dict[str, Any] | None, str | None] = (None, None)
    for msg in messages:
        if isinstance(msg, ToolMessage) and msg.name == "execute_select":
            content = msg.content if isinstance(msg.content, str) else str(msg.content)
            try:
                parsed = json.loads(content)
            except (json.JSONDecodeError, TypeError):
                parsed = {"error": "execute_select returned non-JSON content"}
            sql = last_call_id_to_sql.get(msg.tool_call_id or "")
            last = (parsed, sql)
    return last


def _final_assistant_text(messages: list[BaseMessage]) -> str:
    """Return the text of the last AIMessage that has no tool calls."""
    for msg in reversed(messages):
        if isinstance(msg, AIMessage) and not getattr(msg, "tool_calls", None):
            return msg.content if isinstance(msg.content, str) else str(msg.content)
    return ""


def _result_to_data_preview(
    rows: list[dict[str, Any]], cap: int = 10
) -> list[dict[str, Any]]:
    if not rows:
        return []
    return json.loads(json.dumps(rows[:cap], default=_json_default))


# ---------------------------------------------------------------------------
# Run a single LangChain agent stage (compiled LangGraph under the hood)
# ---------------------------------------------------------------------------


def _run_stage(
    *,
    chat_model,
    tools: list[Any],
    system_prompt: str,
    user_prompt: str,
    max_iterations: int,
    stage_name: str = "primary",
) -> list[BaseMessage]:
    """Invoke a create_agent stage and return its full message history."""
    recursion_limit = max_iterations * 2 + 5
    model_name = getattr(chat_model, "model", None) or getattr(
        chat_model, "model_name", "unknown"
    )
    log.info(
        "Stage start: stage=%s model=%s tools=%d max_iter=%d",
        stage_name,
        model_name,
        len(tools),
        max_iterations,
    )
    handler = AgentObservabilityHandler()
    agent = create_agent(model=chat_model, tools=tools, system_prompt=system_prompt)
    t0 = time.perf_counter()
    try:
        state = agent.invoke(
            {"messages": [HumanMessage(content=user_prompt)]},
            config={"recursion_limit": recursion_limit, "callbacks": [handler]},
        )
    except GraphRecursionError:
        elapsed_ms = (time.perf_counter() - t0) * 1000
        log.warning(
            "Stage %s: iteration cap hit (recursion_limit=%d) after %.0f ms",
            stage_name,
            recursion_limit,
            elapsed_ms,
        )
        raise
    elapsed_ms = (time.perf_counter() - t0) * 1000
    msgs = state.get("messages") if isinstance(state, dict) else None
    if not isinstance(msgs, list):
        log.info("Stage %s done: %.0f ms, 0 messages", stage_name, elapsed_ms)
        return []
    log.info("Stage %s done: %.0f ms, %d messages", stage_name, elapsed_ms, len(msgs))
    return msgs


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def _classify_outcome(
    parsed_result: dict[str, Any] | None,
    raw_sql: str | None,
) -> tuple[bool, str, str | None]:
    """Return (success, phase, error_message_or_None) for an execute_select result."""
    if parsed_result is None:
        return False, "no_sql", "Agent finished without calling execute_select."
    if "error" in parsed_result:
        return False, str(parsed_result.get("phase") or "validation"), str(
            parsed_result["error"]
        )
    if "rows" in parsed_result:
        return True, "ok", None
    return False, "no_sql", "execute_select returned an unexpected payload."


def run_ask(request: AgentRequest) -> AgentResult | AgentFailure:
    """Run the primary agent + (if needed) one-shot repair. Synchronous."""
    log.info("run_ask start: question=%.80s", request.question)
    agent_model_id = resolve_agent_model(request.agent_model)
    repair_model_id = resolve_repair_model(request.repair_model)

    layer = {}
    try:
        layer = load_semantic_layer()
    except Exception as exc:
        log.warning("semantic layer load failed (non-fatal): %s", exc)
    answer_style_rules = (
        ((layer.get("answer_style") or {}).get("rules") or []) if isinstance(layer, dict) else []
    )

    user_prompt = build_user_prompt(
        question=request.question,
        conversation_section=request.conversation_section,
        answer_style_rules=list(answer_style_rules) if answer_style_rules else None,
    )

    notes: list[str] = []
    notes.append(f"Used {_PROVIDER_DISPLAY['openrouter']} agent model {agent_model_id}.")

    max_iter = _max_iterations()
    try:
        chat = build_chat_model(agent_model_id)
        primary_msgs = _run_stage(
            chat_model=chat,
            tools=ALL_TOOLS,
            system_prompt=AGENT_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            max_iterations=max_iter,
            stage_name="primary",
        )
    except GraphRecursionError:
        log.warning(
            "run_ask failed: primary stage hit iteration cap (max_iter=%d)", max_iter
        )
        return AgentFailure(
            error=f"Primary agent exceeded iteration cap ({max_iter} iterations).",
            phase="iteration_cap",
            sql=None,
            agent_model=agent_model_id,
            repair_model=repair_model_id,
            notes=notes,
        )
    except Exception as exc:  # noqa: BLE001
        log.exception("Primary agent invocation failed")
        return AgentFailure(
            error=str(exc),
            phase="execution",
            sql=None,
            agent_model=agent_model_id,
            repair_model=repair_model_id,
            notes=notes,
        )

    parsed, raw_sql = _last_execute_select_result(primary_msgs)
    success, phase, err = _classify_outcome(parsed, raw_sql)
    log.info("Primary stage complete: success=%s phase=%s", success, phase)

    if success:
        rows = list(parsed["rows"])  # type: ignore[index]
        sql_used = parsed.get("sql") or raw_sql or ""
        answer = _final_assistant_text(primary_msgs).strip()
        if not answer:
            answer = "_(The agent did not produce a natural-language answer.)_"
        log.info("run_ask done: repaired=False rows=%d", len(rows))
        return AgentResult(
            answer=answer,
            sql=sql_used,
            rows=rows,
            data_preview=_result_to_data_preview(rows),
            agent_model=agent_model_id,
            repair_model=repair_model_id,
            repaired=False,
            notes=notes,
        )

    # --- Repair pass ----------------------------------------------------
    log.info("Repair pass triggered: phase=%s", phase)
    notes.append(
        f"Primary agent failed ({phase}); invoking repair pass with model {repair_model_id}."
    )
    repair_user = build_repair_user_prompt(
        question=request.question,
        failed_sql=raw_sql or "",
        failure_phase=phase,
        failure_message=err or "(unknown)",
        conversation_section=request.conversation_section,
    )
    repair_max_iter = max(3, max_iter // 2)
    try:
        repair_chat = build_chat_model(repair_model_id)
        repair_msgs = _run_stage(
            chat_model=repair_chat,
            tools=REPAIR_TOOLS,
            system_prompt=REPAIR_SYSTEM_PROMPT,
            user_prompt=repair_user,
            max_iterations=repair_max_iter,
            stage_name="repair",
        )
    except GraphRecursionError:
        log.warning(
            "run_ask failed: repair stage hit iteration cap (max_iter=%d)", repair_max_iter
        )
        return AgentFailure(
            error=f"Repair agent exceeded iteration cap ({repair_max_iter} iterations).",
            phase="iteration_cap",
            sql=raw_sql,
            agent_model=agent_model_id,
            repair_model=repair_model_id,
            notes=notes,
        )
    except Exception as exc:  # noqa: BLE001
        log.exception("Repair agent invocation failed")
        return AgentFailure(
            error=f"Repair pass failed: {exc}",
            phase="execution",
            sql=raw_sql,
            agent_model=agent_model_id,
            repair_model=repair_model_id,
            notes=notes,
        )

    parsed_r, raw_sql_r = _last_execute_select_result(repair_msgs)
    success_r, phase_r, err_r = _classify_outcome(parsed_r, raw_sql_r)
    if success_r:
        rows = list(parsed_r["rows"])  # type: ignore[index]
        sql_used = parsed_r.get("sql") or raw_sql_r or ""
        answer = _final_assistant_text(repair_msgs).strip() or _final_assistant_text(
            primary_msgs
        ).strip() or "_(No natural-language answer was produced.)_"
        notes.append("Repair pass succeeded.")
        log.info("run_ask done: repaired=True rows=%d", len(rows))
        return AgentResult(
            answer=answer,
            sql=sql_used,
            rows=rows,
            data_preview=_result_to_data_preview(rows),
            agent_model=agent_model_id,
            repair_model=repair_model_id,
            repaired=True,
            notes=notes,
        )

    notes.append(f"Repair pass also failed ({phase_r}).")
    log.error("run_ask failed: phase=%s error=%.200s", phase_r, err_r or "(none)")
    return AgentFailure(
        error=err_r or "Repair pass produced no usable SQL.",
        phase=phase_r,
        sql=raw_sql_r or raw_sql,
        agent_model=agent_model_id,
        repair_model=repair_model_id,
        notes=notes,
    )


def run_ask_stream(request: AgentRequest) -> Iterator[StreamEvent]:
    """Streaming entrypoint. Runs the agent synchronously then emits SSE events.

    Emits, in order:

    - ``meta`` — ``{sql, data_preview, trace_notes, repaired}``
    - one or more ``answer_delta`` — ``{text}`` (the answer split on paragraph
      boundaries to give a streaming feel without re-invoking the LLM)
    - ``done`` — ``{}``

    On failure: emits ``error`` and stops.
    """
    outcome = run_ask(request)
    if isinstance(outcome, AgentFailure):
        yield StreamEvent(
            "error",
            {
                "message": outcome.error,
                "phase": outcome.phase,
                "sql": outcome.sql,
                "notes": outcome.notes,
            },
        )
        return

    yield StreamEvent(
        "meta",
        {
            "sql": outcome.sql,
            "data_preview": outcome.data_preview,
            "trace_notes": outcome.notes,
            "repaired": outcome.repaired,
        },
    )
    text = outcome.answer
    if text:
        # Coarse "streaming": split on paragraph boundaries; falls back to the
        # whole answer in one delta if there are no blank lines.
        parts = [p for p in text.split("\n\n") if p]
        if not parts:
            parts = [text]
        for chunk in parts:
            yield StreamEvent("answer_delta", {"text": chunk + "\n\n"})
    yield StreamEvent("done", {})


# Re-export for convenience
__all__ = [
    "AgentRequest",
    "AgentResult",
    "AgentFailure",
    "StreamEvent",
    "run_ask",
    "run_ask_stream",
    "execute_select",
    "build_answer_semantic_context",
]
