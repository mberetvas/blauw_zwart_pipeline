"""Flask Text-to-SQL API backed by Ollama or OpenRouter and Postgres dbt marts.

Flow
----
1. POST /api/ask {"question": "...", "provider": "ollama"|"openrouter", "model": "..."}
2. Load merged dbt schema YAML context (staging / intermediate / marts column docs).
3. Prompt the selected LLM provider -> raw SQL.
4. Validate: must be SELECT-only; no mutating keywords.
5. Execute wrapped SQL (LIMIT 50, statement_timeout 10 s) as llm_reader.
6. Prompt the LLM again with the result rows -> natural language answer.
7. Return {"answer", "sql", "data_preview"}.

POST /api/ask/stream — same steps 1–5, then streams the answer via SSE (meta, answer_delta, done).
GET /api/leaderboard — read-only fan leaderboard from mart_fan_loyalty (all-time)
    or time-windowed rollups from match_events / merch_purchase / retail_purchase (month, season).
"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Iterator, Sequence

import psycopg2
import requests
from flask import Flask, Response, jsonify, request, send_from_directory, stream_with_context

from .llm_runtime_config import (
    apply_llm_config_update,
    get_llm_settings,
    init_llm_config,
    to_public_config,
)
from .schema_context import build_schema_context_text
from .semantic_layer import (
    SemanticLayerError,
    build_answer_semantic_context,
    build_sql_semantic_context,
    load_semantic_layer,
)

# ---------------------------------------------------------------------------
# Configuration (environment variables)
# ---------------------------------------------------------------------------

# Schema loading is implemented in schema_context (SCHEMA_FILE, SCHEMA_FILES, DBT_MODELS_DIR).
# Prefer read-only role URL; Compose maps LLM_READER_DATABASE_URL -> DATABASE_URL for this service.
DATABASE_URL = (
    os.environ.get("LLM_READER_DATABASE_URL", "").strip()
    or os.environ.get("DATABASE_URL", "").strip()
)

KNOWN_PROVIDERS: frozenset[str] = frozenset({"ollama", "openrouter"})
_PROVIDER_DISPLAY = {"ollama": "Ollama", "openrouter": "OpenRouter"}
LEADERBOARD_SUPPORTED_WINDOWS: frozenset[str] = frozenset({"all", "month", "season"})
LEADERBOARD_LIMIT = 25
LEADERBOARD_ATTENDANCE_BONUS = 1000
LEADERBOARD_MATCH_POINTS = 150
LEADERBOARD_PURCHASE_POINTS = 5
LEADERBOARD_POINTS_FORMULA_TEMPLATE = (
    "ROUND(CASE WHEN {matches_attended} > 0 THEN "
    f"{LEADERBOARD_ATTENDANCE_BONUS} ELSE 0 END + "
    f"{LEADERBOARD_MATCH_POINTS} * {{matches_attended}} + {{total_spend}} "
    f"+ {LEADERBOARD_PURCHASE_POINTS} * {{merch_purchase_count}} "
    f"+ {LEADERBOARD_PURCHASE_POINTS} * {{retail_purchase_count}})::bigint"
)
LEADERBOARD_POINTS_FORMULA_TEXT = (
    f"{LEADERBOARD_ATTENDANCE_BONUS:,} attendance bonus + "
    f"{LEADERBOARD_MATCH_POINTS} x matches + spend + "
    f"{LEADERBOARD_PURCHASE_POINTS} x merch + {LEADERBOARD_PURCHASE_POINTS} x retail"
)
LEADERBOARD_TIE_BREAKERS = [
    "points DESC",
    "matches_attended DESC",
    "total_spend DESC",
    "fan_id ASC",
]
ASK_CONTEXT_MAX_TURNS = 3
ASK_CONTEXT_MAX_PREVIEW_ROWS = 5

# ---------------------------------------------------------------------------
# Security: forbidden SQL keywords that would mutate state
# ---------------------------------------------------------------------------

_MUTATING = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|TRUNCATE|ALTER|CREATE|REPLACE"
    r"|GRANT|REVOKE|EXECUTE|EXEC|CALL|COPY|VACUUM|ANALYZE|COMMENT"
    r"|LOCK|CLUSTER|REINDEX|REFRESH|SET\s+ROLE|RESET)\b",
    re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------

app = Flask(__name__, static_folder="static", static_url_path="/static")
logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)
init_llm_config()


# ---------------------------------------------------------------------------
# Schema and semantic context loaders
# ---------------------------------------------------------------------------


def load_schema_context() -> str:
    """Merge configured dbt schema YAML(s) into a compact prompt-friendly description."""
    return build_schema_context_text()


def load_semantic_context() -> tuple[str, str]:
    """Load the semantic layer and return (sql_context, answer_context).

    Returns ('', '') when the semantic layer file is absent (graceful degradation).
    Raises SemanticLayerError when the file is explicitly configured but missing or invalid.
    """
    layer = load_semantic_layer()
    return build_sql_semantic_context(layer), build_answer_semantic_context(layer)


# ---------------------------------------------------------------------------
# LLM provider helpers
# ---------------------------------------------------------------------------


def _call_ollama(prompt: str, model: str) -> str:
    """Send a prompt to Ollama /api/generate and return the response text."""
    s = get_llm_settings()
    resp = requests.post(
        f"{s['ollama_url']}/api/generate",
        json={"model": model, "prompt": prompt, "stream": False},
        timeout=int(s["ollama_timeout"]),
    )
    resp.raise_for_status()
    return resp.json()["response"].strip()


def _call_openrouter(prompt: str, model: str) -> str:
    """Send a prompt to OpenRouter chat/completions and return the response text."""
    s = get_llm_settings()
    resp = requests.post(
        f"{s['openrouter_base_url']}/chat/completions",
        headers={
            "Authorization": f"Bearer {s['openrouter_api_key']}",
            "Content-Type": "application/json",
        },
        json={"model": model, "messages": [{"role": "user", "content": prompt}]},
        timeout=int(s["openrouter_timeout"]),
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"].strip()


def complete(prompt: str, provider: str, model: str) -> str:
    """Call the selected LLM provider and return the plain-text response."""
    if provider == "openrouter":
        return _call_openrouter(prompt, model)
    return _call_ollama(prompt, model)


def _llm_request_error(
    provider_label: str,
    stage: str,
    exc: requests.exceptions.RequestException,
) -> tuple[str, int]:
    """Map provider request failures to clearer API responses."""
    status_code = getattr(getattr(exc, "response", None), "status_code", None)
    if status_code == 429:
        return (
            f"{provider_label} hit a rate limit during the {stage} step. "
            "Wait a moment, switch model, or try the other provider.",
            429,
        )
    if status_code in {401, 403}:
        return (
            f"{provider_label} rejected the request during the {stage} step. "
            "Check the server-side API key and model access.",
            503,
        )
    if isinstance(exc, requests.exceptions.Timeout):
        return (
            f"{provider_label} timed out during the {stage} step.",
            504,
        )
    if isinstance(exc, requests.exceptions.ConnectionError):
        return (
            f"{provider_label} is unreachable during the {stage} step. "
            "Check the provider connection and try again.",
            503,
        )
    return (f"{provider_label} request failed during the {stage} step: {exc}", 503)


def _build_trace(
    provider: str,
    provider_label: str,
    model: str,
    *,
    conversation_turn_count: int = 0,
    raw_sql: str | None = None,
    sql: str | None = None,
    row_count: int | None = None,
    answered: bool = False,
) -> dict[str, Any]:
    """Return safe user-facing working notes for the request."""
    notes = [
        f"Used {provider_label} with model {model}.",
        "Asked the model for one PostgreSQL SELECT query based on the schema and your question.",
    ]
    if conversation_turn_count:
        notes.append(
            "Included "
            f"{conversation_turn_count} recent conversation turn(s) so "
            "follow-up references stay scoped to the prior result set."
        )
    if raw_sql is not None:
        if sql is not None and raw_sql.strip() != sql:
            notes.append(
                "Normalized the model output by removing markdown wrappers or trailing semicolons."
            )
        else:
            notes.append("The model returned SQL directly without extra formatting.")
    if sql is not None:
        notes.append("Validated the SQL as read-only before sending it to Postgres.")
    if row_count is not None:
        notes.append(
            f"Executed the query with a 10 second timeout and outer LIMIT 50, "
            f"returning {row_count} row(s)."
        )
    elif sql is not None:
        notes.append("Tried to execute the validated SQL against Postgres.")
    if answered:
        notes.append(
            "Used the returned rows as context for the natural-language answer you see in chat."
        )
    return {
        "provider": provider,
        "provider_label": provider_label,
        "model": model,
        "notes": notes,
    }


# ---------------------------------------------------------------------------
# SQL guardrails
# ---------------------------------------------------------------------------


def _validate_sql(sql: str) -> None:
    """Raise ValueError if sql is not a safe, read-only SELECT statement."""
    stripped = sql.strip()
    starts_with = stripped.upper().lstrip("(\n\r\t ")
    if not (starts_with.startswith("SELECT") or starts_with.startswith("WITH")):
        raise ValueError(
            "Generated SQL must begin with SELECT or WITH. "
            f"Received: {stripped[:120]!r}"
        )
    if ";" in stripped:
        raise ValueError(
            "Generated SQL must contain exactly one SELECT statement and cannot include "
            "';' inside the query."
        )
    match = _MUTATING.search(stripped)
    if match:
        raise ValueError(
            f"Generated SQL contains forbidden keyword '{match.group()}'."
        )


def _strip_fences(raw: str) -> str:
    """Remove markdown code fences that models sometimes wrap SQL in."""
    raw = re.sub(r"^```[a-z]*\n?", "", raw, flags=re.MULTILINE)
    raw = re.sub(r"```\s*$", "", raw, flags=re.MULTILINE)
    raw = re.sub(r";+\s*$", "", raw.strip())
    return raw.strip()


# ---------------------------------------------------------------------------
# Database execution
# ---------------------------------------------------------------------------


def _json_default(obj: Any) -> Any:
    """JSON serialiser for Decimal and other non-serialisable Postgres types."""
    if isinstance(obj, Decimal):
        return float(obj)
    raise TypeError(f"Object of type {type(obj)} is not JSON serialisable")


def _execute_sql(sql: str) -> list[dict[str, Any]]:
    """Wrap sql in a LIMIT guard and execute it as the llm_reader role."""
    wrapped = f"SELECT * FROM (\n{sql}\n) AS llm_query LIMIT 50"
    return _run_read_query(wrapped)


def _run_read_query(
    sql: str, params: Sequence[Any] | None = None
) -> list[dict[str, Any]]:
    """Execute a read-only query with the shared reader DSN and timeout."""
    if not DATABASE_URL:
        raise psycopg2.OperationalError(
            "No database URL: set LLM_READER_DATABASE_URL or DATABASE_URL "
            "(see .env.example and docker/postgres/init/002_llm_reader.sql)."
        )
    conn = psycopg2.connect(DATABASE_URL)
    try:
        with conn.cursor() as cur:
            cur.execute("SET statement_timeout = '10s'")
            if params is None:
                cur.execute(sql)
            else:
                cur.execute(sql, params)
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, row)) for row in cur.fetchall()]
    finally:
        conn.close()


def _leaderboard_points_sql(alias: str) -> str:
    """Return the shared attendance-first leaderboard points expression."""
    return LEADERBOARD_POINTS_FORMULA_TEMPLATE.format(
        matches_attended=f"{alias}.matches_attended",
        total_spend=f"{alias}.total_spend",
        merch_purchase_count=f"{alias}.merch_purchase_count",
        retail_purchase_count=f"{alias}.retail_purchase_count",
    )


def _leaderboard_order_sql(alias: str) -> str:
    """Return the deterministic leaderboard sort order for the given alias."""
    return (
        f"{alias}.points DESC, {alias}.matches_attended DESC, "
        f"{alias}.total_spend DESC, {alias}.fan_id ASC"
    )


def _leaderboard_month_bounds_utc(
    reference: datetime | None = None,
) -> tuple[datetime, datetime]:
    """Return the UTC calendar month [start, end) for the reference instant (default: now)."""
    ref = reference or datetime.now(timezone.utc)
    if ref.tzinfo is None:
        ref = ref.replace(tzinfo=timezone.utc)
    else:
        ref = ref.astimezone(timezone.utc)
    month_start = ref.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    if month_start.month == 12:
        next_month_start = month_start.replace(year=month_start.year + 1, month=1)
    else:
        next_month_start = month_start.replace(month=month_start.month + 1)
    return month_start, next_month_start


def _leaderboard_season_bounds_utc(
    reference: datetime | None = None,
) -> tuple[datetime, datetime]:
    """Return European football season bounds [start, end) in UTC: 1 Aug → next 1 Aug."""
    ref = reference or datetime.now(timezone.utc)
    if ref.tzinfo is None:
        ref = ref.replace(tzinfo=timezone.utc)
    else:
        ref = ref.astimezone(timezone.utc)
    year = ref.year
    if ref.month >= 8:
        start = datetime(year, 8, 1, tzinfo=timezone.utc)
        end = datetime(year + 1, 8, 1, tzinfo=timezone.utc)
    else:
        start = datetime(year - 1, 8, 1, tzinfo=timezone.utc)
        end = datetime(year, 8, 1, tzinfo=timezone.utc)
    return start, end


def _fan_display_name(fan_id: str) -> str:
    """Return a stable, non-PII display name for leaderboard cards."""
    match = re.fullmatch(r"fan_(\d+)", fan_id)
    if not match:
        return fan_id
    return f"Fan {match.group(1)}"


def _leaderboard_entry_from_row(row: dict[str, Any]) -> dict[str, Any]:
    """Convert a leaderboard row into the public JSON shape."""
    fan_id = str(row["fan_id"])
    return {
        "rank": int(row["rank"]),
        "fan_id": fan_id,
        "display_name": _fan_display_name(fan_id),
        "points": int(row["points"]),
        "matches_attended": int(row["matches_attended"]),
        "total_spend": row["total_spend"],
        "merch_purchase_count": int(row["merch_purchase_count"]),
        "retail_purchase_count": int(row["retail_purchase_count"]),
    }


def _fetch_leaderboard_rows(limit: int = LEADERBOARD_LIMIT) -> list[dict[str, Any]]:
    """Return the top leaderboard rows from mart_fan_loyalty."""
    points_sql = _leaderboard_points_sql("loyalty")
    order_sql = _leaderboard_order_sql("leaderboard")
    sql = f"""
        WITH leaderboard AS (
            SELECT
                loyalty.fan_id,
                loyalty.matches_attended,
                loyalty.total_spend,
                loyalty.merch_purchase_count,
                loyalty.retail_purchase_count,
                {points_sql} AS points
            FROM mart_fan_loyalty AS loyalty
        ),
        ranked AS (
            SELECT
                ROW_NUMBER() OVER (
                    ORDER BY {order_sql}
                ) AS rank,
                leaderboard.fan_id,
                leaderboard.matches_attended,
                leaderboard.total_spend,
                leaderboard.merch_purchase_count,
                leaderboard.retail_purchase_count,
                leaderboard.points
            FROM leaderboard
        )
        SELECT
            rank,
            fan_id,
            matches_attended,
            total_spend,
            merch_purchase_count,
            retail_purchase_count,
            points
        FROM ranked
        WHERE rank <= %s
        ORDER BY rank
    """
    return _run_read_query(sql, (limit,))


def _fetch_leaderboard_rows_bounded(
    window_start: datetime,
    window_end: datetime,
    limit: int = LEADERBOARD_LIMIT,
) -> list[dict[str, Any]]:
    """Top fans for [window_start, window_end) using live fact tables (UTC bounds)."""
    points_sql = _leaderboard_points_sql("loy")
    order_sql = _leaderboard_order_sql("leaderboard")
    sql = f"""
        WITH bounds AS (
            SELECT %s::timestamptz AS t0, %s::timestamptz AS t1
        ),
        att AS (
            SELECT
                me.fan_id,
                COUNT(DISTINCT me.match_id)::integer AS matches_attended
            FROM match_events AS me
            CROSS JOIN bounds AS b
            WHERE me.event_type = 'ticket_scan'
              AND me.event_time >= b.t0
              AND me.event_time < b.t1
              AND me.match_id IS NOT NULL
              AND me.match_id <> ''
            GROUP BY me.fan_id
        ),
        merch AS (
            SELECT
                mp.fan_id,
                COUNT(*)::integer AS merch_purchase_count,
                COALESCE(SUM(mp.amount), 0)::numeric(12, 2) AS merch_spend
            FROM merch_purchase AS mp
            CROSS JOIN bounds AS b
            WHERE COALESCE(mp.event_time, mp.ingested_at) >= b.t0
              AND COALESCE(mp.event_time, mp.ingested_at) < b.t1
            GROUP BY mp.fan_id
        ),
        retail AS (
            SELECT
                rp.fan_id,
                COUNT(*)::integer AS retail_purchase_count,
                COALESCE(SUM(rp.amount), 0)::numeric(12, 2) AS retail_spend
            FROM retail_purchase AS rp
            CROSS JOIN bounds AS b
            WHERE COALESCE(rp.event_time, rp.ingested_at) >= b.t0
              AND COALESCE(rp.event_time, rp.ingested_at) < b.t1
            GROUP BY rp.fan_id
        ),
        fans AS (
            SELECT fan_id FROM att
            UNION
            SELECT fan_id FROM merch
            UNION
            SELECT fan_id FROM retail
        ),
        lo AS (
            SELECT
                f.fan_id,
                COALESCE(a.matches_attended, 0) AS matches_attended,
                (COALESCE(m.merch_spend, 0) + COALESCE(r.retail_spend, 0))::numeric(12, 2)
                    AS total_spend,
                COALESCE(m.merch_purchase_count, 0) AS merch_purchase_count,
                COALESCE(r.retail_purchase_count, 0) AS retail_purchase_count
            FROM fans AS f
            LEFT JOIN att AS a ON a.fan_id = f.fan_id
            LEFT JOIN merch AS m ON m.fan_id = f.fan_id
            LEFT JOIN retail AS r ON r.fan_id = f.fan_id
        ),
        leaderboard AS (
            SELECT
                lo.fan_id,
                lo.matches_attended,
                lo.total_spend,
                lo.merch_purchase_count,
                lo.retail_purchase_count,
                {points_sql} AS points
            FROM lo AS lo
        ),
        ranked AS (
            SELECT
                ROW_NUMBER() OVER (
                    ORDER BY {order_sql}
                ) AS rank,
                leaderboard.fan_id,
                leaderboard.matches_attended,
                leaderboard.total_spend,
                leaderboard.merch_purchase_count,
                leaderboard.retail_purchase_count,
                leaderboard.points
            FROM leaderboard
        )
        SELECT
            rank,
            fan_id,
            matches_attended,
            total_spend,
            merch_purchase_count,
            retail_purchase_count,
            points
        FROM ranked
        WHERE rank <= %s
        ORDER BY rank
    """
    return _run_read_query(sql, (window_start, window_end, limit))


def _fetch_leaderboard_as_of_bounded(
    window_start: datetime,
    window_end: datetime,
) -> datetime:
    """Latest event timestamp inside the window, or server time if the window is empty."""
    rows = _run_read_query(
        """
        WITH bounds AS (
            SELECT %s::timestamptz AS t0, %s::timestamptz AS t1
        )
        SELECT COALESCE(
            GREATEST(
                (
                    SELECT MAX(me.event_time)
                    FROM match_events AS me
                    CROSS JOIN bounds AS b
                    WHERE me.event_type = 'ticket_scan'
                      AND me.event_time >= b.t0
                      AND me.event_time < b.t1
                ),
                (
                    SELECT MAX(COALESCE(mp.event_time, mp.ingested_at))
                    FROM merch_purchase AS mp
                    CROSS JOIN bounds AS b
                    WHERE COALESCE(mp.event_time, mp.ingested_at) >= b.t0
                      AND COALESCE(mp.event_time, mp.ingested_at) < b.t1
                ),
                (
                    SELECT MAX(COALESCE(rp.event_time, rp.ingested_at))
                    FROM retail_purchase AS rp
                    CROSS JOIN bounds AS b
                    WHERE COALESCE(rp.event_time, rp.ingested_at) >= b.t0
                      AND COALESCE(rp.event_time, rp.ingested_at) < b.t1
                )
            ),
            NOW()
        ) AS as_of
        FROM bounds
        """,
        (window_start, window_end),
    )
    value = rows[0]["as_of"]
    if isinstance(value, datetime):
        return value
    return datetime.now(timezone.utc)


def _fetch_leaderboard_as_of() -> datetime:
    """Return the freshest mart watermark, or server time if the mart is empty."""
    rows = _run_read_query(
        """
        SELECT COALESCE(MAX(last_updated_at), NOW()) AS as_of
        FROM mart_fan_loyalty
        """
    )
    value = rows[0]["as_of"]
    if isinstance(value, datetime):
        return value
    return datetime.now(timezone.utc)


def _fetch_last_purchased_item(fan_id: str) -> str | None:
    """Return the item name from the fan's most recently ingested purchase row."""
    rows = _run_read_query(
        """
        SELECT item AS last_purchased_item
        FROM (
            SELECT fan_id, item, ingested_at
            FROM merch_purchase
            WHERE fan_id = %s
            UNION ALL
            SELECT fan_id, item, ingested_at
            FROM retail_purchase
            WHERE fan_id = %s
        ) purchases
        ORDER BY ingested_at DESC NULLS LAST, item ASC
        LIMIT 1
        """,
        (fan_id, fan_id),
    )
    if not rows:
        return None
    value = rows[0].get("last_purchased_item")
    if value is None:
        return None
    return str(value)


