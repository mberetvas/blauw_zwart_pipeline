"""Unit tests for sql_agent.observability: ContextVar request id + callback handler."""

from __future__ import annotations

import asyncio
from uuid import uuid4

import pytest

from frontend_app.sql_agent import observability as obs


def test_new_request_id_is_8_hex() -> None:
    rid = obs.new_request_id()
    assert len(rid) == 8
    int(rid, 16)  # parses as hex


def test_request_id_set_get_reset_round_trip() -> None:
    assert obs.get_request_id() == "-"
    token = obs.set_request_id("abc123")
    assert obs.get_request_id() == "abc123"
    obs.reset_request_id(token)
    assert obs.get_request_id() == "-"


def test_request_id_isolated_across_async_tasks() -> None:
    async def runner() -> tuple[str, str]:
        async def task(value: str) -> str:
            obs.set_request_id(value)
            await asyncio.sleep(0)
            return obs.get_request_id()

        return await asyncio.gather(task("AAA"), task("BBB"))

    a, b = asyncio.run(runner())
    assert {a, b} == {"AAA", "BBB"}


# ---------------------------------------------------------------------------
# AgentObservabilityHandler
# ---------------------------------------------------------------------------


def test_handler_emits_progress_and_records_timing() -> None:
    events: list[dict] = []
    handler = obs.AgentObservabilityHandler(progress_sink=events.append, phase="primary")

    run_id = uuid4()
    handler.on_chat_model_start(
        {"name": "x-ai/grok-4.1-fast", "kwargs": {"model": "x-ai/grok-4.1-fast"}},
        [],
        run_id=run_id,
    )

    class _Result:  # minimal stand-in for LLMResult
        pass

    handler.on_llm_end(_Result(), run_id=run_id)

    step_keys = [e["step_key"] for e in events]
    assert step_keys == ["llm_start", "llm_done"]
    done = events[-1]
    assert done["model"] == "x-ai/grok-4.1-fast"
    assert done["phase"] == "primary"
    assert "elapsed_ms" in done


def test_handler_on_llm_error_emits_error_event() -> None:
    events: list[dict] = []
    handler = obs.AgentObservabilityHandler(progress_sink=events.append)

    run_id = uuid4()
    handler.on_llm_start({"name": "m"}, [], run_id=run_id)
    handler.on_llm_error(RuntimeError("boom"), run_id=run_id)

    assert events[-1]["step_key"] == "llm_error"
    assert events[-1]["error"] == "boom"


def test_handler_tool_lifecycle() -> None:
    events: list[dict] = []
    handler = obs.AgentObservabilityHandler(progress_sink=events.append)

    run_id = uuid4()
    handler.on_tool_start({"name": "list_tables"}, "input here", run_id=run_id)
    handler.on_tool_end("output rows", run_id=run_id)

    keys = [e["step_key"] for e in events]
    assert keys == ["tool_start", "tool_done"]
    assert events[0]["tool"] == "list_tables"
    assert events[0]["args_preview"] == "input here"


def test_handler_tool_error_emits_error_event() -> None:
    events: list[dict] = []
    handler = obs.AgentObservabilityHandler(progress_sink=events.append)

    run_id = uuid4()
    handler.on_tool_start({"name": "execute_select"}, "...", run_id=run_id)
    handler.on_tool_error(ValueError("bad sql"), run_id=run_id)

    assert events[-1]["step_key"] == "tool_error"
    assert events[-1]["error"] == "bad sql"


def test_handler_progress_sink_failure_is_swallowed() -> None:
    def boom(_: dict) -> None:
        raise RuntimeError("sink down")

    handler = obs.AgentObservabilityHandler(progress_sink=boom)
    # Must not raise.
    handler.on_chat_model_start({"name": "m"}, [], run_id=uuid4())


def test_handler_without_progress_sink_no_op() -> None:
    handler = obs.AgentObservabilityHandler(progress_sink=None)
    run_id = uuid4()
    handler.on_chat_model_start({"name": "m"}, [], run_id=run_id)

    class _Result:
        pass

    handler.on_llm_end(_Result(), run_id=run_id)


def test_extract_model_falls_back_to_unknown() -> None:
    assert obs.AgentObservabilityHandler._extract_model({}) == "unknown"


def test_extract_model_uses_kwargs_model_first() -> None:
    out = obs.AgentObservabilityHandler._extract_model({"name": "fallback", "kwargs": {"model": "preferred"}})
    assert out == "preferred"


def test_pop_run_handles_missing_run_id() -> None:
    handler = obs.AgentObservabilityHandler()
    meta = handler._pop_run(uuid4())
    assert meta["name"] == "unknown"
    assert meta["elapsed_ms"] == 0.0


@pytest.mark.parametrize("rid", ["short", "abcdef0123"])
def test_set_request_id_accepts_arbitrary_strings(rid: str) -> None:
    token = obs.set_request_id(rid)
    try:
        assert obs.get_request_id() == rid
    finally:
        obs.reset_request_id(token)
