"""Flask Text-to-SQL API backed by Ollama or OpenRouter and Postgres dbt marts.

Flow
----
1. POST /api/ask {"question": "...", "provider": "ollama"|"openrouter", "model": "..."}
2. Load schema.yml context (dbt marts column descriptions).
3. Prompt the selected LLM provider -> raw SQL.
4. Validate: must be SELECT-only; no mutating keywords.
5. Execute wrapped SQL (LIMIT 50, statement_timeout 10 s) as llm_reader.
6. Prompt the LLM again with the result rows -> natural language answer.
7. Return {"answer", "sql", "data_preview"}.
"""

from __future__ import annotations

import json
import logging
import os
import re
from decimal import Decimal
from pathlib import Path
from typing import Any

import psycopg2
import requests
import yaml
from flask import Flask, jsonify, request, send_from_directory

from .llm_runtime_config import (
    apply_llm_config_update,
    get_llm_settings,
    init_llm_config,
    to_public_config,
)

# ---------------------------------------------------------------------------
# Configuration (environment variables)
# ---------------------------------------------------------------------------

SCHEMA_FILE = Path(os.environ.get("SCHEMA_FILE", Path(__file__).parent / "schema.yml"))
# Prefer read-only role URL; Compose maps LLM_READER_DATABASE_URL -> DATABASE_URL for this service.
DATABASE_URL = (
    os.environ.get("LLM_READER_DATABASE_URL", "").strip()
    or os.environ.get("DATABASE_URL", "").strip()
)

KNOWN_PROVIDERS: frozenset[str] = frozenset({"ollama", "openrouter"})
_PROVIDER_DISPLAY = {"ollama": "Ollama", "openrouter": "OpenRouter"}

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
# Schema context loader
# ---------------------------------------------------------------------------


def load_schema_context() -> str:
    """Read schema.yml and return a compact prompt-friendly description."""
    with open(SCHEMA_FILE) as fh:
        schema: dict[str, Any] = yaml.safe_load(fh)

    parts: list[str] = []
    for model in schema.get("models", []):
        parts.append(f"Table: {model['name']}")
        desc = (model.get("description") or "").strip().replace("\n", " ")
        if desc:
            parts.append(f"  Description: {desc}")
        for col in model.get("columns", []):
            col_desc = (col.get("description") or "").strip().replace("\n", " ")
            parts.append(
                f"  - {col['name']} ({col.get('data_type', '?')}): {col_desc}"
            )
        parts.append("")
    return "\n".join(parts)


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
            f"Executed the query with a 10 second timeout and outer LIMIT 50, returning {row_count} row(s)."
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
    if not stripped.upper().lstrip("(\n\r\t ").startswith("SELECT"):
        raise ValueError(
            "Generated SQL must begin with SELECT. "
            f"Received: {stripped[:120]!r}"
        )
    if ";" in stripped:
        raise ValueError(
            "Generated SQL must contain exactly one SELECT statement and cannot include ';' inside the query."
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
    if not DATABASE_URL:
        raise psycopg2.OperationalError(
            "No database URL: set LLM_READER_DATABASE_URL or DATABASE_URL "
            "(see .env.example and docker/postgres/init/002_llm_reader.sql)."
        )
    wrapped = f"SELECT * FROM (\n{sql}\n) AS llm_query LIMIT 50"
    conn = psycopg2.connect(DATABASE_URL)
    try:
        with conn.cursor() as cur:
            cur.execute("SET statement_timeout = '10s'")
            cur.execute(wrapped)
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, row)) for row in cur.fetchall()]
    finally:
        conn.close()


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