def _fetch_fan_of_the_month() -> dict[str, Any] | None:
    """Return the current UTC month fan based on ticket scans, with points tie-breakers."""
    month_start, next_month_start = _leaderboard_month_bounds_utc()
    points_sql = _leaderboard_points_sql("loyalty")
    sql = f"""
        WITH last_purchase_by_fan AS (
            SELECT DISTINCT ON (fan_id)
                fan_id,
                item AS last_purchased_item
            FROM (
                SELECT fan_id, item, ingested_at FROM merch_purchase
                UNION ALL
                SELECT fan_id, item, ingested_at FROM retail_purchase
            ) purchases
            ORDER BY fan_id, ingested_at DESC NULLS LAST, item ASC
        ),
        month_scans AS (
            SELECT
                fan_id,
                COUNT(*)::integer AS month_ticket_scans
            FROM match_events
            WHERE event_type = %s
              AND event_time >= %s
              AND event_time < %s
            GROUP BY fan_id
        ),
        ranked AS (
            SELECT
                month_scans.fan_id,
                month_scans.month_ticket_scans,
                loyalty.matches_attended,
                loyalty.total_spend,
                loyalty.merch_purchase_count,
                loyalty.retail_purchase_count,
                lp.last_purchased_item,
                {points_sql} AS points,
                ROW_NUMBER() OVER (
                    ORDER BY month_scans.month_ticket_scans DESC,
                             {points_sql} DESC,
                             loyalty.matches_attended DESC,
                             loyalty.total_spend DESC,
                             month_scans.fan_id ASC
                ) AS month_rank
            FROM month_scans
            JOIN mart_fan_loyalty AS loyalty
              ON loyalty.fan_id = month_scans.fan_id
            LEFT JOIN last_purchase_by_fan AS lp
              ON lp.fan_id = month_scans.fan_id
        )
        SELECT
            fan_id,
            month_ticket_scans,
            matches_attended,
            total_spend,
            merch_purchase_count,
            retail_purchase_count,
            last_purchased_item,
            points
        FROM ranked
        WHERE month_rank = 1
    """
    rows = _run_read_query(sql, ("ticket_scan", month_start, next_month_start))
    return rows[0] if rows else None


