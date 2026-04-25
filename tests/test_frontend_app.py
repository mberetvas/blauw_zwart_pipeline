from __future__ import annotations

import importlib
import json
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest
import yaml

from frontend_app.sql_agent.graph import AgentFailure, AgentResult, StreamEvent


@pytest.fixture()
def llm_app_module(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    config_path = tmp_path / "llm_config.json"
    monkeypatch.setenv("LLM_CONFIG_PATH", str(config_path))
    monkeypatch.setenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
    monkeypatch.setenv("OPENROUTER_MODEL", "mistralai/mistral-7b-instruct:free")
    monkeypatch.setenv("OPENROUTER_TIMEOUT", "120")
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test-fixture-key")
    monkeypatch.delenv("OPENROUTER_AGENT_MODEL", raising=False)
    monkeypatch.delenv("OPENROUTER_REPAIR_MODEL", raising=False)
    monkeypatch.delenv("OLLAMA_URL", raising=False)
    monkeypatch.delenv("OLLAMA_MODEL", raising=False)
    monkeypatch.delenv("OLLAMA_TIMEOUT", raising=False)
    monkeypatch.delenv("LLM_PROVIDER", raising=False)

    runtime_config = importlib.import_module("frontend_app.sql_agent.llm_runtime_config")
    importlib.reload(runtime_config)
    app_module = importlib.import_module("frontend_app.app")
    app_module = importlib.reload(app_module)
    return app_module


def test_validate_sql_allows_select_and_with(llm_app_module) -> None:
    llm_app_module._validate_sql("SELECT 1")
    llm_app_module._validate_sql(
        "WITH latest AS (SELECT 1 AS fan_id) SELECT fan_id FROM latest"
    )


def test_validate_sql_rejects_mutating_keyword(llm_app_module) -> None:
    # sqlglot's AST walk catches the DELETE first; legacy regex remains as second pass.
    with pytest.raises(ValueError, match=r"(?i)delete|mutation not allowed"):
        llm_app_module._validate_sql(
            "WITH removed AS (DELETE FROM fans RETURNING id) SELECT id FROM removed"
        )


def test_validate_sql_rejects_sqlglot_parse_failure(llm_app_module) -> None:
    with pytest.raises(ValueError, match=r"(?i)sqlglot|parse"):
        llm_app_module._validate_sql("SELECT FROM WHERE 1 ===")


def test_validate_sql_rejects_multiple_top_level_statements(llm_app_module) -> None:
    # The legacy regex rejects ';' early, but sqlglot also catches multi-statement input.
    with pytest.raises(ValueError):
        llm_app_module._validate_sql("SELECT 1; SELECT 2")


def test_validate_sql_rejects_ddl_via_ast(llm_app_module) -> None:
    with pytest.raises(ValueError, match=r"(?i)mutation|drop"):
        llm_app_module._validate_sql("DROP TABLE fans")


def test_validate_sql_accepts_complex_cte(llm_app_module) -> None:
    sql = (
        "WITH ranked AS ("
        "  SELECT fan_id, total_spend, "
        "         RANK() OVER (ORDER BY total_spend DESC) AS r "
        "  FROM dbt_dev.mart_fan_loyalty"
        ") "
        "SELECT fan_id, total_spend FROM ranked WHERE r <= 10"
    )
    llm_app_module._validate_sql(sql)


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
            "openrouter_base_url": "https://openrouter.ai/api/v1/",
            "openrouter_model": "openai/gpt-4.1-mini",
            "openrouter_timeout": 90,
            "openrouter_api_key": "sk-test-1234",
            "agent_model": "openai/gpt-4.1-mini",
            "repair_model": "anthropic/claude-3.5-sonnet",
        },
    )

    assert put_response.status_code == 200
    body = put_response.get_json()
    assert body["openrouter_timeout"] == 90
    assert body["openrouter_api_key_configured"] is True
    assert body["openrouter_api_key_masked"] == "****1234"
    assert body["agent_model"] == "openai/gpt-4.1-mini"
    assert body["repair_model"] == "anthropic/claude-3.5-sonnet"
    assert body["resolved_repair_model"] == "anthropic/claude-3.5-sonnet"
    assert "sk-test-1234" not in json.dumps(body)
    # Ollama keys are gone from the public config.
    assert "ollama_url" not in body
    assert "default_provider" not in body

    get_response = client.get("/api/llm-config")
    assert get_response.status_code == 200
    public_body = get_response.get_json()
    assert public_body["openrouter_api_key_masked"] == "****1234"
    assert public_body["openrouter_api_key_configured"] is True
    assert isinstance(public_body.get("openrouter_models"), list)
    assert len(public_body["openrouter_models"]) >= 1

    persisted = json.loads(Path(public_body["config_file"]).read_text(encoding="utf-8"))
    assert persisted["openrouter_api_key"] == "sk-test-1234"
    assert persisted["openrouter_base_url"] == "https://openrouter.ai/api/v1"
    assert persisted["agent_model"] == "openai/gpt-4.1-mini"
    assert persisted["repair_model"] == "anthropic/claude-3.5-sonnet"


