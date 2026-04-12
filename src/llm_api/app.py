"""Flask Text-to-SQL API backed by Ollama (gemma4:e2b) and Postgres dbt marts.

Flow
----
1. POST /api/ask {"question": "..."}
2. Load schema.yml context (dbt marts column descriptions).
3. Prompt Ollama → raw SQL.
4. Validate: must be SELECT-only; no mutating keywords.
5. Execute wrapped SQL (LIMIT 50, statement_timeout 10 s) as llm_reader.
6. Prompt Ollama again with the result rows → natural language answer.
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

# ---------------------------------------------------------------------------
# Configuration (environment variables)
# ---------------------------------------------------------------------------

SCHEMA_FILE = Path(os.environ.get("SCHEMA_FILE", Path(__file__).parent / "schema.yml"))
DATABASE_URL = os.environ.get("DATABASE_URL", "")
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://host.docker.internal:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "gemma4:e2b")
OLLAMA_TIMEOUT = int(os.environ.get("OLLAMA_TIMEOUT", "120"))

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
# Ollama helper
# ---------------------------------------------------------------------------


def _call_ollama(prompt: str) -> str:
    """Send a prompt to Ollama and return the response text."""
    resp = requests.post(
        f"{OLLAMA_URL}/api/generate",
        json={"model": OLLAMA_MODEL, "prompt": prompt, "stream": False},
        timeout=OLLAMA_TIMEOUT,
    )
    resp.raise_for_status()
    return resp.json()["response"].strip()


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
    match = _MUTATING.search(stripped)
    if match:
        raise ValueError(
            f"Generated SQL contains forbidden keyword '{match.group()}'."
        )


def _strip_fences(raw: str) -> str:
    """Remove markdown code fences that models sometimes wrap SQL in."""
    raw = re.sub(r"^```[a-z]*\n?", "", raw, flags=re.MULTILINE)
    raw = re.sub(r"```\s*$", "", raw, flags=re.MULTILINE)
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


@app.get("/health")
def health() -> Any:
    return jsonify({"status": "ok"})


@app.post("/api/ask")
def ask() -> Any:
    body: dict[str, Any] = request.get_json(force=True) or {}
    question: str = (body.get("question") or "").strip()
    if not question:
        return jsonify({"error": "question is required"}), 400

    # 1. Load schema context.
    try:
        schema_context = load_schema_context()
    except Exception as exc:
        log.exception("Failed to load schema")
        return jsonify({"error": f"Schema load failed: {exc}"}), 500

    # 2. Prompt Ollama for SQL.
    sql_prompt = (
        "You are a PostgreSQL expert. Given the schema below, write a single "
        "SELECT query that answers the question. Return ONLY the SQL — no "
        "explanation, no markdown, no code fences.\n\n"
        f"Schema:\n{schema_context}\n"
        f"Question: {question}\n\n"
        "SQL:"
    )
    try:
        raw_sql = _call_ollama(sql_prompt)
    except requests.exceptions.RequestException as exc:
        log.exception("Ollama unreachable")
        return jsonify({"error": f"Ollama request failed: {exc}"}), 503

    sql = _strip_fences(raw_sql)
    log.info("Generated SQL: %s", sql)

    # 3. Validate SQL.
    try:
        _validate_sql(sql)
    except ValueError as exc:
        return jsonify({"error": str(exc), "raw_sql": raw_sql}), 422

    # 4. Execute against Postgres.
    try:
        rows = _execute_sql(sql)
    except psycopg2.Error as exc:
        log.exception("Query execution failed")
        return jsonify({"error": f"Query execution failed: {exc}", "sql": sql}), 500

    # 5. Prompt Ollama for a natural-language answer.
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
        answer = _call_ollama(answer_prompt)
    except requests.exceptions.RequestException as exc:
        log.exception("Ollama unreachable for answer step")
        return jsonify({"error": f"Ollama answer step failed: {exc}", "sql": sql}), 503

    return jsonify(
        {
            "answer": answer,
            "sql": sql,
            "data_preview": json.loads(json.dumps(rows, default=_json_default)),
        }
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