def _fan_of_the_month_payload(
    month_row: dict[str, Any] | None, fallback_row: dict[str, Any] | None
) -> dict[str, Any] | None:
    """Return the public fan-of-the-month payload with a fallback to rank 1 overall."""
    source = month_row or fallback_row
    if source is None:
        return None
    fan_id = str(source["fan_id"])
    display_name = _fan_display_name(fan_id)
    month_scans = (
        int(source["month_ticket_scans"])
        if month_row is not None and source.get("month_ticket_scans") is not None
        else None
    )
    summary = (
        f"{month_scans} ticket scans this month · Referrals not tracked"
        if month_scans is not None
        else "No ticket scans recorded this month yet — showing the current all-time leader."
    )
    merch_count = int(source["merch_purchase_count"])
    retail_count = int(source["retail_purchase_count"])
    items_purchased = merch_count + retail_count
    if "last_purchased_item" in source:
        last_item = source.get("last_purchased_item")
    else:
        last_item = _fetch_last_purchased_item(fan_id)
    if last_item is not None:
        last_item = str(last_item)
    return {
        "fan_id": fan_id,
        "display_name": display_name,
        "points": int(source["points"]),
        "matches_attended": int(source["matches_attended"]),
        "total_spend": source["total_spend"],
        "merch_purchase_count": merch_count,
        "retail_purchase_count": retail_count,
        "subtitle_metrics": {
            "matches": month_scans if month_scans is not None else int(source["matches_attended"]),
            "items_purchased": items_purchased,
            "last_purchased_item": last_item,
            "referrals": None,
        },
        "summary": summary,
        "fallback": month_scans is None,
    }