def _stub_agent_result(llm_app_module, **overrides):
    defaults = {
        "answer": "Fan 1 is the latest supporter in the result set.",
        "sql": "WITH latest AS (SELECT 1 AS fan_id)\nSELECT fan_id FROM latest",
        "rows": [{"fan_id": 1}],
        "data_preview": [{"fan_id": 1}],
        "agent_model": "openrouter/test-agent",
        "repair_model": "openrouter/test-agent",
        "repaired": False,
        "notes": [],
    }
    defaults.update(overrides)
    return AgentResult(**defaults)


def test_ask_route_returns_answer_from_agent(
    llm_app_module, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, object] = {}

    def fake_run_ask(req):
        captured["request"] = req
        return _stub_agent_result(llm_app_module)

    monkeypatch.setattr(llm_app_module, "run_ask", fake_run_ask)

    response = llm_app_module.app.test_client().post(
        "/api/ask",
        json={"question": "Who is the latest fan?", "provider": "openrouter"},
    )

    assert response.status_code == 200
    body = response.get_json()
    assert body["sql"] == "WITH latest AS (SELECT 1 AS fan_id)\nSELECT fan_id FROM latest"
    assert body["answer"] == "Fan 1 is the latest supporter in the result set."
    assert body["data_preview"] == [{"fan_id": 1}]
    assert body["repaired"] is False
    assert captured["request"].question == "Who is the latest fan?"


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


