from __future__ import annotations

import pytest

from llm_api.schema_context import (
    SchemaContextOverflowError,
    build_schema_context_text,
)


@pytest.fixture(autouse=True)
def clear_schema_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in (
        "SCHEMA_FILES",
        "DBT_MODELS_DIR",
        "SCHEMA_FILE",
        "SCHEMA_CONTEXT_MAX_CHARS",
        "SCHEMA_CONTEXT_OVERFLOW",
        "DBT_RELATION_SCHEMA",
    ):
        monkeypatch.delenv(key, raising=False)


def test_dbt_models_dir_orders_staging_before_marts(tmp_path, monkeypatch) -> None:
    root = tmp_path / "dbt_schema"
    (root / "staging").mkdir(parents=True)
    (root / "marts").mkdir(parents=True)
    (root / "staging" / "fan_schema.yaml").write_text(
        "version: 2\n"
        "models:\n"
        "  - name: z_staging_last_alpha\n"
        "    columns: []\n",
        encoding="utf-8",
    )
    (root / "marts" / "schema.yml").write_text(
        "version: 2\n"
        "models:\n"
        "  - name: a_mart_first_alpha\n"
        "    columns: []\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("DBT_MODELS_DIR", str(root))
    text = build_schema_context_text()
    assert "Layer: staging" in text
    assert "Layer: marts" in text
    pos_staging = text.index("Table: z_staging_last_alpha")
    pos_mart = text.index("Table: a_mart_first_alpha")
    assert pos_staging < pos_mart


def test_schema_files_duplicate_model_last_file_wins(tmp_path, monkeypatch, caplog) -> None:
    caplog.set_level("WARNING")
    first = tmp_path / "one" / "staging"
    second = tmp_path / "two" / "staging"
    first.mkdir(parents=True)
    second.mkdir(parents=True)
    (first / "a.yaml").write_text(
        "version: 2\n"
        "models:\n"
        "  - name: same_model\n"
        "    description: from first file\n"
        "    columns: []\n",
        encoding="utf-8",
    )
    (second / "b.yaml").write_text(
        "version: 2\n"
        "models:\n"
        "  - name: same_model\n"
        "    description: from second file\n"
        "    columns: []\n",
        encoding="utf-8",
    )
    monkeypatch.setenv(
        "SCHEMA_FILES",
        f"{first / 'a.yaml'},{second / 'b.yaml'}",
    )
    text = build_schema_context_text()
    assert "from second file" in text
    assert "from first file" not in text
    assert any("same_model" in r.message for r in caplog.records)


def test_column_without_description_renders(tmp_path, monkeypatch) -> None:
    y = tmp_path / "marts" / "schema.yml"
    y.parent.mkdir(parents=True)
    y.write_text(
        "version: 2\n"
        "models:\n"
        "  - name: t\n"
        "    columns:\n"
        "      - name: bare\n"
        "        data_type: int\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("SCHEMA_FILE", str(y))
    text = build_schema_context_text()
    assert "  - bare (int):" in text


def test_schema_context_overflow_error(tmp_path, monkeypatch) -> None:
    y = tmp_path / "marts" / "schema.yml"
    y.parent.mkdir(parents=True)
    y.write_text(
        "version: 2\n"
        "models:\n"
        "  - name: x\n"
        "    columns: []\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("SCHEMA_FILE", str(y))
    monkeypatch.setenv("SCHEMA_CONTEXT_MAX_CHARS", "20")
    monkeypatch.setenv("SCHEMA_CONTEXT_OVERFLOW", "error")
    with pytest.raises(SchemaContextOverflowError, match="Schema context is"):
        build_schema_context_text()


def test_schema_context_overflow_truncate(tmp_path, monkeypatch) -> None:
    y = tmp_path / "marts" / "schema.yml"
    y.parent.mkdir(parents=True)
    y.write_text(
        "version: 2\n"
        "models:\n"
        "  - name: x\n"
        "    columns: []\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("SCHEMA_FILE", str(y))
    monkeypatch.setenv("SCHEMA_CONTEXT_MAX_CHARS", "120")
    monkeypatch.setenv("SCHEMA_CONTEXT_OVERFLOW", "truncate")
    text = build_schema_context_text()
    assert "[SCHEMA CONTEXT TRUNCATED]" in text
    assert len(text) <= 120


def test_single_schema_file_backward_compatible(tmp_path, monkeypatch) -> None:
    y = tmp_path / "only.yml"
    y.write_text(
        "version: 2\n"
        "models:\n"
        "  - name: solo\n"
        "    description: only\n"
        "    columns: []\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("SCHEMA_FILE", str(y))
    text = build_schema_context_text()
    assert "Table: solo" in text
    assert "Layer: unspecified" in text


def test_invalid_overflow_mode(tmp_path, monkeypatch) -> None:
    y = tmp_path / "marts" / "schema.yml"
    y.parent.mkdir(parents=True)
    y.write_text("version: 2\nmodels:\n  - name: x\n    columns: []\n", encoding="utf-8")
    monkeypatch.setenv("SCHEMA_FILE", str(y))
    monkeypatch.setenv("SCHEMA_CONTEXT_MAX_CHARS", "10")
    monkeypatch.setenv("SCHEMA_CONTEXT_OVERFLOW", "nope")
    with pytest.raises(ValueError, match="SCHEMA_CONTEXT_OVERFLOW"):
        build_schema_context_text()