def _build_leaderboard_payload(window: str) -> dict[str, Any]:
    """Build the public leaderboard payload for the supported window."""
    if window not in LEADERBOARD_SUPPORTED_WINDOWS:
        raise ValueError(
            f"Unsupported leaderboard window '{window}'. "
            f"Valid values: {sorted(LEADERBOARD_SUPPORTED_WINDOWS)}"
        )

    if window == "all":
        rankings = [_leaderboard_entry_from_row(row) for row in _fetch_leaderboard_rows()]
        as_of_dt = _fetch_leaderboard_as_of()
    elif window == "month":
        t0, t1 = _leaderboard_month_bounds_utc()
        rankings = [
            _leaderboard_entry_from_row(row)
            for row in _fetch_leaderboard_rows_bounded(t0, t1)
        ]
        as_of_dt = _fetch_leaderboard_as_of_bounded(t0, t1)
    else:
        t0, t1 = _leaderboard_season_bounds_utc()
        rankings = [
            _leaderboard_entry_from_row(row)
            for row in _fetch_leaderboard_rows_bounded(t0, t1)
        ]
        as_of_dt = _fetch_leaderboard_as_of_bounded(t0, t1)

    podium = rankings[:3]
    fan_of_the_month = _fan_of_the_month_payload(
        _fetch_fan_of_the_month(),
        podium[0] if podium else None,
    )
    as_of = as_of_dt.astimezone(timezone.utc).isoformat()
    return {
        "window": window,
        "as_of": as_of.replace("+00:00", "Z"),
        "points_formula": LEADERBOARD_POINTS_FORMULA_TEXT,
        "tie_breakers": LEADERBOARD_TIE_BREAKERS,
        "podium": podium,
        "rankings": rankings,
        "fan_of_the_month": fan_of_the_month,
        "achievement": None,
    }


