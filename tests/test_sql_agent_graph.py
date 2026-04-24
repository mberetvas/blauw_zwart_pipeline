"""Tests for the LangGraph SQL-agent orchestration."""

from __future__ import annotations

import importlib
import json
from pathlib import Path
from typing import Any

import pytest
import yaml
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage


class FakeToolChatModel(GenericFakeChatModel):
    """GenericFakeChatModel that pretends to support bind_tools."""

    def bind_tools(self, tools, **kwargs):  # type: ignore[override]
        return self


@pytest.fixture()
def graph_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("LLM_CONFIG_PATH", str(tmp_path / "llm_config.json"))
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test-fixture-key")
    monkeypatch.setenv("OPENROUTER_AGENT_MODEL", "openrouter/test-agent")
    monkeypatch.setenv("OPENROUTER_REPAIR_MODEL", "openrouter/test-repair")
    monkeypatch.setenv("DBT_RELATION_SCHEMA", "dbt_dev")
    monkeypatch.delenv("LLM_PROVIDER", raising=False)

    schema_file = tmp_path / "schema.yml"
    schema_file.write_text(
        yaml.dump(
            {"models": [{"name": "mart_fan_loyalty", "columns": []}]}
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("SCHEMA_FILE", str(schema_file))

    semantic_file = tmp_path / "semantic_layer.yml"
    semantic_file.write_text(
        yaml.dump(
            {
                "version": 1,
                "subjects": [],
                "metrics": [],
                "dimensions": [],
                "join_paths": [],
                "layering_rules": [],
                "answer_style": {"rules": ["Use EUR units."]},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("SEMANTIC_LAYER_FILE", str(semantic_file))

    import frontend_app.sql_agent.llm_runtime_config as cfg
    importlib.reload(cfg)
    cfg.init_llm_config()

    import frontend_app.sql_agent.graph as graph
    import frontend_app.sql_agent.providers as providers
    import frontend_app.sql_agent.tools as tools
    importlib.reload(providers)
    importlib.reload(tools)
    importlib.reload(graph)
    return graph


def _ai_tool_call(name: str, args: dict[str, Any], call_id: str) -> AIMessage:
    return AIMessage(
        content="",
        tool_calls=[{"name": name, "args": args, "id": call_id, "type": "tool_call"}],
    )


def _ai_final(text: str) -> AIMessage:
    return AIMessage(content=text)


def test_run_ask_happy_path(graph_env, monkeypatch: pytest.MonkeyPatch) -> None:
    """Primary agent calls execute_select successfully and returns an answer."""
    captured_models: list[str] = []

    fake_messages = iter(
        [
            _ai_tool_call("execute_select", {"sql": "SELECT 1 AS x"}, "call_1"),
            _ai_final("There is one row with x=1."),
        ]
    )

    def fake_build_chat_model(model: str, **_kw):
        captured_models.append(model)
        return FakeToolChatModel(messages=fake_messages)

    def fake_execute_select_func(sql: str) -> str:
        return json.dumps({"rows": [{"x": 1}], "row_count": 1, "sql": sql})

    monkeypatch.setattr(graph_env, "build_chat_model", fake_build_chat_model)
    # Patch the underlying execute_select tool callable
    monkeypatch.setattr(graph_env.execute_select, "func", fake_execute_select_func)

    request = graph_env.AgentRequest(question="How many rows?")
    result = graph_env.run_ask(request)

    assert isinstance(result, graph_env.AgentResult)
    assert result.sql == "SELECT 1 AS x"
    assert result.rows == [{"x": 1}]
    assert result.data_preview == [{"x": 1}]
    assert "x=1" in result.answer
    assert result.repaired is False
    assert captured_models == ["openrouter/test-agent"]


def test_run_ask_repair_succeeds_with_different_model(
    graph_env, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Primary fails sqlglot validation; repair model fixes the SQL and succeeds."""
    captured_models: list[str] = []

    primary_messages = iter(
        [
            _ai_tool_call("execute_select", {"sql": "DROP TABLE x"}, "call_p1"),
            _ai_final("(unable to answer)"),
        ]
    )
    repair_messages = iter(
        [
            _ai_tool_call("execute_select", {"sql": "SELECT 42 AS y"}, "call_r1"),
            _ai_final("Fixed: y=42."),
        ]
    )

    def fake_build_chat_model(model: str, **_kw):
        captured_models.append(model)
        if "repair" in model:
            return FakeToolChatModel(messages=repair_messages)
        return FakeToolChatModel(messages=primary_messages)

    call_count = {"n": 0}

    def fake_execute_select_func(sql: str) -> str:
        call_count["n"] += 1
        if "DROP" in sql.upper():
            return json.dumps({"error": "mutating statement", "phase": "validation", "sql": sql})
        return json.dumps({"rows": [{"y": 42}], "row_count": 1, "sql": sql})

    monkeypatch.setattr(graph_env, "build_chat_model", fake_build_chat_model)
    monkeypatch.setattr(graph_env.execute_select, "func", fake_execute_select_func)

    request = graph_env.AgentRequest(question="What's the answer?")
    result = graph_env.run_ask(request)

    assert isinstance(result, graph_env.AgentResult)
    assert result.repaired is True
    assert result.rows == [{"y": 42}]
    assert result.sql == "SELECT 42 AS y"
    # Both models should have been built.
    assert "openrouter/test-agent" in captured_models
    assert "openrouter/test-repair" in captured_models
    # Repair note is recorded.
    assert any("repair" in n.lower() for n in result.notes)


def test_run_ask_repair_exhausted_returns_failure(
    graph_env, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Both primary and repair fail validation -> AgentFailure with phase=validation."""
    primary_messages = iter(
        [
            _ai_tool_call("execute_select", {"sql": "DROP TABLE x"}, "call_p1"),
            _ai_final("(failed)"),
        ]
    )
    repair_messages = iter(
        [
            _ai_tool_call("execute_select", {"sql": "INSERT INTO x VALUES (1)"}, "call_r1"),
            _ai_final("(also failed)"),
        ]
    )

    def fake_build_chat_model(model: str, **_kw):
        if "repair" in model:
            return FakeToolChatModel(messages=repair_messages)
        return FakeToolChatModel(messages=primary_messages)

    def fake_execute_select_func(sql: str) -> str:
        return json.dumps({"error": f"refused: {sql}", "phase": "validation", "sql": sql})

    monkeypatch.setattr(graph_env, "build_chat_model", fake_build_chat_model)
    monkeypatch.setattr(graph_env.execute_select, "func", fake_execute_select_func)

    result = graph_env.run_ask(graph_env.AgentRequest(question="bad"))

    assert isinstance(result, graph_env.AgentFailure)
    assert result.phase == "validation"
    assert result.sql is not None


def test_run_ask_no_execute_select_returns_failure(
    graph_env, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Agent never calls execute_select -> repair pass also doesn't, -> AgentFailure no_sql."""
    primary_messages = iter([_ai_final("I refuse to answer.")])
    repair_messages = iter([_ai_final("I also refuse.")])

    def fake_build_chat_model(model: str, **_kw):
        if "repair" in model:
            return FakeToolChatModel(messages=repair_messages)
        return FakeToolChatModel(messages=primary_messages)

    monkeypatch.setattr(graph_env, "build_chat_model", fake_build_chat_model)

    result = graph_env.run_ask(graph_env.AgentRequest(question="anything"))

    assert isinstance(result, graph_env.AgentFailure)
    assert result.phase == "no_sql"


def test_run_ask_stream_emits_meta_then_delta_then_done(
    graph_env, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_messages = iter(
        [
            _ai_tool_call("execute_select", {"sql": "SELECT 1 AS x"}, "call_1"),
            _ai_final("Paragraph one.\n\nParagraph two."),
        ]
    )

    def fake_build_chat_model(model: str, **_kw):
        return FakeToolChatModel(messages=fake_messages)

    def fake_execute_select_func(sql: str) -> str:
        return json.dumps({"rows": [{"x": 1}], "row_count": 1, "sql": sql})

    monkeypatch.setattr(graph_env, "build_chat_model", fake_build_chat_model)
    monkeypatch.setattr(graph_env.execute_select, "func", fake_execute_select_func)

    events = list(graph_env.run_ask_stream(graph_env.AgentRequest(question="q")))
    names = [e.name for e in events]
    assert names[0] == "meta"
    assert names[-1] == "done"
    assert "answer_delta" in names
    # First meta event carries the SQL and preview.
    assert events[0].data["sql"] == "SELECT 1 AS x"
    assert events[0].data["data_preview"] == [{"x": 1}]


def test_run_ask_stream_failure_emits_error_event(
    graph_env, monkeypatch: pytest.MonkeyPatch
) -> None:
    primary_messages = iter([_ai_final("nope")])
    repair_messages = iter([_ai_final("also nope")])

    def fake_build_chat_model(model: str, **_kw):
        if "repair" in model:
            return FakeToolChatModel(messages=repair_messages)
        return FakeToolChatModel(messages=primary_messages)

    monkeypatch.setattr(graph_env, "build_chat_model", fake_build_chat_model)

    events = list(graph_env.run_ask_stream(graph_env.AgentRequest(question="q")))
    assert len(events) == 1
    assert events[0].name == "error"
    assert "phase" in events[0].data
