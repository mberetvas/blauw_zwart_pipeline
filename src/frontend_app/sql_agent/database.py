"""Database execution helpers: connection, read-only query runner, JSON serialisation."""

from __future__ import annotations

import os
from decimal import Decimal
from typing import Any, Sequence

import psycopg2

# Prefer read-only role URL; Compose maps LLM_READER_DATABASE_URL -> DATABASE_URL for this service.
DATABASE_URL = (
    os.environ.get("LLM_READER_DATABASE_URL", "").strip()
    or os.environ.get("DATABASE_URL", "").strip()
)


def _json_default(obj: Any) -> Any:
    """JSON serialiser for Decimal and other non-serialisable Postgres types."""
    if isinstance(obj, Decimal):
        return float(obj)
    raise TypeError(f"Object of type {type(obj)} is not JSON serialisable")


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


def _execute_sql(sql: str) -> list[dict[str, Any]]:
    """Wrap sql in a LIMIT guard and execute it as the llm_reader role."""
    wrapped = f"SELECT * FROM (\n{sql}\n) AS llm_query LIMIT 50"
    return _run_read_query(wrapped)