def test_ask_stream_returns_sse_events_from_agent(
    llm_app_module, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fake_run_ask_stream(req):
        meta_payload = {
            "sql": "SELECT 1",
            "data_preview": [{"x": 1}],
            "trace_notes": [],
            "repaired": False,
        }
        yield StreamEvent("meta", meta_payload)
        yield StreamEvent("answer_delta", {"text": "Hel"})
        yield StreamEvent("answer_delta", {"text": "lo"})
        yield StreamEvent("done", {})

    monkeypatch.setattr(llm_app_module, "run_ask_stream", fake_run_ask_stream)

    response = llm_app_module.app.test_client().post(
        "/api/ask/stream",
        json={"question": "Who is the latest fan?", "provider": "openrouter"},
    )

    assert response.status_code == 200
    assert "text/event-stream" in (response.content_type or "")
    text = response.get_data(as_text=True)
    events = _parse_sse_events(text)
    types = [e[0] for e in events]
    assert types == ["meta", "answer_delta", "answer_delta", "done"]
    assert events[0][1]["sql"] == "SELECT 1"
    assert events[1][1]["text"] == "Hel"
    assert events[2][1]["text"] == "lo"
    assert events[3][1] == {}


def test_ask_stream_passes_through_progress_events(
    llm_app_module, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fake_run_ask_stream(req):
        yield StreamEvent(
            "progress",
            {
                "step_key": "tool_start",
                "title": "Cleaning the attic",
                "detail": "Reviewing available tables.",
                "phase": "primary",
                "ts": "2026-04-25T09:00:00Z",
            },
        )
        yield StreamEvent(
            "meta",
            {
                "sql": "SELECT 1",
                "data_preview": [{"x": 1}],
                "trace_notes": [],
                "repaired": False,
            },
        )
        yield StreamEvent("answer_delta", {"text": "Hi"})
        yield StreamEvent("done", {})

    monkeypatch.setattr(llm_app_module, "run_ask_stream", fake_run_ask_stream)

    response = llm_app_module.app.test_client().post(
        "/api/ask/stream",
        json={"question": "status please", "provider": "openrouter"},
    )

    assert response.status_code == 200
    events = _parse_sse_events(response.get_data(as_text=True))
    assert [e[0] for e in events] == ["progress", "meta", "answer_delta", "done"]
    assert events[0][1]["title"] == "Cleaning the attic"


def test_ask_route_returns_422_on_agent_failure(
    llm_app_module, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fake_run_ask(req):
        return AgentFailure(
            error="SQL contains a forbidden mutating statement",
            phase="validation",
            sql="DROP TABLE fans",
            agent_model="openrouter/test-agent",
            repair_model="openrouter/test-repair",
            notes=[
                "Primary agent failed (validation); invoking repair pass.",
                "Repair pass also failed (validation).",
            ],
        )

    monkeypatch.setattr(llm_app_module, "run_ask", fake_run_ask)

    response = llm_app_module.app.test_client().post(
        "/api/ask",
        json={"question": "drop everything", "provider": "openrouter"},
    )

    assert response.status_code == 422
    body = response.get_json()
    assert "error" in body
    assert body["phase"] == "validation"
    assert body["sql"] == "DROP TABLE fans"


def test_ask_route_passes_model_overrides_to_agent(
    llm_app_module, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, object] = {}

    def fake_run_ask(req):
        captured["request"] = req
        return _stub_agent_result(llm_app_module)

    monkeypatch.setattr(llm_app_module, "run_ask", fake_run_ask)

    llm_app_module.app.test_client().post(
        "/api/ask",
        json={
            "question": "Q",
            "provider": "openrouter",
            "agent_model": "openai/gpt-4.1-mini",
            "repair_model": "anthropic/claude-3.5-sonnet",
        },
    )

    req = captured["request"]
    assert req.agent_model == "openai/gpt-4.1-mini"
    assert req.repair_model == "anthropic/claude-3.5-sonnet"


def test_ask_route_legacy_model_field_treated_as_agent_model(
    llm_app_module, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, object] = {}

    def fake_run_ask(req):
        captured["request"] = req
        return _stub_agent_result(llm_app_module)

    monkeypatch.setattr(llm_app_module, "run_ask", fake_run_ask)

    llm_app_module.app.test_client().post(
        "/api/ask",
        json={"question": "Q", "provider": "openrouter", "model": "openai/gpt-4.1-mini"},
    )

    assert captured["request"].agent_model == "openai/gpt-4.1-mini"


def test_ask_route_passes_history_to_agent(
    llm_app_module, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, object] = {}

    def fake_run_ask(req):
        captured["request"] = req
        return _stub_agent_result(llm_app_module)

    monkeypatch.setattr(llm_app_module, "run_ask", fake_run_ask)

    response = llm_app_module.app.test_client().post(
        "/api/ask",
        json={
            "question": "Can you also tell me what they spent it on?",
            "provider": "openrouter",
            "history": [
                {
                    "question": "Why are these fans top 3?",
                    "answer": "They are the top 3 by total spend.",
                    "sql": (
                        "SELECT fan_id, total_spend FROM mart_fan_loyalty "
                        "ORDER BY total_spend DESC LIMIT 3"
                    ),
                    "data_preview": [
                        {"fan_id": "fan_03248", "total_spend": 512.4},
                        {"fan_id": "fan_17965", "total_spend": 417.59},
                        {"fan_id": "fan_00219", "total_spend": 336.7},
                    ],
                }
            ],
        },
    )

    assert response.status_code == 200
    req = captured["request"]
    assert req.conversation_turn_count == 1
    assert "RECENT CONVERSATION CONTEXT" in req.conversation_section
    assert "fan_03248" in req.conversation_section
    assert "fan_17965" in req.conversation_section
    assert "fan_00219" in req.conversation_section


def test_ask_route_rejects_ollama_provider(llm_app_module) -> None:
    response = llm_app_module.app.test_client().post(
        "/api/ask",
        json={"question": "Q", "provider": "ollama"},
    )
    assert response.status_code == 400
    body = response.get_json()
    assert "Ollama is no longer supported" in body["error"]


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


# NOTE: tests for prompt construction (semantic section, answer guidelines,
# semantic-load failure, history injection into the prompt) were removed in the
# LangGraph tool-calling refactor. The model now discovers schema and semantic
# layer through tools (see tests/test_sql_agent_tools.py + test_sql_agent_graph.py),
# so those concerns are no longer enforced at the prompt-string level.


def test_ask_route_rejects_invalid_history_payload(llm_app_module) -> None:
    response = llm_app_module.app.test_client().post(
        "/api/ask",
        json={
            "question": "Who spent the most?",
            "provider": "openrouter",
            "history": {"question": "bad shape"},
        },
    )

    assert response.status_code == 400
    body = response.get_json()
    assert body["error"] == "history must be a list of prior ask/answer turns"


def _sample_leaderboard_rows() -> list[dict[str, object]]:
    return [
        {
            "rank": 1,
            "fan_id": "fan_00002",
            "points": 10560,
            "matches_attended": 10,
            "total_spend": Decimal("520.25"),
            "merch_purchase_count": 3,
            "retail_purchase_count": 5,
        },
        {
            "rank": 2,
            "fan_id": "fan_00003",
            "points": 9605,
            "matches_attended": 9,
            "total_spend": Decimal("575.10"),
            "merch_purchase_count": 4,
            "retail_purchase_count": 2,
        },
        {
            "rank": 3,
            "fan_id": "fan_00001",
            "points": 8490,
            "matches_attended": 8,
            "total_spend": Decimal("470.00"),
            "merch_purchase_count": 2,
            "retail_purchase_count": 2,
        },
    ]


def test_leaderboard_points_sql_is_attendance_first(llm_app_module) -> None:
    assert llm_app_module._leaderboard_points_sql("loyalty") == (
        "ROUND(1000 * loyalty.matches_attended + loyalty.total_spend + "
        "5 * loyalty.merch_purchase_count + 5 * loyalty.retail_purchase_count)::bigint"
    )


def test_leaderboard_order_sql_prioritizes_matches_before_spend(llm_app_module) -> None:
    assert llm_app_module._leaderboard_order_sql("leaderboard") == (
        "leaderboard.points DESC, leaderboard.matches_attended DESC, "
        "leaderboard.total_spend DESC, leaderboard.fan_id ASC"
    )
    assert llm_app_module.LEADERBOARD_TIE_BREAKERS == [
        "points DESC",
        "matches_attended DESC",
        "total_spend DESC",
        "fan_id ASC",
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
            "last_purchased_item": "Home shirt",
            "points": 9605,
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
    assert payload["fan_of_the_month"]["subtitle_metrics"]["items_purchased"] == 6
    assert payload["fan_of_the_month"]["subtitle_metrics"]["last_purchased_item"] == "Home shirt"
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
                    "points": 10560,
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
                    "points": 10560,
                    "matches_attended": 10,
                    "total_spend": Decimal("520.25"),
                    "merch_purchase_count": 3,
                    "retail_purchase_count": 5,
                }
            ],
            "fan_of_the_month": {
                "fan_id": "fan_00002",
                "display_name": "Fan 00002",
                "points": 10560,
                "matches_attended": 10,
                "total_spend": Decimal("520.25"),
                "merch_purchase_count": 3,
                "retail_purchase_count": 5,
                "subtitle_metrics": {
                    "matches": 4,
                    "items_purchased": 8,
                    "last_purchased_item": "Scarf",
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
    assert body["fan_of_the_month"]["subtitle_metrics"]["items_purchased"] == 8
    assert body["fan_of_the_month"]["subtitle_metrics"]["last_purchased_item"] == "Scarf"


def test_leaderboard_route_rejects_unsupported_window(llm_app_module) -> None:
    response = llm_app_module.app.test_client().get("/api/leaderboard?window=daily")

    assert response.status_code == 400
    body = response.get_json()
    assert "Unsupported leaderboard window" in body["error"]


def test_leaderboard_season_bounds_utc(llm_app_module) -> None:
    aug = datetime(2026, 8, 15, 12, 0, 0, tzinfo=timezone.utc)
    start, end = llm_app_module._leaderboard_season_bounds_utc(aug)
    assert start == datetime(2026, 8, 1, tzinfo=timezone.utc)
    assert end == datetime(2027, 8, 1, tzinfo=timezone.utc)

    april = datetime(2026, 4, 13, tzinfo=timezone.utc)
    start2, end2 = llm_app_module._leaderboard_season_bounds_utc(april)
    assert start2 == datetime(2025, 8, 1, tzinfo=timezone.utc)
    assert end2 == datetime(2026, 8, 1, tzinfo=timezone.utc)


def test_leaderboard_month_bounds_accepts_reference(llm_app_module) -> None:
    ref = datetime(2026, 3, 15, 22, 0, 0, tzinfo=timezone.utc)
    start, end = llm_app_module._leaderboard_month_bounds_utc(ref)
    assert start == datetime(2026, 3, 1, tzinfo=timezone.utc)
    assert end == datetime(2026, 4, 1, tzinfo=timezone.utc)


def test_build_leaderboard_payload_month_uses_bounded_fetch(
    llm_app_module, monkeypatch: pytest.MonkeyPatch
) -> None:
    called: list[tuple[datetime, datetime]] = []

    def fake_bounded(t0: datetime, t1: datetime, limit: int = 25) -> list[dict[str, object]]:
        called.append((t0, t1))
        assert limit == llm_app_module.LEADERBOARD_LIMIT
        return _sample_leaderboard_rows()

    monkeypatch.setattr(llm_app_module, "_fetch_leaderboard_rows_bounded", fake_bounded)
    monkeypatch.setattr(
        llm_app_module,
        "_leaderboard_month_bounds_utc",
        lambda: (
            datetime(2026, 4, 1, tzinfo=timezone.utc),
            datetime(2026, 5, 1, tzinfo=timezone.utc),
        ),
    )
    monkeypatch.setattr(
        llm_app_module,
        "_fetch_leaderboard_as_of_bounded",
        lambda t0, t1: datetime(2026, 4, 13, 19, 0, tzinfo=timezone.utc),
    )
    monkeypatch.setattr(
        llm_app_module,
        "_fetch_fan_of_the_month",
        lambda: None,
    )
    monkeypatch.setattr(llm_app_module, "_fetch_last_purchased_item", lambda fan_id: None)

    payload = llm_app_module._build_leaderboard_payload("month")

    assert len(called) == 1
    assert called[0][0] == datetime(2026, 4, 1, tzinfo=timezone.utc)
    assert called[0][1] == datetime(2026, 5, 1, tzinfo=timezone.utc)
    assert payload["window"] == "month"
    assert payload["rankings"][0]["fan_id"] == "fan_00002"


def test_leaderboard_route_returns_503_without_database_url(
    llm_app_module, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(llm_app_module, "DATABASE_URL", "")

    response = llm_app_module.app.test_client().get("/api/leaderboard")

    assert response.status_code == 503
    body = response.get_json()
    assert "No database URL" in body["error"]


# ---------------------------------------------------------------------------
# /api/player-stats/squad  — DB-backed reads
# ---------------------------------------------------------------------------


def _sample_player_rows() -> list[dict]:
    from datetime import datetime, timezone

    return [
        {
            "player_id": "p-001",
            "slug": "hans-vanaken",
            "name": "Hans Vanaken",
            "position": "Midfielder",
            "field_position": "CM",
            "shirt_number": 20,
            "image_url": "https://cdn.proleague.be/hans.jpg",
            "profile": {"nationality": "Belgian"},
            "stats": [
                {"key": "goals", "label": "Goals", "value": 8},
                {"key": "assists", "label": "Assists", "value": 12},
            ],
            "competition": "JPL",
            "source_url": "https://www.proleague.be/players/hans-vanaken",
            "scraped_at": datetime(2026, 4, 13, 18, 0, 0, tzinfo=timezone.utc).isoformat(),
        }
    ]


def test_squad_route_returns_players_when_data_exists(
    llm_app_module, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(llm_app_module, "_fetch_players_from_db", _sample_player_rows)

    response = llm_app_module.app.test_client().get("/api/player-stats/squad")

    assert response.status_code == 200
    body = response.get_json()
    assert body["db_backed"] is True
    players = body["players"]
    assert len(players) == 1
    p = players[0]
    assert p["player_id"] == "p-001"
    assert p["name"] == "Hans Vanaken"
    assert p["shirt_number"] == 20
    assert isinstance(p["stats"], list)
    assert p["stats"][0]["key"] == "goals"
    assert body["fetched_at"] == "2026-04-13T18:00:00+00:00"


def test_squad_route_returns_200_with_empty_list_when_table_is_empty(
    llm_app_module, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Empty public.player_stats → HTTP 200 empty-pipeline state (not an error)."""
    monkeypatch.setattr(llm_app_module, "_fetch_players_from_db", lambda: [])

    response = llm_app_module.app.test_client().get("/api/player-stats/squad")

    assert response.status_code == 200
    body = response.get_json()
    assert body["players"] == []
    assert body["db_backed"] is True


def test_squad_route_returns_503_when_db_url_missing(
    llm_app_module, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No DATABASE_URL → _fetch_players_from_db raises OperationalError → HTTP 503."""
    import psycopg2

    def raise_no_url() -> list:
        raise psycopg2.OperationalError("No database URL configured")

    monkeypatch.setattr(llm_app_module, "_fetch_players_from_db", raise_no_url)

    response = llm_app_module.app.test_client().get("/api/player-stats/squad")

    assert response.status_code == 503
    body = response.get_json()
    assert "error" in body
    assert "Database unavailable" in body["error"]


def test_squad_route_returns_500_on_db_query_error(
    llm_app_module, monkeypatch: pytest.MonkeyPatch
) -> None:
    """psycopg2.Error during query → HTTP 500, not silent empty list."""
    import psycopg2

    def raise_db_error() -> list:
        raise psycopg2.ProgrammingError("relation \"public.player_stats\" does not exist")

    monkeypatch.setattr(llm_app_module, "_fetch_players_from_db", raise_db_error)

    response = llm_app_module.app.test_client().get("/api/player-stats/squad")

    assert response.status_code == 500
    body = response.get_json()
    assert "error" in body
    assert "Database query failed" in body["error"]


# ---------------------------------------------------------------------------
# /api/player-stats/image  — CDN allowlist + fetch
# ---------------------------------------------------------------------------


def test_player_stats_image_rejects_disallowed_host(llm_app_module) -> None:
    client = llm_app_module.app.test_client()
    url = "https://evil.example.com/steal.png"
    response = client.get("/api/player-stats/image", query_string={"url": url})
    assert response.status_code == 403


def test_player_stats_image_accepts_proleague_be_host(
    llm_app_module, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, str] = {}

    class FakeResp:
        content = b"\xff\xd8\xff"
        headers = {"Content-Type": "image/jpeg"}

        def raise_for_status(self) -> None:
            return None

    def fake_get(url: str, **_kwargs: object) -> FakeResp:
        captured["url"] = url
        return FakeResp()

    monkeypatch.setattr(llm_app_module.requests, "get", fake_get)
    client = llm_app_module.app.test_client()
    image_url = "https://cdn.proleague.be/hans.jpg"
    response = client.get("/api/player-stats/image", query_string={"url": image_url})
    assert response.status_code == 200
    assert response.data == b"\xff\xd8\xff"
    assert captured["url"] == image_url


def test_player_stats_image_accepts_llt_services_cdn(
    llm_app_module, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, str] = {}

    class FakeResp:
        content = b"\x89PNG\r\n\x1a\n"
        headers = {"Content-Type": "image/png"}

        def raise_for_status(self) -> None:
            return None

    def fake_get(url: str, **_kwargs: object) -> FakeResp:
        captured["url"] = url
        return FakeResp()

    monkeypatch.setattr(llm_app_module.requests, "get", fake_get)
    client = llm_app_module.app.test_client()
    image_url = (
        "https://statics-maker.llt-services.com/prl/images/2025/07/25/xlarge/"
        "2eb8b24b-a119-4031-9bf9-99a77f4e1c03-446.png"
    )
    response = client.get("/api/player-stats/image", query_string={"url": image_url})
    assert response.status_code == 200
    assert response.data.startswith(b"\x89PNG")
    assert captured["url"] == image_url