@app.post("/api/ask")
def ask() -> Any:
    body: dict[str, Any] = request.get_json(force=True) or {}
    question: str = (body.get("question") or "").strip()
    if not question:
        return jsonify({"error": "question is required"}), 400

    s = get_llm_settings()
    # Resolve and validate provider.
    provider = (body.get("provider") or s["default_provider"]).strip().lower()
    if provider not in KNOWN_PROVIDERS:
        return jsonify(
            {
                "error": (
                    f"Unknown provider '{provider}'. "
                    f"Valid values: {sorted(KNOWN_PROVIDERS)}"
                )
            }
        ), 400

    # Resolve model (request override -> configured default for the provider).
    model = (body.get("model") or "").strip() or (
        s["ollama_model"] if provider == "ollama" else s["openrouter_model"]
    )

    # Guard: OpenRouter requires a server-side API key.
    if provider == "openrouter" and not s["openrouter_api_key"]:
        return jsonify(
            {
                "error": (
                    "OpenRouter is not configured. "
                    "Set the API key under Club Settings or OPENROUTER_API_KEY in the environment."
                )
            }
        ), 503

    provider_label = _PROVIDER_DISPLAY.get(provider, provider)

    # 1. Load schema context.
    try:
        schema_context = load_schema_context()
    except Exception as exc:
        log.exception("Failed to load schema")
        return jsonify({"error": f"Schema load failed: {exc}"}), 500

    # 2. Prompt LLM for SQL.
    sql_prompt = (
        "You are a PostgreSQL expert. Given the schema below, write a single "
        "SELECT query that answers the question. Return ONLY the SQL — no "
        "explanation, no markdown, no code fences.\n\n"
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
            jsonify(
                {
                    "error": error,
                    "trace": _build_trace(provider, provider_label, model),
                }
            ),
            status,
        )

    sql = _strip_fences(raw_sql)
    log.info("Generated SQL (%s/%s): %s", provider, model, sql)
    trace = _build_trace(
        provider,
        provider_label,
        model,
        raw_sql=raw_sql,
        sql=sql,
    )

    # 3. Validate SQL.
    try:
        _validate_sql(sql)
    except ValueError as exc:
        return jsonify({"error": str(exc), "raw_sql": raw_sql, "trace": trace}), 422

    # 4. Execute against Postgres.
    try:
        rows = _execute_sql(sql)
    except psycopg2.Error as exc:
        log.exception("Query execution failed")
        err = str(exc)
        if "password authentication failed" in err.lower():
            err += (
                " — check LLM_READER_DATABASE_URL matches the password in "
                "docker/postgres/init/002_llm_reader.sql (default llm_reader_pass). "
                "If Postgres was created before that init script existed, run: "
                "ALTER ROLE llm_reader PASSWORD 'llm_reader_pass'; as a superuser, "
                "or recreate the volume with docker compose down -v."
            )
        return (
            jsonify(
                {
                    "error": f"Query execution failed: {err}",
                    "sql": sql,
                    "trace": trace,
                }
            ),
            500,
        )

    # 5. Prompt LLM for a natural-language answer.
    preview = json.loads(json.dumps(rows[:10], default=_json_default))
    answer_prompt = (
        "You are a helpful data analyst for a football club. "
        "Answer the question below in 1-3 clear sentences using the data provided. "
        "Be specific: include numbers and names from the data.\n\n"
        f"Question: {question}\n\n"
        f"Data (JSON, up to 10 rows):\n{json.dumps(preview, indent=2)}\n\n"
        "Answer:"
    )
    try:
        answer = complete(answer_prompt, provider, model)
    except requests.exceptions.RequestException as exc:
        log.exception("%s unreachable (answer step)", provider_label)
        error, status = _llm_request_error(provider_label, "answer", exc)
        return (
            jsonify(
                {
                    "error": error,
                    "sql": sql,
                    "trace": _build_trace(
                        provider,
                        provider_label,
                        model,
                        raw_sql=raw_sql,
                        sql=sql,
                        row_count=len(rows),
                    ),
                }
            ),
            status,
        )

    return jsonify(
        {
            "answer": answer,
            "sql": sql,
            "data_preview": json.loads(json.dumps(rows, default=_json_default)),
            "trace": _build_trace(
                provider,
                provider_label,
                model,
                raw_sql=raw_sql,
                sql=sql,
                row_count=len(rows),
                answered=True,
            ),
        }
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