# ---------------------------------------------------------------------------
# Ask pipeline (shared by /api/ask and /api/ask/stream)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AskPipelineOk:
    """Successful SQL generation, validation, and execution; ready for answer step."""

    question: str
    conversation_turn_count: int
    provider: str
    model: str
    provider_label: str
    raw_sql: str
    sql: str
    rows: list[dict[str, Any]]
    data_preview: list[dict[str, Any]]
    trace: dict[str, Any]
    answer_prompt: str


@dataclass(frozen=True)
class ConversationTurn:
    """Recent successful ask/answer turn used to resolve follow-up references."""

    question: str
    answer: str
    sql: str | None
    data_preview: list[dict[str, Any]]


def _normalise_conversation_history(
    body: dict[str, Any],
) -> list[ConversationTurn]:
    """Validate and normalise recent conversation history from the request body."""
    raw_history = body.get("history")
    if raw_history is None:
        return []
    if not isinstance(raw_history, list):
        raise ValueError("history must be a list of prior ask/answer turns")

    history: list[ConversationTurn] = []
    for idx, item in enumerate(raw_history[-ASK_CONTEXT_MAX_TURNS:], start=1):
        if not isinstance(item, dict):
            raise ValueError(f"history[{idx}] must be an object")

        question = str(item.get("question") or "").strip()
        answer = str(item.get("answer") or "").strip()
        if not question or not answer:
            raise ValueError(
                f"history[{idx}] must include non-empty question and answer strings"
            )

        sql = item.get("sql")
        if sql is not None:
            sql = str(sql).strip() or None

        raw_preview = item.get("data_preview") or []
        if not isinstance(raw_preview, list):
            raise ValueError(f"history[{idx}].data_preview must be a list")

        preview: list[dict[str, Any]] = []
        for row_idx, row in enumerate(
            raw_preview[:ASK_CONTEXT_MAX_PREVIEW_ROWS], start=1
        ):
            if not isinstance(row, dict):
                raise ValueError(
                    f"history[{idx}].data_preview[{row_idx}] must be an object"
                )
            preview.append(row)

        history.append(
            ConversationTurn(
                question=question,
                answer=answer,
                sql=sql,
                data_preview=preview,
            )
        )

    return history


def _conversation_context_section(history: list[ConversationTurn]) -> str:
    """Return prompt context that helps the model scope follow-up questions."""
    if not history:
        return ""

    blocks: list[str] = []
    for idx, turn in enumerate(history, start=1):
        lines = [
            f"Turn {idx} user question: {turn.question}",
            f"Turn {idx} assistant answer: {turn.answer}",
        ]
        if turn.sql:
            lines.append(f"Turn {idx} SQL used: {turn.sql}")
        if turn.data_preview:
            preview_json = json.dumps(turn.data_preview, indent=2, default=_json_default)
            lines.append(f"Turn {idx} data preview (JSON):\n{preview_json}")
        blocks.append("\n".join(lines))

    joined = "\n\n".join(blocks)
    return (
        "RECENT CONVERSATION CONTEXT:\n"
        "Use the recent turns below only to resolve follow-up references such as "
        "'these fans', 'them', 'those results', 'that match', or 'the same group'. "
        "If the latest question refers to a previously returned subset, keep the SQL "
        "scoped to that subset instead of broadening it to the whole table.\n\n"
        f"{joined}\n\n"
    )


