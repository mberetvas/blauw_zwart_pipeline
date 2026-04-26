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

   **Exactly one repair pass is allowed per request — it is never retried.**
   The repair agent itself may take several internal tool-call iterations
   (bounded by ``max(3, AGENT_MAX_TOOL_ITERATIONS // 2)``). Exhausting those
   internal iterations is what produces an "exceeded iteration cap (N
   iterations)" error — it does *not* trigger a second repair pass.

If the repair pass also fails, the request returns a 422-equivalent error to
the host. Otherwise the result of whichever stage succeeded becomes the
:class:`AgentResult`.

Public API
----------

``run_ask(request) -> AgentResult``
    Synchronous entrypoint used by ``POST /api/ask``.

``run_ask_stream(request) -> Iterator[StreamEvent]``
    Streaming entrypoint used by ``POST /api/ask/stream``. Runs the agent
    pipeline and emits ``progress`` events while it is running, then emits one
    ``meta`` event with the SQL + data preview, the answer text as
    ``answer_delta`` event(s), and a final ``done`` event. Errors mid-pipeline
    are surfaced as ``error``.
"""

from __future__ import annotations

import json
import os
import queue
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Iterator

from langchain.agents import create_agent
from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    ToolMessage,
)
from langgraph.errors import GraphRecursionError

from common.logging_setup import get_logger

from .database import _json_default
from .llm_runtime_config import resolve_agent_model, resolve_repair_model
from .observability import (
    AgentObservabilityHandler,
    get_request_id,
    reset_request_id,
    set_request_id,
)
from .prompts import (
    AGENT_SYSTEM_PROMPT,
    REPAIR_SYSTEM_PROMPT,
    build_repair_user_prompt,
    build_user_prompt,
)
from .providers import _PROVIDER_DISPLAY, build_chat_model
from .semantic_layer import build_answer_semantic_context, load_semantic_layer
from .tools import ALL_TOOLS, REPAIR_TOOLS, execute_select

log = get_logger(__name__)


def _max_iterations() -> int:
    """Return the maximum number of internal tool-call iterations for the primary agent.

    This cap limits the number of reasoning/tool steps *within a single agent
    invocation*. It is not the number of repair passes — the repair agent is
    always invoked at most once, and uses ``max(3, _max_iterations() // 2)``
    iterations internally.

    Controlled by the ``AGENT_MAX_TOOL_ITERATIONS`` environment variable
    (default 8, capped at 25).
    """
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


ProgressSink = Callable[[dict[str, Any]], None]


def _safe_emit_progress(
    on_progress: ProgressSink | None,
    *,
    step_key: str,
    phase: str,
    model: str | None = None,
    tool: str | None = None,
    elapsed_ms: int | None = None,
    error: str | None = None,
) -> None:
    """Emit a progress event to the caller without raising on failure.

    Constructs a timestamped progress payload and passes it to the provided
    ``on_progress`` callback. Any exception raised by the callback is silently
    swallowed so that telemetry problems never interrupt the answer pipeline.

    Args:
        on_progress: Optional callable that receives progress payload dicts.
            When ``None``, this function is a no-op.
        step_key: Identifier for the pipeline step that just occurred
            (e.g. ``"run_start"``, ``"tool_done"``, ``"repair_start"``).
        phase: The active pipeline phase, typically ``"primary"``,
            ``"repair"``, or ``"final"``.
        model: Optional display name of the LLM model that was active during
            the step. Omitted from the payload when ``None``.
        tool: Optional name of the agent tool that was invoked (e.g.
            ``"execute_select"``). Omitted from the payload when ``None``.
        elapsed_ms: Optional wall-clock duration in milliseconds for the step.
            Omitted from the payload when ``None``.
        error: Optional error message to attach when the step failed.
            Omitted from the payload when ``None``.
    """
    # No-op when no progress sink is registered.
    if on_progress is None:
        return

    # Build the base payload with the fields that are always present.
    payload: dict[str, Any] = {
        "step_key": step_key,
        "phase": phase,
        "ts": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }

    # Attach optional fields only when provided to keep payloads compact.
    if model:
        payload["model"] = model
    if tool:
        payload["tool"] = tool
    if elapsed_ms is not None:
        payload["elapsed_ms"] = elapsed_ms
    if error:
        payload["error"] = error

    # Forward to the caller; swallow any exception so progress telemetry
    # never kills the answer pipeline.
    try:
        on_progress(payload)
    except Exception:
        # Never break answer generation because of progress telemetry.
        return


def _user_progress(raw: dict[str, Any]) -> dict[str, Any]:
    """Map an internal progress payload to a human-readable SSE progress dict.

    Translates low-level pipeline step keys (e.g. ``"tool_start"``,
    ``"llm_done"``) into friendly ``title`` and ``detail`` strings suitable
    for display in the frontend. Unknown step keys fall back to a generic
    "Working on your question" message.

    Args:
        raw: Raw progress payload produced by ``_safe_emit_progress``. Expected
            keys are ``step_key``, ``phase``, ``tool``, ``model``,
            ``elapsed_ms``, ``error``, and ``ts``.

    Returns:
        A dict with the following keys:

        - ``step_key`` (str): The original step key, defaulting to
          ``"progress"`` if absent.
        - ``title`` (str): Short human-readable headline for the step.
        - ``detail`` (str): Longer explanatory sentence for the step.
        - ``phase`` (str): Pipeline phase, defaulting to ``"primary"``.
        - ``ts`` (str): ISO-8601 UTC timestamp, forwarded from ``raw``
          or generated fresh if absent.
    """
    # Extract fields from the raw payload, defaulting to safe fallbacks.
    step = str(raw.get("step_key") or "progress")
    phase = str(raw.get("phase") or "primary")
    tool = str(raw.get("tool") or "")
    model = str(raw.get("model") or "")
    elapsed_ms = raw.get("elapsed_ms")

    # Default copy — overridden below for each recognised step key.
    title = "Working on your question"
    detail = "Running the analysis pipeline."

    if step == "run_start":
        title = "Warming up the clubhouse"
        detail = "Preparing the model and semantic context."
    elif step == "llm_start":
        title = "Thinking through the strategy"
        detail = (
            f"Consulting the language model ({model})."
            if model
            else "Consulting the language model."
        )
    elif step == "llm_done":
        title = "Got a planning update"
        detail = (
            f"Model response received in {elapsed_ms} ms."
            if isinstance(elapsed_ms, int)
            else "Model response received."
        )
    elif step == "tool_start":
        if tool == "list_tables":
            title = "Cleaning the attic"
            detail = "Reviewing available tables."
        elif tool == "describe_table":
            title = "Opening labeled boxes"
            detail = "Inspecting table columns."
        elif tool == "sample_table":
            title = "Peeking inside the cupboard"
            detail = "Sampling rows to validate assumptions."
        elif tool == "execute_select":
            title = "Checking the records"
            detail = "Running a read-only SQL query."
        else:
            title = "Using a data tool"
            detail = f"Executing tool: {tool or 'unknown'}."
    elif step == "tool_done":
        title = "Tool step completed"
        detail = (
            f"{tool or 'Tool'} finished in {elapsed_ms} ms."
            if isinstance(elapsed_ms, int)
            else f"{tool or 'Tool'} finished."
        )
    elif step == "repair_start":
        title = "Calling in a second opinion"
        detail = "Switching to the repair pass to recover from a failed SQL attempt."
    elif step == "finalizing":
        title = "Putting the answer together"
        detail = "Formatting the final response for streaming."
    elif step in {"llm_error", "tool_error", "run_error"}:
        title = "Hit a snag"
        detail = str(raw.get("error") or "A step failed while processing your request.")

    # Assemble the final frontend-ready dict with human-readable strings.
    return {
        "step_key": step,
        "title": title,
        "detail": detail,
        "phase": phase,
        "ts": raw.get("ts") or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }


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
    # First pass: build a map of {tool_call_id → sql} for every execute_select
    # call the agent made, so we can later match each ToolMessage to its SQL.
    last_call_id_to_sql: dict[str, str] = {}
    for msg in messages:
        if isinstance(msg, AIMessage) and getattr(msg, "tool_calls", None):
            for tc in msg.tool_calls:
                if tc.get("name") == "execute_select":
                    args = tc.get("args") or {}
                    sql = args.get("sql") if isinstance(args, dict) else None
                    if isinstance(sql, str) and tc.get("id"):
                        last_call_id_to_sql[tc["id"]] = sql

    # Second pass: walk forward and keep overwriting `last` so we naturally
    # end up with the most recent execute_select ToolMessage.
    last: tuple[dict[str, Any] | None, str | None] = (None, None)
    for msg in messages:
        if isinstance(msg, ToolMessage) and msg.name == "execute_select":
            content = msg.content if isinstance(msg.content, str) else str(msg.content)
            # Parse the tool's JSON response; fall back to an error dict on decode failure.
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


def _result_to_data_preview(rows: list[dict[str, Any]], cap: int = 20) -> list[dict[str, Any]]:
    """Return a JSON-safe preview slice of a query result row set.

    Serialises ``rows`` through ``json.dumps`` / ``json.loads`` using
    ``_json_default`` so that non-serialisable types (e.g. ``datetime``,
    ``Decimal``) are safely coerced. Only the first ``cap`` rows are included
    to keep the SSE payload small.

    Args:
        rows: Full list of row dicts returned by ``execute_select``.
        cap: Maximum number of rows to include in the preview. Defaults to 20.

    Returns:
        A JSON-roundtripped list of at most ``cap`` row dicts. Returns an
        empty list when ``rows`` is empty.
    """
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
    on_progress: ProgressSink | None = None,
) -> list[BaseMessage]:
    """Invoke a single LangChain ``create_agent`` stage and return its message history.

    Builds a ReAct agent from ``chat_model`` and ``tools``, runs it against
    ``user_prompt``, and waits for it to finish. The LangGraph recursion limit
    is derived from ``max_iterations`` as ``max_iterations * 2 + 5`` to give
    the agent enough graph steps while still preventing infinite loops.

    An ``AgentObservabilityHandler`` is attached as a LangChain callback so
    that LLM and tool events are forwarded to ``on_progress`` in real time.

    Args:
        chat_model: An instantiated LangChain chat model (e.g. from
            ``build_chat_model``). Must support tool-calling.
        tools: List of LangChain tool callables available to the agent.
        system_prompt: System-level instruction string injected before the
            conversation.
        user_prompt: The user-turn message that drives this stage (question
            text, repair context, etc.).
        max_iterations: Maximum number of reasoning/tool-call iterations the
            agent may take before a ``GraphRecursionError`` is raised.
        stage_name: Label used in log messages and observability payloads.
            Defaults to ``"primary"``.
        on_progress: Optional callback forwarded to
            ``AgentObservabilityHandler`` for real-time step events.

    Returns:
        The full list of ``BaseMessage`` objects from the completed agent
        state. Returns an empty list if the state dict contains no
        ``"messages"`` key.

    Raises:
        GraphRecursionError: Re-raised without wrapping when the agent
            exhausts its iteration budget so callers can classify it as an
            ``"iteration_cap"`` failure.
    """
    # LangGraph counts individual node visits, not agent iterations, so we
    # multiply by 2 (one LLM node + one tool node per cycle) and add a small
    # buffer for the entry/exit nodes.
    recursion_limit = max_iterations * 2 + 5
    model_name = getattr(chat_model, "model", None) or getattr(chat_model, "model_name", "unknown")
    log.debug(
        "task=stage_invoke previous=model_resolved next=agent_invoke "
        "stage={} model={} tools={} max_iter={}",
        stage_name,
        model_name,
        len(tools),
        max_iterations,
    )

    # Wire up the observability handler so every LLM/tool event emits a
    # progress update back to the SSE stream.
    handler = AgentObservabilityHandler(progress_sink=on_progress, phase=stage_name)

    # Build the ReAct agent graph and run it synchronously.
    agent = create_agent(model=chat_model, tools=tools, system_prompt=system_prompt)
    t0 = time.perf_counter()
    try:
        state = agent.invoke(
            {"messages": [HumanMessage(content=user_prompt)]},
            config={"recursion_limit": recursion_limit, "callbacks": [handler]},
        )
    except GraphRecursionError:
        # Re-raise unchanged so run_ask can classify this as an iteration_cap
        # failure without losing the original exception type.
        elapsed_ms = (time.perf_counter() - t0) * 1000
        log.info(
            "stage_iteration_cap stage={} recursion_limit={} elapsed_ms={:.0f}",
            stage_name,
            recursion_limit,
            elapsed_ms,
        )
        raise
    elapsed_ms = (time.perf_counter() - t0) * 1000

    # Pull the message list from the returned state dict; guard against
    # unexpected state shapes by returning an empty list.
    msgs = state.get("messages") if isinstance(state, dict) else None
    if not isinstance(msgs, list):
        log.info("stage_complete stage={} elapsed_ms={:.0f} messages=0", stage_name, elapsed_ms)
        return []
    log.info(
        "stage_complete stage={} elapsed_ms={:.0f} messages={}",
        stage_name,
        elapsed_ms,
        len(msgs),
    )
    return msgs


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def _classify_outcome(
    parsed_result: dict[str, Any] | None,
    raw_sql: str | None,
) -> tuple[bool, str, str | None]:
    """Classify an ``execute_select`` result into a (success, phase, error) triple.

    Inspects the parsed JSON payload returned by the ``execute_select`` tool
    and decides whether the agent stage should be considered successful.

    Args:
        parsed_result: The JSON-decoded content of the last ``execute_select``
            ``ToolMessage``, or ``None`` if the tool was never called.
        raw_sql: The SQL string the agent passed to ``execute_select``, or
            ``None`` if unavailable. Not used in the classification logic but
            accepted for symmetry with ``_last_execute_select_result``.

    Returns:
        A three-tuple ``(success, phase, error_message)``:

        - ``success`` (bool): ``True`` only when ``parsed_result`` contains a
          ``"rows"`` key with no ``"error"`` key.
        - ``phase`` (str): ``"ok"`` on success; ``"no_sql"`` when the tool was
          never called or returned an unexpected shape; otherwise the value of
          ``parsed_result["phase"]`` (defaulting to ``"validation"``).
        - ``error_message`` (str | None): Human-readable failure description,
          or ``None`` on success.
    """
    # Tool was never called — agent finished without producing any SQL.
    if parsed_result is None:
        return False, "no_sql", "Agent finished without calling execute_select."

    # Tool returned an error payload from the validation or execution layer.
    if "error" in parsed_result:
        return False, str(parsed_result.get("phase") or "validation"), str(parsed_result["error"])

    # Happy path: tool ran successfully and returned rows.
    if "rows" in parsed_result:
        return True, "ok", None

    # Unexpected payload shape — treat as a no-sql failure.
    return False, "no_sql", "execute_select returned an unexpected payload."


def run_ask(
    request: AgentRequest, *, on_progress: ProgressSink | None = None
) -> AgentResult | AgentFailure:
    """Run the primary agent and, if needed, one-shot repair pass synchronously.

    This is the main entrypoint called by ``POST /api/ask``. It executes two
    potential stages in sequence:

    1. **Primary stage** — a full ReAct (reasoning and acting) agent with the complete ``ALL_TOOLS``
       toolset and the ``agent_model``. If it calls ``execute_select``
       successfully, the result is returned immediately as an
       :class:`AgentResult` with ``repaired=False``.

    2. **Repair stage** — triggered only when the primary stage fails (no SQL,
       validation error, or execution error). A second, constrained agent
       using ``REPAIR_TOOLS`` and the ``repair_model`` gets one attempt to
       produce a working query. If it succeeds, an :class:`AgentResult` with
       ``repaired=True`` is returned. If it also fails, an
       :class:`AgentFailure` is returned.

    The repair pass is invoked **at most once**. Exhausting its internal
    iteration cap produces an ``"iteration_cap"`` :class:`AgentFailure` and
    does *not* trigger a further retry.

    Args:
        request: Fully populated :class:`AgentRequest` describing the user
            question, optional conversation context, and optional model
            overrides.
        on_progress: Optional callable that receives real-time progress
            payload dicts (see ``_safe_emit_progress``). Used by
            ``run_ask_stream`` to forward events to SSE clients.

    Returns:
        :class:`AgentResult` when either stage produces a valid
        ``execute_select`` response, or :class:`AgentFailure` when both
        stages fail or an unexpected exception is raised.

    Note:
        The semantic layer is loaded once per call. A load failure is
        non-fatal: answer-style rules are simply omitted from the prompt.
    """
    log.debug(
        "task=run_ask_start previous=request_received next=resolve_models question_preview={}",
        request.question[:80],
    )
    _safe_emit_progress(on_progress, step_key="run_start", phase="primary")

    # Resolve model IDs — may apply env-var overrides on top of request values.
    agent_model_id = resolve_agent_model(request.agent_model)
    repair_model_id = resolve_repair_model(request.repair_model)

    # Load the semantic layer for answer-style rules; failure is non-fatal.
    layer = {}
    try:
        layer = load_semantic_layer()
    except Exception as exc:
        log.info("semantic_layer_load_failed_non_fatal error={}", exc)
    answer_style_rules = (
        ((layer.get("answer_style") or {}).get("rules") or [])
        if isinstance(layer, dict)
        else []
    )

    # Build the final user-turn message combining the question, conversation
    # history, and any answer-style rules from the semantic layer.
    user_prompt = build_user_prompt(
        question=request.question,
        conversation_section=request.conversation_section,
        answer_style_rules=list(answer_style_rules) if answer_style_rules else None,
    )

    # Accumulate diagnostic notes returned in the result for tracing.
    notes: list[str] = []
    notes.append(f"Used {_PROVIDER_DISPLAY['openrouter']} agent model {agent_model_id}.")

    # --- Primary stage: full toolset, unrestricted schema discovery -----------
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
            on_progress=on_progress,
        )
    except GraphRecursionError:
        log.info("run_ask_primary_iteration_cap max_iter={}", max_iter)
        return AgentFailure(
            error=f"Primary agent exceeded iteration cap ({max_iter} iterations).",
            phase="iteration_cap",
            sql=None,
            agent_model=agent_model_id,
            repair_model=repair_model_id,
            notes=notes,
        )
    except Exception as exc:  # noqa: BLE001
        log.info("run_ask_primary_failed error={}", exc)
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
    log.info("run_ask_primary_complete success={} phase={}", success, phase)

    if success:
        # Primary succeeded — extract rows, SQL, and the final prose answer.
        rows = list(parsed["rows"])  # type: ignore[index]
        sql_used = parsed.get("sql") or raw_sql or ""
        answer = _final_assistant_text(primary_msgs).strip()
        if not answer:
            answer = "_(The agent did not produce a natural-language answer.)_"
        log.info("run_ask_complete repaired={} rows={}", False, len(rows))
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

    # --- Repair stage: triggered because the primary stage failed -----------
    log.info("run_ask_repair_triggered phase={}", phase)
    _safe_emit_progress(
        on_progress,
        step_key="repair_start",
        phase="repair",
        error=err,
    )
    notes.append(
        f"Primary agent failed ({phase}); invoking repair pass with model "
        f"{repair_model_id}."
    )

    # Build a targeted repair prompt that includes the failed SQL and the
    # specific error so the repair model can focus on fixing the problem.
    repair_user = build_repair_user_prompt(
        question=request.question,
        failed_sql=raw_sql or "",
        failure_phase=phase,
        failure_message=err or "(unknown)",
        conversation_section=request.conversation_section,
    )
    # The repair agent is invoked exactly once per request — there is no outer
    # retry loop. The iteration cap below only limits its internal tool-call
    # steps. If those are exhausted, the request fails with an
    # "iteration_cap" error and no further repair is attempted.
    # Give the repair agent half the primary budget (min 3) since it only
    # needs to fix one known SQL error, not explore the schema from scratch.
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
            on_progress=on_progress,
        )
    except GraphRecursionError:
        log.info("run_ask_repair_iteration_cap max_iter={}", repair_max_iter)
        return AgentFailure(
            error=f"Repair agent exceeded iteration cap ({repair_max_iter} iterations).",
            phase="iteration_cap",
            sql=raw_sql,
            agent_model=agent_model_id,
            repair_model=repair_model_id,
            notes=notes,
        )
    except Exception as exc:  # noqa: BLE001
        log.info("run_ask_repair_failed error={}", exc)
        return AgentFailure(
            error=f"Repair pass failed: {exc}",
            phase="execution",
            sql=raw_sql,
            agent_model=agent_model_id,
            repair_model=repair_model_id,
            notes=notes,
        )

    # Classify the repair result using the same logic as the primary stage.
    parsed_r, raw_sql_r = _last_execute_select_result(repair_msgs)
    success_r, phase_r, err_r = _classify_outcome(parsed_r, raw_sql_r)
    if success_r:
        # Repair succeeded — prefer the repair agent's answer text, but fall
        # back to the primary agent's text if the repair model stayed silent.
        rows = list(parsed_r["rows"])  # type: ignore[index]
        sql_used = parsed_r.get("sql") or raw_sql_r or ""
        answer = (
            _final_assistant_text(repair_msgs).strip()
            or _final_assistant_text(primary_msgs).strip()
            or "_(No natural-language answer was produced.)_"
        )
        notes.append("Repair pass succeeded.")
        log.info("run_ask_complete repaired={} rows={}", True, len(rows))
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

    # Both stages failed — surface the most recent error to the caller.
    notes.append(f"Repair pass also failed ({phase_r}).")
    log.info("run_ask_failed phase={} error={}", phase_r, (err_r or "(none)")[:200])
    return AgentFailure(
        error=err_r or "Repair pass produced no usable SQL.",
        phase=phase_r,
        sql=raw_sql_r or raw_sql,
        agent_model=agent_model_id,
        repair_model=repair_model_id,
        notes=notes,
    )


def run_ask_stream(request: AgentRequest) -> Iterator[StreamEvent]:
    """Execute the agent pipeline asynchronously with streaming progress events.

    This function runs the SQL agent (primary + optional repair stages) in a
    background worker thread, emitting live progress updates via Server-Sent
    Events (SSE). The main thread yields events as they are produced, enabling
    real-time feedback to HTTP clients without blocking the response.

    Architecture:
    - Worker thread: Executes ``run_ask(request, on_progress=...)`` to
      generate the agent result or failure, invoking the progress callback
      whenever a step completes.
    - Main thread: Reads from a thread-safe queue and yields ``StreamEvent``
      objects to the HTTP response stream. Applies throttling (250ms) to
      prevent duplicate progress events within rapid succession.
    - Synchronization: Uses a ``threading.Event`` to signal completion and
      ensure all queued progress updates are flushed before final result events.

    Event sequence (typical success case):
    1. Multiple "progress" events during agent execution
    2. "meta" event containing the SQL query, data preview, and metadata
    3. One or more "answer_delta" events with answer text (split on paragraph
       boundaries for streaming semantics)
    4. "done" event signaling completion

    On error at any stage, an "error" event is emitted and streaming stops.

    Args:
        request: The validated ``AgentRequest`` containing the user's question
            and optional conversation history.

    Yields:
        StreamEvent: Events with names ``progress``, ``meta``, ``answer_delta``,
        ``error``, or ``done``, in that order. Each event carries a
        ``name: str`` and ``data: dict[str, Any]`` payload.

    Raises:
        (None directly; errors are captured and emitted as ``error`` events)

    Thread Safety:
        Uses ``queue.Queue`` for thread-safe producer–consumer communication
        between worker and main threads. Request context is preserved via
        ``set_request_id`` / ``reset_request_id`` for proper logging.
    """
    # Thread-safe queue: the worker pushes progress dicts, the main thread drains them.
    progress_q: queue.Queue[dict[str, Any]] = queue.Queue()
    # Shared dict: the worker deposits its AgentResult / AgentFailure (or exception) here.
    outcome_box: dict[str, Any] = {}
    # Signals the main drain loop that the worker has finished.
    done_evt = threading.Event()
    # Capture the current request-id so the worker thread inherits it for logging.
    req_id = get_request_id()

    def on_progress(payload: dict[str, Any]) -> None:
        progress_q.put(payload)

    def _worker() -> None:
        # Propagate the request-id into this thread's context variable.
        token = set_request_id(req_id)
        try:
            # Run the full synchronous pipeline; result lands in outcome_box.
            outcome_box["outcome"] = run_ask(request, on_progress=on_progress)
        except Exception as exc:  # noqa: BLE001
            # Capture unexpected exceptions so the main thread can emit an error event.
            outcome_box["error"] = exc
            _safe_emit_progress(
                on_progress,
                step_key="run_error",
                phase="final",
                error=str(exc),
            )
        finally:
            # Signal the drain loop whether we succeeded or failed.
            done_evt.set()
            reset_request_id(token)

    worker = threading.Thread(target=_worker, name="ask-stream-worker", daemon=True)
    worker.start()

    last_progress_sig: tuple[str, str, str, str] | None = None
    last_progress_at = 0.0
    throttle_seconds = 0.25

    # --- Main drain loop: yield progress events while the worker is running ---
    # Blocks on the queue with a short timeout so we can periodically check
    # done_evt without busy-waiting. Exits once the worker is done and the
    # queue is empty.
    while True:
        try:
            raw = progress_q.get(timeout=0.1)
            mapped = _user_progress(raw)
            # Build a dedup signature from the four human-visible fields.
            sig = (
                str(mapped.get("step_key") or ""),
                str(mapped.get("phase") or ""),
                str(mapped.get("title") or ""),
                str(mapped.get("detail") or ""),
            )
            now = time.monotonic()
            # Throttle: skip exact duplicates that arrive within 250 ms.
            if sig == last_progress_sig and (now - last_progress_at) < throttle_seconds:
                continue
            last_progress_sig = sig
            last_progress_at = now
            yield StreamEvent("progress", mapped)
        except queue.Empty:
            # Queue was empty — exit only if the worker has finished.
            if done_evt.is_set():
                break

    # --- Post-completion drain: flush any progress events buffered during
    #     the final worker steps that arrived after done_evt was set. --------
    while True:
        try:
            raw = progress_q.get_nowait()
        except queue.Empty:
            break
        mapped = _user_progress(raw)
        sig = (
            str(mapped.get("step_key") or ""),
            str(mapped.get("phase") or ""),
            str(mapped.get("title") or ""),
            str(mapped.get("detail") or ""),
        )
        if sig == last_progress_sig:
            continue
        last_progress_sig = sig
        yield StreamEvent("progress", mapped)

    # --- Emit result events --------------------------------------------------
    if "error" in outcome_box:
        exc = outcome_box["error"]
        yield StreamEvent("error", {"message": f"Agent stream failed: {exc}"})
        return

    outcome = outcome_box.get("outcome")
    if outcome is None:
        yield StreamEvent("error", {"message": "Agent stream failed: missing outcome."})
        return

    # Emit one final "finalizing" progress tick before assembling the answer.
    _safe_emit_progress(on_progress, step_key="finalizing", phase="final")
    while True:
        try:
            raw = progress_q.get_nowait()
        except queue.Empty:
            break
        mapped = _user_progress(raw)
        sig = (
            str(mapped.get("step_key") or ""),
            str(mapped.get("phase") or ""),
            str(mapped.get("title") or ""),
            str(mapped.get("detail") or ""),
        )
        if sig == last_progress_sig:
            continue
        last_progress_sig = sig
        yield StreamEvent("progress", mapped)

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
        # Coarse streaming: split on paragraph boundaries so the frontend can
        # render text incrementally. Falls back to a single delta when there
        # are no blank lines (e.g. a short one-line answer).
        parts = [p for p in text.split("\n\n") if p]
        if not parts:
            parts = [text]
        for chunk in parts:
            yield StreamEvent("answer_delta", {"text": chunk + "\n\n"})
    # Signal to the client that the full response has been delivered.
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
