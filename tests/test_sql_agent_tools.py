"""Tests for the read-only SQL agent tools."""

from __future__ import annotations

import importlib
import json
from pathlib import Path
from typing import Any

import pytest
import yaml


@pytest.fixture()
def tools_module(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("LLM_CONFIG_PATH", str(tmp_path / "llm_config.json"))
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test-fixture-key")
    monkeypatch.setenv("DBT_RELATION_SCHEMA", "dbt_dev")
    monkeypatch.delenv("LLM_PROVIDER", raising=False)

    # Use a single empty schema YAML so YAML index lookups don't crash.
    schema_file = tmp_path / "schema.yml"
    schema_file.write_text(
        yaml.dump(
            {
                "models": [
                    {
                        "name": "mart_fan_loyalty",
                        "description": "Per-fan loyalty roll-up.",
                        "columns": [
                            {
                                "name": "fan_id",
                                "data_type": "text",
                                "description": "Stable fan id.",
                            },
                            {
                                "name": "total_spend",
                                "data_type": "numeric",
                                "description": "Total spend in EUR.",
                            },
                        ],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    # Pretend the file is in a marts/ subdir for layer detection.
    marts_dir = tmp_path / "marts"
    marts_dir.mkdir()
    moved = marts_dir / "schema.yml"
    schema_file.rename(moved)
    monkeypatch.setenv("SCHEMA_FILES", str(moved))

    import frontend_app.sql_agent.llm_runtime_config as runtime_config

    importlib.reload(runtime_config)
    import frontend_app.sql_agent.tools as tools_mod

    importlib.reload(tools_mod)
    return tools_mod


def _stub_run_read(monkeypatch: pytest.MonkeyPatch, tools_mod, mapping):
    """Stub _run_read_query with a callable taking (sql, params) -> rows."""

    def fake(sql, params=None):
        return mapping(sql, params)

    monkeypatch.setattr(tools_mod, "_run_read_query", fake)


def test_list_tables_merges_layer_from_yaml(tools_module, monkeypatch: pytest.MonkeyPatch) -> None:
    def fake(sql: str, params: tuple | None) -> list[dict[str, Any]]:
        assert "information_schema.tables" in sql
        assert params == ("dbt_dev",)
        return [{"table_name": "mart_fan_loyalty"}, {"table_name": "stg_unknown"}]

    _stub_run_read(monkeypatch, tools_module, fake)
    out = json.loads(tools_module.list_tables.invoke({}))
    assert {"name": "mart_fan_loyalty", "layer": "marts"} in out
    assert {"name": "stg_unknown", "layer": "unspecified"} in out


def test_describe_table_rejects_unknown_table(
    tools_module, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fake(sql: str, params: tuple | None):
        if "information_schema.tables" in sql:
            return [{"table_name": "mart_fan_loyalty"}]
        raise AssertionError("describe_table must not query columns for unknown table")

    _stub_run_read(monkeypatch, tools_module, fake)
    out = json.loads(tools_module.describe_table.invoke({"table": "nope; DROP TABLE x"}))
    assert "error" in out
    assert "Invalid table identifier" in out["error"]


def test_describe_table_returns_columns_with_descriptions(
    tools_module, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fake(sql: str, params: tuple | None):
        if "information_schema.tables" in sql:
            return [{"table_name": "mart_fan_loyalty"}]
        if "information_schema.columns" in sql:
            return [
                {"column_name": "fan_id", "data_type": "text", "is_nullable": "NO"},
                {
                    "column_name": "total_spend",
                    "data_type": "numeric",
                    "is_nullable": "YES",
                },
            ]
        raise AssertionError(f"Unexpected SQL: {sql}")

    _stub_run_read(monkeypatch, tools_module, fake)
    out = json.loads(tools_module.describe_table.invoke({"table": "mart_fan_loyalty"}))
    assert out["name"] == "mart_fan_loyalty"
    assert out["layer"] == "marts"
    cols = {c["name"]: c for c in out["columns"]}
    assert cols["fan_id"]["description"] == "Stable fan id."
    assert cols["total_spend"]["nullable"] is True


def test_execute_select_rejects_mutation_with_validation_phase(
    tools_module, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fake_exec(sql: str):
        raise AssertionError("execute_select must not run mutating SQL")

    monkeypatch.setattr(tools_module, "_execute_sql", fake_exec)
    out = json.loads(tools_module.execute_select.invoke({"sql": "DELETE FROM fans"}))
    assert out["phase"] == "validation"
    assert "error" in out


def test_execute_select_runs_valid_select(tools_module, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tools_module, "_execute_sql", lambda sql: [{"fan_id": "F1", "n": 7}])
    out = json.loads(
        tools_module.execute_select.invoke(
            {"sql": "```sql\nSELECT fan_id, COUNT(*) AS n FROM fans GROUP BY fan_id\n```"}
        )
    )
    assert out["row_count"] == 1
    assert out["rows"] == [{"fan_id": "F1", "n": 7}]
    # Markdown fences must be stripped.
    assert "```" not in out["sql"]


def test_execute_select_rewrites_dbt_layer_prefix(
    tools_module, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, str] = {}

    def fake_exec(sql: str):
        captured["sql"] = sql
        return []

    monkeypatch.setattr(tools_module, "_execute_sql", fake_exec)
    tools_module.execute_select.invoke({"sql": "SELECT fan_id FROM marts.mart_fan_loyalty"})
    assert "dbt_dev.mart_fan_loyalty" in captured["sql"]


def test_execute_select_reports_execution_phase_on_db_error(
    tools_module, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fake_exec(sql: str):
        raise RuntimeError("permission denied for relation foo")

    monkeypatch.setattr(tools_module, "_execute_sql", fake_exec)
    out = json.loads(tools_module.execute_select.invoke({"sql": "SELECT 1 AS x"}))
    assert out["phase"] == "execution"
    assert "permission denied" in out["error"]


def test_get_semantic_layer_returns_yaml(
    tools_module, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    sem = tmp_path / "sem.yml"
    sem.write_text(
        yaml.dump(
            {
                "version": 1,
                "subjects": [{"name": "fan", "primary_mart": "mart_fan_loyalty"}],
                "answer_style": {"rules": ["Be concise."]},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("SEMANTIC_LAYER_FILE", str(sem))
    out = json.loads(tools_module.get_semantic_layer.invoke({}))
    assert out["version"] == 1
    assert out["subjects"][0]["name"] == "fan"