def _ask_run_through_execution(
    body: dict[str, Any],
) -> AskPipelineOk | tuple[dict[str, Any], int]:
    """Validate request, generate SQL, validate SQL, execute. Returns Ok or (error dict, status)."""
    question: str = (body.get("question") or "").strip()
    if not question:
        return ({"error": "question is required"}, 400)
    try:
        history = _normalise_conversation_history(body)
    except ValueError as exc:
        return ({"error": str(exc)}, 400)

    s = get_llm_settings()
    provider = (body.get("provider") or s["default_provider"]).strip().lower()
    if provider not in KNOWN_PROVIDERS:
        return (
            {
                "error": (
                    f"Unknown provider '{provider}'. "
                    f"Valid values: {sorted(KNOWN_PROVIDERS)}"
                )
            },
            400,
        )

    model = (body.get("model") or "").strip() or (
        s["ollama_model"] if provider == "ollama" else s["openrouter_model"]
    )

    if provider == "openrouter" and not s["openrouter_api_key"]:
        return (
            {
                "error": (
                    "OpenRouter is not configured. "
                    "Set the API key under Club Settings or OPENROUTER_API_KEY in the environment."
                )
            },
            503,
        )

    provider_label = _PROVIDER_DISPLAY.get(provider, provider)

    try:
        schema_context = load_schema_context()
    except Exception as exc:
        log.exception("Failed to load schema")
        return ({"error": f"Schema load failed: {exc}"}, 500)

    try:
        sql_semantic_ctx, answer_semantic_ctx = load_semantic_context()
    except SemanticLayerError as exc:
        log.exception("Failed to load semantic layer")
        return ({"error": f"Semantic layer load failed: {exc}"}, 500)

    semantic_section = (
        f"SEMANTIC LAYER:\n{sql_semantic_ctx}\n" if sql_semantic_ctx else ""
    )
    conversation_section = _conversation_context_section(history)
    sql_prompt = (
        "You are a PostgreSQL expert. Given the schema below, write a single "
        "SELECT query that answers the question. Return ONLY the SQL — no "
        "explanation, no markdown, no code fences.\n\n"
        f"{semantic_section}"
        f"{conversation_section}"
        f"Schema:\n{schema_context}\n"
        f"Question: {question}\n\n"
        "SQL:"
    )
    try:
        raw_sql = complete(sql_prompt, provider, model)
    except requests.exceptions.RequestException as exc:
        log.exception("%s unreachable (SQL step)", provider_label)
        error, status = _llm_request_error(provider_label, "SQL generation", exc)
        return (
            {
                "error": error,
                "trace": _build_trace(
                    provider,
                    provider_label,
                    model,
                    conversation_turn_count=len(history),
                ),
            },
            status,
        )

    sql = _strip_fences(raw_sql)
    log.info("Generated SQL (%s/%s): %s", provider, model, sql)
    trace = _build_trace(
        provider,
        provider_label,
        model,
        conversation_turn_count=len(history),
        raw_sql=raw_sql,
        sql=sql,
    )

    try:
        _validate_sql(sql)
    except ValueError as exc:
        return ({"error": str(exc), "raw_sql": raw_sql, "trace": trace}, 422)

    try:
        rows = _execute_sql(sql)
    except psycopg2.Error as exc:
        log.exception("Query execution failed")
        err = str(exc)
        if "password authentication failed" in err.lower():
            err += (
                " — check LLM_READER_DATABASE_URL matches LLM_READER_PASSWORD in "
                ".env / docker-compose and the Postgres role password. "
                "If Postgres was created before that init script existed, run: "
                "ALTER ROLE llm_reader PASSWORD '<your-llm-reader-password>'; as a superuser, "
                "or recreate the volume with docker compose down -v."
            )
        return (
            {
                "error": f"Query execution failed: {err}",
                "sql": sql,
                "trace": trace,
            },
            500,
        )

    preview = json.loads(json.dumps(rows[:10], default=_json_default))
    answer_guidelines_section = (
        f"{answer_semantic_ctx}\n" if answer_semantic_ctx else ""
    )
    answer_prompt = (
        "You are a helpful data analyst for a football club. "
        "Answer the question below using the data provided.\n\n"
        "Output format — Markdown only:\n"
        "- Respond only in GitHub-flavored Markdown (headings, bold, lists, tables, "
        "inline `code`, fenced code blocks when useful).\n"
        "- Do not wrap the entire answer in one outer fenced code block.\n"
        "- Do not include raw HTML tags in your answer.\n\n"
        f"{answer_guidelines_section}"
        f"{conversation_section}"
        f"Question: {question}\n\n"
        f"Data (JSON, up to 10 rows):\n{json.dumps(preview, indent=2)}\n\n"
        "Answer:"
    )
    data_preview = json.loads(json.dumps(rows, default=_json_default))
    trace_with_rows = _build_trace(
        provider,
        provider_label,
        model,
        conversation_turn_count=len(history),
        raw_sql=raw_sql,
        sql=sql,
        row_count=len(rows),
    )

    return AskPipelineOk(
        question=question,
        conversation_turn_count=len(history),
        provider=provider,
        model=model,
        provider_label=provider_label,
        raw_sql=raw_sql,
        sql=sql,
        rows=rows,
        data_preview=data_preview,
        trace=trace_with_rows,
        answer_prompt=answer_prompt,
    )


def _format_sse(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, default=_json_default)}\n\n"


def _streaming_timeout(total: int) -> tuple[int, int]:
    """(connect, read) for streaming requests; read uses full provider timeout."""
    c = min(30, max(1, total))
    return (c, total)


def _stream_ollama_answer(prompt: str, model: str) -> Iterator[str]:
    s = get_llm_settings()
    to = int(s["ollama_timeout"])
    timeout = _streaming_timeout(to)
    with requests.post(
        f"{s['ollama_url']}/api/generate",
        json={"model": model, "prompt": prompt, "stream": True},
        stream=True,
        timeout=timeout,
    ) as resp:
        resp.raise_for_status()
        for line in resp.iter_lines(decode_unicode=True):
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                log.warning("Ollama stream: skip non-JSON line: %s", line[:200])
                continue
            piece = obj.get("response") or ""
            if piece:
                yield piece


