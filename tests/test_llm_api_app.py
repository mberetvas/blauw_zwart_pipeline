from __future__ import annotations

import importlib
import json
from pathlib import Path

import pytest


@pytest.fixture()
def llm_app_module(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    config_path = tmp_path / "llm_config.json"
    monkeypatch.setenv("LLM_CONFIG_PATH", str(config_path))
    monkeypatch.setenv("OLLAMA_URL", "http://localhost:11434")
    monkeypatch.setenv("OLLAMA_MODEL", "gemma4:e2b")
    monkeypatch.setenv("OLLAMA_TIMEOUT", "120")
    monkeypatch.setenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
    monkeypatch.setenv("OPENROUTER_MODEL", "mistralai/mistral-7b-instruct:free")
    monkeypatch.setenv("OPENROUTER_TIMEOUT", "120")
    monkeypatch.setenv("OPENROUTER_API_KEY", "")
    monkeypatch.setenv("LLM_PROVIDER", "ollama")

    runtime_config = importlib.import_module("llm_api.llm_runtime_config")
    importlib.reload(runtime_config)
    app_module = importlib.import_module("llm_api.app")
    app_module = importlib.reload(app_module)
    return app_module


def test_validate_sql_allows_select_and_with(llm_app_module) -> None:
    llm_app_module._validate_sql("SELECT 1")
    llm_app_module._validate_sql(
        "WITH latest AS (SELECT 1 AS fan_id) SELECT fan_id FROM latest"
    )


def test_validate_sql_rejects_mutating_keyword(llm_app_module) -> None:
    with pytest.raises(ValueError, match="forbidden keyword 'DELETE'"):
        llm_app_module._validate_sql(
            "WITH removed AS (DELETE FROM fans RETURNING id) SELECT id FROM removed"
        )


def test_strip_fences_removes_markdown_and_trailing_semicolons(llm_app_module) -> None:
    raw = "```sql\nWITH latest AS (SELECT 1 AS fan_id)\nSELECT fan_id FROM latest;\n```"
    assert (
        llm_app_module._strip_fences(raw)
        == "WITH latest AS (SELECT 1 AS fan_id)\nSELECT fan_id FROM latest"
    )


def test_llm_config_routes_mask_and_persist_key(llm_app_module) -> None:
    client = llm_app_module.app.test_client()

    put_response = client.put(
        "/api/llm-config",
        json={
            "default_provider": "openrouter",
            "ollama_url": "http://localhost:11434/",
            "ollama_model": "gemma4:e2b",
            "ollama_timeout": 45,
            "openrouter_base_url": "https://openrouter.ai/api/v1/",
            "openrouter_model": "openai/gpt-4.1-mini",
            "openrouter_timeout": 90,
            "openrouter_api_key": "sk-test-1234",
        },
    )

    assert put_response.status_code == 200
    body = put_response.get_json()
    assert body["default_provider"] == "openrouter"
    assert body["ollama_timeout"] == 45
    assert body["openrouter_timeout"] == 90
    assert body["openrouter_api_key_configured"] is True
    assert body["openrouter_api_key_masked"] == "****1234"
    assert "sk-test-1234" not in json.dumps(body)

    get_response = client.get("/api/llm-config")
    assert get_response.status_code == 200
    public_body = get_response.get_json()
    assert public_body["openrouter_api_key_masked"] == "****1234"
    assert public_body["openrouter_api_key_configured"] is True

    persisted = json.loads(Path(public_body["config_file"]).read_text(encoding="utf-8"))
    assert persisted["openrouter_api_key"] == "sk-test-1234"
    assert persisted["ollama_url"] == "http://localhost:11434"
    assert persisted["openrouter_base_url"] == "https://openrouter.ai/api/v1"


def test_ask_route_accepts_cte_sql_and_returns_answer(
    llm_app_module, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(llm_app_module, "load_schema_context", lambda: "Table: fans")
    monkeypatch.setattr(
        llm_app_module,
        "complete",
        lambda prompt, provider, model: (
            "```sql\nWITH latest AS (SELECT 1 AS fan_id)\nSELECT fan_id FROM latest;\n```"
            if "SQL:" in prompt
            else "Fan 1 is the latest supporter in the result set."
        ),
    )
    monkeypatch.setattr(llm_app_module, "_execute_sql", lambda sql: [{"fan_id": 1}])

    response = llm_app_module.app.test_client().post(
        "/api/ask",
        json={"question": "Who is the latest fan?", "provider": "ollama"},
    )

    assert response.status_code == 200
    body = response.get_json()
    assert body["sql"] == "WITH latest AS (SELECT 1 AS fan_id)\nSELECT fan_id FROM latest"
    assert body["answer"] == "Fan 1 is the latest supporter in the result set."
    assert body["data_preview"] == [{"fan_id": 1}]
