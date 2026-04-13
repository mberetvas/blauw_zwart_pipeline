"""Tests for src/llm_api/semantic_layer.py."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_valid_yaml(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "version": 1,
        "subjects": [
            {
                "name": "fan",
                "primary_mart": "mart_fan_loyalty",
                "description": "Fan-level KPIs.",
                "prefer_mart_when": "spend, attendance",
                "prefer_event_tables_when": "event-level detail",
            }
        ],
        "metrics": [
            {
                "name": "total_spend",
                "table": "mart_fan_loyalty",
                "column": "total_spend",
                "aggregation": "sum",
                "unit": "EUR",
                "description": "Combined lifetime spend.",
            }
        ],
        "dimensions": [
            {
                "name": "fan_id",
                "tables": ["mart_fan_loyalty"],
                "description": "Unique fan id.",
            }
        ],
        "join_paths": [
            {
                "from_table": "merch_purchase",
                "to_table": "mart_fan_loyalty",
                "on": "merch_purchase.fan_id = mart_fan_loyalty.fan_id",
            }
        ],
        "layering_rules": [
            {
                "id": "prefer_mart",
                "description": "Always prefer mart for KPIs.",
            }
        ],
        "answer_style": {
            "currency_unit": "EUR",
            "decimal_places": 2,
            "rules": [
                "State monetary values with EUR unit.",
                "Do not hallucinate values.",
            ],
        },
    }
    path.write_text(yaml.dump(data), encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def clear_semantic_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SEMANTIC_LAYER_FILE", raising=False)
    monkeypatch.delenv("SEMANTIC_CONTEXT_MAX_CHARS", raising=False)


# ---------------------------------------------------------------------------
# load_semantic_layer tests
# ---------------------------------------------------------------------------

def test_load_happy_path_returns_expected_keys(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from llm_api import semantic_layer  # noqa: PLC0415  (import inside test intentional)
    import importlib
    importlib.reload(semantic_layer)

    yaml_file = _write_valid_yaml(tmp_path / "semantic_layer.yml")
    monkeypatch.setenv("SEMANTIC_LAYER_FILE", str(yaml_file))
    importlib.reload(semantic_layer)

    layer = semantic_layer.load_semantic_layer()
    assert layer["version"] == 1
    assert isinstance(layer.get("subjects"), list)
    assert isinstance(layer.get("metrics"), list)
    assert isinstance(layer.get("layering_rules"), list)
    assert isinstance(layer.get("answer_style"), dict)


def test_load_missing_explicit_file_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import importlib
    from llm_api import semantic_layer
    importlib.reload(semantic_layer)

    missing = tmp_path / "no_such_file.yml"
    monkeypatch.setenv("SEMANTIC_LAYER_FILE", str(missing))
    importlib.reload(semantic_layer)

    with pytest.raises(semantic_layer.SemanticLayerError, match="missing file"):
        semantic_layer.load_semantic_layer()


def test_load_missing_default_file_returns_empty_gracefully(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """When SEMANTIC_LAYER_FILE is not set and the default file is absent, return {}."""
    import importlib
    from llm_api import semantic_layer
    importlib.reload(semantic_layer)

    # Override _DEFAULT_SEMANTIC_FILE to point somewhere that does not exist.
    monkeypatch.setattr(
        semantic_layer,
        "_DEFAULT_SEMANTIC_FILE",
        tmp_path / "missing_default.yml",
    )
    caplog.set_level("WARNING")

    layer = semantic_layer.load_semantic_layer()
    assert layer == {}
    assert any("semantic layer" in r.message.lower() for r in caplog.records)


def test_load_bad_yaml_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import importlib
    from llm_api import semantic_layer
    importlib.reload(semantic_layer)

    bad = tmp_path / "bad.yml"
    bad.write_text("{invalid: yaml: : :", encoding="utf-8")
    monkeypatch.setenv("SEMANTIC_LAYER_FILE", str(bad))
    importlib.reload(semantic_layer)

    with pytest.raises(semantic_layer.SemanticLayerError, match="not valid YAML"):
        semantic_layer.load_semantic_layer()


def test_load_wrong_version_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import importlib
    from llm_api import semantic_layer
    importlib.reload(semantic_layer)

    yaml_file = tmp_path / "wrong_ver.yml"
    yaml_file.write_text("version: 99\nsubjects: []\n", encoding="utf-8")
    monkeypatch.setenv("SEMANTIC_LAYER_FILE", str(yaml_file))
    importlib.reload(semantic_layer)

    with pytest.raises(semantic_layer.SemanticLayerError, match="version=99"):
        semantic_layer.load_semantic_layer()


def test_load_non_mapping_top_level_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import importlib
    from llm_api import semantic_layer
    importlib.reload(semantic_layer)

    yaml_file = tmp_path / "list.yml"
    yaml_file.write_text("- item1\n- item2\n", encoding="utf-8")
    monkeypatch.setenv("SEMANTIC_LAYER_FILE", str(yaml_file))
    importlib.reload(semantic_layer)

    with pytest.raises(semantic_layer.SemanticLayerError, match="mapping"):
        semantic_layer.load_semantic_layer()


# ---------------------------------------------------------------------------
# build_sql_semantic_context tests
# ---------------------------------------------------------------------------

def test_build_sql_context_contains_mart_and_rules(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import importlib
    from llm_api import semantic_layer
    importlib.reload(semantic_layer)

    yaml_file = _write_valid_yaml(tmp_path / "semantic_layer.yml")
    monkeypatch.setenv("SEMANTIC_LAYER_FILE", str(yaml_file))
    importlib.reload(semantic_layer)

    layer = semantic_layer.load_semantic_layer()
    text = semantic_layer.build_sql_semantic_context(layer)

    assert "mart_fan_loyalty" in text
    assert "LAYERING RULES" in text
    assert "AVAILABLE METRICS" in text
    assert "VALID JOIN PATHS" in text
    assert "total_spend" in text
    assert "EUR" in text


def test_build_sql_context_empty_layer_returns_empty() -> None:
    import importlib
    from llm_api import semantic_layer
    importlib.reload(semantic_layer)

    assert semantic_layer.build_sql_semantic_context({}) == ""


# ---------------------------------------------------------------------------
# build_answer_semantic_context tests
# ---------------------------------------------------------------------------

def test_build_answer_context_contains_units_and_rules(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import importlib
    from llm_api import semantic_layer
    importlib.reload(semantic_layer)

    yaml_file = _write_valid_yaml(tmp_path / "semantic_layer.yml")
    monkeypatch.setenv("SEMANTIC_LAYER_FILE", str(yaml_file))
    importlib.reload(semantic_layer)

    layer = semantic_layer.load_semantic_layer()
    text = semantic_layer.build_answer_semantic_context(layer)

    assert "ANSWER GUIDELINES" in text
    assert "EUR" in text
    assert "hallucinate" in text.lower()


def test_build_answer_context_empty_layer_returns_empty() -> None:
    import importlib
    from llm_api import semantic_layer
    importlib.reload(semantic_layer)

    assert semantic_layer.build_answer_semantic_context({}) == ""


# ---------------------------------------------------------------------------
# SEMANTIC_CONTEXT_MAX_CHARS truncation
# ---------------------------------------------------------------------------

def test_semantic_context_max_chars_truncates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import importlib
    from llm_api import semantic_layer
    importlib.reload(semantic_layer)

    yaml_file = _write_valid_yaml(tmp_path / "semantic_layer.yml")
    monkeypatch.setenv("SEMANTIC_LAYER_FILE", str(yaml_file))
    monkeypatch.setenv("SEMANTIC_CONTEXT_MAX_CHARS", "80")
    importlib.reload(semantic_layer)

    layer = semantic_layer.load_semantic_layer()
    text = semantic_layer.build_sql_semantic_context(layer)

    assert len(text) <= 80
    assert "TRUNCATED" in text