def _stream_openrouter_answer(prompt: str, model: str) -> Iterator[str]:
    s = get_llm_settings()
    to = int(s["openrouter_timeout"])
    timeout = _streaming_timeout(to)
    with requests.post(
        f"{s['openrouter_base_url']}/chat/completions",
        headers={
            "Authorization": f"Bearer {s['openrouter_api_key']}",
            "Content-Type": "application/json",
        },
        json={
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "stream": True,
        },
        stream=True,
        timeout=timeout,
    ) as resp:
        resp.raise_for_status()
        for line in resp.iter_lines(decode_unicode=True):
            if not line:
                continue
            if not line.startswith("data:"):
                continue
            data = line[5:].lstrip()
            if data == "[DONE]":
                break
            try:
                obj = json.loads(data)
            except json.JSONDecodeError:
                continue
            choices = obj.get("choices") or []
            if not choices:
                continue
            delta = choices[0].get("delta") or {}
            content = delta.get("content")
            if content:
                yield content


def _iter_answer_stream(provider: str, model: str, answer_prompt: str) -> Iterator[str]:
    """Yield non-empty UTF-8 text fragments from the provider's streaming answer API."""
    if provider == "openrouter":
        yield from _stream_openrouter_answer(answer_prompt, model)
    else:
        yield from _stream_ollama_answer(answer_prompt, model)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@app.get("/")
def index() -> Any:
    return send_from_directory(app.static_folder, "index.html")


@app.get("/leaderboard")
def leaderboard() -> Any:
    return send_from_directory(app.static_folder, "leaderboard.html")


@app.get("/player-stats")
def player_stats() -> Any:
    return send_from_directory(app.static_folder, "player-stats.html")


@app.get("/settings")
def settings_page() -> Any:
    return send_from_directory(app.static_folder, "settings.html")


@app.get("/api/llm-config")
def llm_config_get() -> Any:
    return jsonify(to_public_config())


@app.put("/api/llm-config")
def llm_config_put() -> Any:
    body: dict[str, Any] = request.get_json(force=True) or {}
    try:
        return jsonify(apply_llm_config_update(body))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except OSError as exc:
        log.exception("Failed to persist LLM config")
        return jsonify({"error": str(exc)}), 500


@app.get("/health")
def health() -> Any:
    return jsonify({"status": "ok"})


# ---------------------------------------------------------------------------
# Player stats — DB-backed reads (squad) + image proxy
# /api/player-stats/squad   reads public.player_stats (written by proleague-ingest)
# /api/player-stats/player  single-player live fetch via proleague-scraper (utility)
# /api/player-stats/image   server-side CDN image proxy (bypasses hotlink/CORS)
# ---------------------------------------------------------------------------

#: Internal URL of the proleague-scraper Compose service.
#: Used only for the /api/player-stats/player and /api/player-stats/image routes.
PROLEAGUE_SCRAPER_URL = os.environ.get(
    "PROLEAGUE_SCRAPER_URL", "http://proleague-scraper:8001"
).rstrip("/")

# SQL to read all player rows from the public schema.
# llm_reader has search_path=dbt_dev so the schema qualifier is explicit.
_SELECT_PLAYERS_SQL = """
SELECT player_id, slug, name, position, field_position, shirt_number,
       image_url, profile, stats, competition, source_url, scraped_at
FROM public.player_stats
ORDER BY name
"""

DEFAULT_SQUAD_URL = "https://www.proleague.be/teams/club-brugge-kv-182/squad"


def _fetch_players_from_db() -> list[dict]:
    """Return all rows from public.player_stats using the read-only DB connection.

    Returns an empty list only when the table exists but contains no rows.
    Raises psycopg2.OperationalError when DATABASE_URL is not configured.
    Raises psycopg2.Error on any other database failure (caller maps to HTTP status).
    """
    import json as _json

    if not DATABASE_URL:
        raise psycopg2.OperationalError(
            "No database URL configured: set LLM_READER_DATABASE_URL or DATABASE_URL "
            "(see .env.example and docker/postgres/init/002_llm_reader.sql)."
        )
    conn = psycopg2.connect(DATABASE_URL)
    try:
        with conn.cursor() as cur:
            cur.execute(_SELECT_PLAYERS_SQL)
            rows = cur.fetchall()
    finally:
        conn.close()

    players = []
    for row in rows:
        (
            player_id, slug, name, position, field_position, shirt_number,
            image_url, profile, stats, competition, source_url, scraped_at,
        ) = row
        players.append(
            {
                "player_id": player_id,
                "slug": slug,
                "name": name,
                "position": position or "",
                "field_position": field_position or "",
                "shirt_number": shirt_number,
                "image_url": image_url or "",
                # psycopg2 returns JSONB as Python dicts/lists already.
                "profile": profile if isinstance(profile, dict) else _json.loads(profile or "{}"),
                "stats": stats if isinstance(stats, list) else _json.loads(stats or "[]"),
                "competition": competition or "",
                "source_url": source_url or "",
                "scraped_at": scraped_at.isoformat() if scraped_at else None,
            }
        )
    return players


@app.get("/api/player-stats/squad")
def player_stats_squad() -> Any:
    """Return Club Brugge squad data from the Postgres ``player_stats`` table.

    Data is populated asynchronously by the daily proleague-scheduler → Kafka →
    proleague-ingest pipeline.  Returns an empty squad (HTTP 200) when the table
    exists but is empty (pipeline hasn't run yet).  Returns HTTP 503/500 on DB
    errors so the browser shows the error state rather than the empty-pipeline state.
    """
    try:
        players = _fetch_players_from_db()
    except psycopg2.OperationalError as exc:
        log.error("player_stats_squad: DB unavailable: %s", exc)
        return jsonify({"error": f"Database unavailable: {exc}"}), 503
    except psycopg2.Error as exc:
        log.exception("player_stats_squad: DB query failed")
        return jsonify({"error": f"Database query failed: {exc}"}), 500
    latest = max(
        (p["scraped_at"] for p in players if p.get("scraped_at")),
        default=None,
    )
    return jsonify(
        {
            "source_url": DEFAULT_SQUAD_URL,
            "fetched_at": latest or "",
            "db_backed": True,
            "players": players,
        }
    )


