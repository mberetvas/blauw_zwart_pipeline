from __future__ import annotations

import importlib
import json
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest
import yaml


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
    assert isinstance(public_body.get("openrouter_models"), list)
    assert len(public_body["openrouter_models"]) >= 1

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


def _parse_sse_events(text: str) -> list[tuple[str, dict]]:
    events: list[tuple[str, dict]] = []
    for block in text.split("\n\n"):
        if not block.strip():
            continue
        ev = "message"
        data_line: str | None = None
        for line in block.split("\n"):
            if line.startswith("event:"):
                ev = line[6:].strip()
            elif line.startswith("data:"):
                data_line = line[5:].lstrip()
        if data_line is not None and data_line != "":
            events.append((ev, json.loads(data_line)))
    return events


def test_ask_stream_returns_sse_meta_deltas_done(
    llm_app_module, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(llm_app_module, "load_schema_context", lambda: "Table: fans")

    def fake_complete(prompt: str, provider: str, model: str) -> str:
        if "SQL:" in prompt:
            return (
                "```sql\nWITH latest AS (SELECT 1 AS fan_id)\n"
                "SELECT fan_id FROM latest;\n```"
            )
        raise AssertionError("complete must not be used for the answer step in /stream")

    monkeypatch.setattr(llm_app_module, "complete", fake_complete)
    monkeypatch.setattr(llm_app_module, "_execute_sql", lambda sql: [{"fan_id": 1}])
    monkeypatch.setattr(
        llm_app_module,
        "_iter_answer_stream",
        lambda provider, model, answer_prompt: iter(["Hel", "lo"]),
    )

    response = llm_app_module.app.test_client().post(
        "/api/ask/stream",
        json={"question": "Who is the latest fan?", "provider": "ollama"},
    )

    assert response.status_code == 200
    assert response.content_type is not None
    assert "text/event-stream" in response.content_type
    assert response.headers.get("Cache-Control") == "no-cache"

    text = response.get_data(as_text=True)
    events = _parse_sse_events(text)
    types = [e[0] for e in events]
    assert types == ["meta", "answer_delta", "answer_delta", "done"]

    meta = events[0][1]
    assert meta["sql"] == "WITH latest AS (SELECT 1 AS fan_id)\nSELECT fan_id FROM latest"
    assert meta["data_preview"] == [{"fan_id": 1}]
    assert "trace" in meta

    assert events[1][1]["text"] == "Hel"
    assert events[2][1]["text"] == "lo"
    assert events[3][1] == {}


def test_ask_stream_pre_stream_validation_returns_json(
    llm_app_module, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(llm_app_module, "load_schema_context", lambda: "Table: fans")
    monkeypatch.setattr(
        llm_app_module,
        "complete",
        lambda prompt, provider, model: (
            "DROP TABLE fans;" if "SQL:" in prompt else "n/a"
        ),
    )

    response = llm_app_module.app.test_client().post(
        "/api/ask/stream",
        json={"question": "bad?", "provider": "ollama"},
    )

    assert response.status_code == 422
    body = response.get_json()
    assert body is not None
    assert "error" in body
    assert "text/event-stream" not in (response.content_type or "")


# ---------------------------------------------------------------------------
# Semantic layer integration tests
# ---------------------------------------------------------------------------


def _write_minimal_semantic_yaml(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "version": 1,
        "subjects": [
            {
                "name": "fan",
                "primary_mart": "mart_fan_loyalty",
                "description": "Fan KPIs.",
                "prefer_mart_when": "spend",
                "prefer_event_tables_when": "event detail",
            }
        ],
        "metrics": [
            {
                "name": "total_spend",
                "table": "mart_fan_loyalty",
                "column": "total_spend",
                "aggregation": "sum",
                "unit": "EUR",
                "description": "Total spend.",
            }
        ],
        "dimensions": [],
        "join_paths": [],
        "layering_rules": [
            {"id": "prefer_mart", "description": "Prefer mart for fan KPIs."}
        ],
        "answer_style": {
            "currency_unit": "EUR",
            "decimal_places": 2,
            "rules": ["State monetary values with EUR unit."],
        },
    }
    path.write_text(yaml.dump(data), encoding="utf-8")


def test_sql_prompt_includes_semantic_section(
    llm_app_module, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The prompt sent to `complete` must contain 'SEMANTIC LAYER' when a valid YAML is present."""
    semantic_file = tmp_path / "semantic_layer.yml"
    _write_minimal_semantic_yaml(semantic_file)
    monkeypatch.setenv("SEMANTIC_LAYER_FILE", str(semantic_file))

    captured_prompts: list[str] = []

    def fake_complete(prompt: str, provider: str, model: str) -> str:
        captured_prompts.append(prompt)
        if "SQL:" in prompt:
            return "SELECT 1 AS fan_id"
        return "One fan found."

    monkeypatch.setattr(llm_app_module, "load_schema_context", lambda: "Table: fans")
    monkeypatch.setattr(llm_app_module, "complete", fake_complete)
    monkeypatch.setattr(llm_app_module, "_execute_sql", lambda sql: [{"fan_id": 1}])

    response = llm_app_module.app.test_client().post(
        "/api/ask",
        json={"question": "Who spent the most?", "provider": "ollama"},
    )

    assert response.status_code == 200
    sql_prompt = next(p for p in captured_prompts if "SQL:" in p)
    assert "SEMANTIC LAYER" in sql_prompt
    assert "mart_fan_loyalty" in sql_prompt


def test_answer_prompt_includes_answer_guidelines(
    llm_app_module, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The answer prompt sent to `complete` must contain 'ANSWER GUIDELINES'."""
    semantic_file = tmp_path / "semantic_layer.yml"
    _write_minimal_semantic_yaml(semantic_file)
    monkeypatch.setenv("SEMANTIC_LAYER_FILE", str(semantic_file))

    captured_prompts: list[str] = []

    def fake_complete(prompt: str, provider: str, model: str) -> str:
        captured_prompts.append(prompt)
        if "SQL:" in prompt:
            return "SELECT 1 AS fan_id"
        return "One fan."

    monkeypatch.setattr(llm_app_module, "load_schema_context", lambda: "Table: fans")
    monkeypatch.setattr(llm_app_module, "complete", fake_complete)
    monkeypatch.setattr(llm_app_module, "_execute_sql", lambda sql: [{"fan_id": 1}])

    response = llm_app_module.app.test_client().post(
        "/api/ask",
        json={"question": "Who spent the most?", "provider": "ollama"},
    )

    assert response.status_code == 200
    answer_prompt = next(p for p in captured_prompts if "Answer:" in p)
    assert "ANSWER GUIDELINES" in answer_prompt
    assert "EUR" in answer_prompt


def test_semantic_load_failure_returns_500(
    llm_app_module, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If load_semantic_context raises SemanticLayerError, /api/ask returns HTTP 500."""
    from llm_api.semantic_layer import SemanticLayerError  # noqa: PLC0415

    def boom() -> tuple[str, str]:
        raise SemanticLayerError("test: semantic file is corrupt")

    monkeypatch.setattr(llm_app_module, "load_schema_context", lambda: "Table: fans")
    monkeypatch.setattr(llm_app_module, "load_semantic_context", boom)

    response = llm_app_module.app.test_client().post(
        "/api/ask",
        json={"question": "Who spent the most?", "provider": "ollama"},
    )

    assert response.status_code == 500
    body = response.get_json()
    assert "error" in body
    assert "semantic" in body["error"].lower()


def _sample_leaderboard_rows() -> list[dict[str, object]]:
    return [
        {
            "rank": 1,
            "fan_id": "fan_00002",
            "points": 1550,
            "matches_attended": 10,
            "total_spend": Decimal("520.25"),
            "merch_purchase_count": 3,
            "retail_purchase_count": 5,
        },
        {
            "rank": 2,
            "fan_id": "fan_00003",
            "points": 1490,
            "matches_attended": 9,
            "total_spend": Decimal("575.10"),
            "merch_purchase_count": 4,
            "retail_purchase_count": 2,
        },
        {
            "rank": 3,
            "fan_id": "fan_00001",
            "points": 1310,
            "matches_attended": 8,
            "total_spend": Decimal("470.00"),
            "merch_purchase_count": 2,
            "retail_purchase_count": 2,
        },
    ]


def test_build_leaderboard_payload_shapes_rankings(
    llm_app_module, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(llm_app_module, "_fetch_leaderboard_rows", _sample_leaderboard_rows)
    monkeypatch.setattr(
        llm_app_module,
        "_fetch_fan_of_the_month",
        lambda: {
            "fan_id": "fan_00003",
            "month_ticket_scans": 4,
            "matches_attended": 9,
            "total_spend": Decimal("575.10"),
            "merch_purchase_count": 4,
            "retail_purchase_count": 2,
            "points": 1490,
        },
    )
    monkeypatch.setattr(
        llm_app_module,
        "_fetch_leaderboard_as_of",
        lambda: datetime(2026, 4, 13, 19, 0, tzinfo=timezone.utc),
    )

    payload = llm_app_module._build_leaderboard_payload("all")

    assert payload["window"] == "all"
    assert payload["as_of"] == "2026-04-13T19:00:00Z"
    assert payload["points_formula"] == llm_app_module.LEADERBOARD_POINTS_FORMULA_TEXT
    assert [entry["rank"] for entry in payload["podium"]] == [1, 2, 3]
    assert [entry["fan_id"] for entry in payload["rankings"]] == [
        "fan_00002",
        "fan_00003",
        "fan_00001",
    ]
    assert payload["rankings"][0]["display_name"] == "Fan 00002"
    assert payload["fan_of_the_month"]["fan_id"] == "fan_00003"
    assert payload["fan_of_the_month"]["subtitle_metrics"]["matches"] == 4
    assert payload["fan_of_the_month"]["subtitle_metrics"]["referrals"] is None
    assert payload["fan_of_the_month"]["fallback"] is False
    assert payload["achievement"] is None


def test_leaderboard_route_returns_json_payload(
    llm_app_module, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        llm_app_module,
        "_build_leaderboard_payload",
        lambda window: {
            "window": window,
            "as_of": "2026-04-13T19:00:00Z",
            "points_formula": llm_app_module.LEADERBOARD_POINTS_FORMULA_TEXT,
            "tie_breakers": llm_app_module.LEADERBOARD_TIE_BREAKERS,
            "podium": [
                {
                    "rank": 1,
                    "fan_id": "fan_00002",
                    "display_name": "Fan 00002",
                    "points": 1550,
                    "matches_attended": 10,
                    "total_spend": Decimal("520.25"),
                    "merch_purchase_count": 3,
                    "retail_purchase_count": 5,
                }
            ],
            "rankings": [
                {
                    "rank": 1,
                    "fan_id": "fan_00002",
                    "display_name": "Fan 00002",
                    "points": 1550,
                    "matches_attended": 10,
                    "total_spend": Decimal("520.25"),
                    "merch_purchase_count": 3,
                    "retail_purchase_count": 5,
                }
            ],
            "fan_of_the_month": {
                "fan_id": "fan_00002",
                "display_name": "Fan 00002",
                "points": 1550,
                "matches_attended": 10,
                "total_spend": Decimal("520.25"),
                "subtitle_metrics": {
                    "matches": 4,
                    "spend_eur": Decimal("520.25"),
                    "referrals": None,
                },
                "summary": "4 ticket scans this month · Referrals not tracked",
                "fallback": False,
            },
            "achievement": None,
        },
    )

    response = llm_app_module.app.test_client().get("/api/leaderboard?window=all")

    assert response.status_code == 200
    body = response.get_json()
    assert body["window"] == "all"
    assert body["rankings"][0]["fan_id"] == "fan_00002"
    assert body["rankings"][0]["total_spend"] == 520.25
    assert body["fan_of_the_month"]["subtitle_metrics"]["spend_eur"] == 520.25


def test_leaderboard_route_rejects_unsupported_window(llm_app_module) -> None:
    response = llm_app_module.app.test_client().get("/api/leaderboard?window=season")

    assert response.status_code == 400
    body = response.get_json()
    assert "Unsupported leaderboard window" in body["error"]


def test_leaderboard_route_returns_503_without_database_url(
    llm_app_module, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(llm_app_module, "DATABASE_URL", "")

    response = llm_app_module.app.test_client().get("/api/leaderboard")

    assert response.status_code == 503
    body = response.get_json()
    assert "No database URL" in body["error"]