@app.get("/api/player-stats/player")
def player_stats_player() -> Any:
    """Proxy a single-player live fetch from the proleague-scraper service.

    This is a utility endpoint for on-demand single-player refresh; normal
    squad reads go through /api/player-stats/squad (DB-backed).
    Requires the proleague-scraper Compose service to be reachable.
    """
    player_url = request.args.get("url", "").strip()
    if not player_url:
        return jsonify({"error": "url query parameter is required"}), 400
    try:
        resp = requests.get(
            f"{PROLEAGUE_SCRAPER_URL}/player",
            params={"url": player_url},
            timeout=30,
        )
        resp.raise_for_status()
        return jsonify(resp.json())
    except requests.exceptions.ConnectionError:
        return (
            jsonify(
                {"error": "proleague-scraper is unreachable. "
                          "Check: docker compose logs proleague-scraper."}
            ),
            503,
        )
    except requests.exceptions.Timeout:
        return jsonify({"error": "proleague-scraper timed out."}), 504
    except requests.exceptions.RequestException as exc:
        log.exception("Player stats player proxy failed")
        return jsonify({"error": f"Scraper request failed: {exc}"}), 502


@app.get("/api/player-stats/image")
def player_stats_image() -> Any:
    """Proxy a player image from proleague.be to the browser.

    Fetches the image server-side and streams it back, bypassing browser-side
    hotlink blocking and CORS restrictions from the proleague.be image CDN.
    Only URLs whose hostname ends with ``proleague.be`` are accepted.
    """
    from urllib.parse import urlparse as _urlparse

    image_url = request.args.get("url", "").strip()
    if not image_url:
        return jsonify({"error": "url parameter is required"}), 400

    parsed = _urlparse(image_url)
    if not parsed.netloc.lower().endswith("proleague.be"):
        return jsonify({"error": "Only proleague.be image URLs are allowed"}), 403

    try:
        img_resp = requests.get(
            image_url,
            timeout=10,
            headers={
                "Referer": "https://www.proleague.be/",
                "User-Agent": (
                    "ClubBruggeAI-FanSim/1.0 "
                    "(fan data pipeline; https://github.com/your-org/blauw_zwart_fan_sim_pipeline)"
                ),
            },
        )
        img_resp.raise_for_status()
    except requests.exceptions.RequestException as exc:
        log.warning("Image proxy failed for %s: %s", image_url, exc)
        return jsonify({"error": f"Failed to fetch image: {exc}"}), 502

    content_type = img_resp.headers.get("Content-Type", "image/jpeg")
    return Response(img_resp.content, content_type=content_type)


@app.get("/api/leaderboard")
def leaderboard_api() -> Any:
    window = (request.args.get("window") or "all").strip().lower()
    try:
        payload = _build_leaderboard_payload(window)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except psycopg2.OperationalError as exc:
        if not DATABASE_URL:
            return jsonify({"error": str(exc)}), 503
        log.exception("Leaderboard query failed")
        return jsonify({"error": f"Leaderboard query failed: {exc}"}), 500
    except psycopg2.Error as exc:
        log.exception("Leaderboard query failed")
        return jsonify({"error": f"Leaderboard query failed: {exc}"}), 500

    return jsonify(json.loads(json.dumps(payload, default=_json_default)))


@app.post("/api/ask")
def ask() -> Any:
    body: dict[str, Any] = request.get_json(force=True) or {}
    result = _ask_run_through_execution(body)
    if isinstance(result, tuple):
        payload, status = result
        return jsonify(payload), status

    ok = result
    try:
        answer = complete(ok.answer_prompt, ok.provider, ok.model)
    except requests.exceptions.RequestException as exc:
        log.exception("%s unreachable (answer step)", ok.provider_label)
        error, status = _llm_request_error(ok.provider_label, "answer", exc)
        return (
            jsonify(
                {
                    "error": error,
                    "sql": ok.sql,
                    "trace": _build_trace(
                        ok.provider,
                        ok.provider_label,
                        ok.model,
                        conversation_turn_count=ok.conversation_turn_count,
                        raw_sql=ok.raw_sql,
                        sql=ok.sql,
                        row_count=len(ok.rows),
                    ),
                }
            ),
            status,
        )

    return jsonify(
        {
            "answer": answer,
            "sql": ok.sql,
            "data_preview": ok.data_preview,
            "trace": _build_trace(
                ok.provider,
                ok.provider_label,
                ok.model,
                conversation_turn_count=ok.conversation_turn_count,
                raw_sql=ok.raw_sql,
                sql=ok.sql,
                row_count=len(ok.rows),
                answered=True,
            ),
        }
    )


@app.post("/api/ask/stream")
def ask_stream() -> Any:
    body: dict[str, Any] = request.get_json(force=True) or {}
    pipeline = _ask_run_through_execution(body)
    if isinstance(pipeline, tuple):
        payload, status = pipeline
        return jsonify(payload), status

    ok = pipeline

    @stream_with_context
    def event_stream() -> Iterator[str]:
        yield _format_sse(
            "meta",
            {
                "sql": ok.sql,
                "data_preview": ok.data_preview,
                "trace": ok.trace,
            },
        )
        try:
            for fragment in _iter_answer_stream(
                ok.provider, ok.model, ok.answer_prompt
            ):
                if fragment:
                    yield _format_sse("answer_delta", {"text": fragment})
        except requests.exceptions.RequestException as exc:
            log.exception("%s unreachable (answer stream)", ok.provider_label)
            msg, _ = _llm_request_error(ok.provider_label, "answer", exc)
            yield _format_sse("error", {"message": msg})
            return
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            log.exception("Answer stream parse error")
            yield _format_sse(
                "error",
                {"message": f"Answer stream failed: {exc}"},
            )
            return
        yield _format_sse("done", {})

    headers = {
        "Cache-Control": "no-cache",
        "X-Accel-Buffering": "no",
    }
    return Response(
        event_stream(),
        mimetype="text/event-stream",
        headers=headers,
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
