"""LangChain tools exposed to the SQL agent (all read-only).

These tools let the agent discover the warehouse schema and run safe SELECT
queries against the ``llm_reader`` Postgres role, instead of being given the
full schema in the system prompt.

Read-only by construction
-------------------------
* All SQL goes through :func:`frontend_app.sql_agent.database._run_read_query`,
  which connects as the ``llm_reader`` role (revoked of write privileges) and
  enforces a 10s ``statement_timeout``.
* Only :func:`execute_select` accepts free-form SQL, and it routes the SQL
  through :mod:`frontend_app.sql_agent.guardrails` (sqlglot AST validation +
  legacy regex check) before execution.
* All identifier-bearing tool args are whitelisted against the live
  ``information_schema`` listing for the dbt schema before any SQL is built.
* Result payloads are size-capped (``_MAX_*`` constants) to keep tool round
  trips small in the agent's context window.
"""

from __future__ import annotations

import json
import os
import re
import time
from typing import Any

from langchain_core.tools import tool

from common.logging_setup import get_logger

from .database import _execute_sql, _json_default, _run_read_query
from .guardrails import _rewrite_layer_schema_qualifiers, _strip_fences, _validate_sql
from .schema_context import _resolve_schema_paths
from .semantic_layer import load_semantic_layer

try:
    import yaml
except ImportError:  # pragma: no cover — yaml comes with the api extra
    yaml = None  # type: ignore[assignment]

log = get_logger(__name__)

_MAX_TABLES_RETURNED = 200
_MAX_COLUMNS_RETURNED = 300
_MAX_SEARCH_RESULTS = 100
_MAX_SAMPLE_ROWS = 10
_DEFAULT_SAMPLE_ROWS = 5
_VALID_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _dbt_schema() -> str:
    return os.environ.get("DBT_RELATION_SCHEMA", "dbt_dev").strip() or "dbt_dev"


def _yaml_models_index() -> dict[str, dict[str, Any]]:
    """Return ``{model_name: {layer, description, columns_by_name}}`` from dbt YAML.

    Empty dict if YAML is not configured or PyYAML is unavailable.
    """
    if yaml is None:
        return {}
    try:
        paths = _resolve_schema_paths()
    except Exception:
        return {}

    out: dict[str, dict[str, Any]] = {}
    for path in paths:
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(data, dict):
            continue
        models = data.get("models")
        if not isinstance(models, list):
            continue
        layer = "unspecified"
        parts = {p.lower() for p in path.parts}
        if "staging" in parts:
            layer = "staging"
        elif "intermediate" in parts:
            layer = "intermediate"
        elif "marts" in parts:
            layer = "marts"

        for m in models:
            if not isinstance(m, dict):
                continue
            name = m.get("name")
            if not isinstance(name, str):
                continue
            cols_by_name: dict[str, dict[str, Any]] = {}
            for col in m.get("columns") or []:
                if isinstance(col, dict) and isinstance(col.get("name"), str):
                    cols_by_name[col["name"]] = col
            out[name] = {
                "layer": layer,
                "description": (m.get("description") or "").strip(),
                "columns_by_name": cols_by_name,
            }
    return out


def _list_relations() -> list[dict[str, str]]:
    """Return live ``{name, layer}`` rows from information_schema for the dbt schema."""
    schema = _dbt_schema()
    rows = _run_read_query(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema = %s AND table_type IN ('BASE TABLE', 'VIEW') "
        "ORDER BY table_name",
        (schema,),
    )
    yaml_index = _yaml_models_index()
    out: list[dict[str, str]] = []
    for row in rows:
        name = row["table_name"]
        layer = yaml_index.get(name, {}).get("layer", "unspecified")
        out.append({"name": name, "layer": layer})
    return out


def _ensure_known_table(table: str) -> str:
    """Whitelist *table* against live information_schema; return validated name."""
    if not isinstance(table, str) or not _VALID_IDENT.match(table):
        raise ValueError(
            f"Invalid table identifier: {table!r}. "
            "Must match [A-Za-z_][A-Za-z0-9_]*."
        )
    known = {r["name"] for r in _list_relations()}
    if table not in known:
        raise ValueError(
            f"Unknown table {table!r} in schema {_dbt_schema()!r}. "
            "Call list_tables to see valid options."
        )
    return table


def _truncate(items: list[Any], cap: int, label: str) -> list[Any]:
    if len(items) <= cap:
        return items
    truncated = items[:cap]
    truncated.append(
        {
            "_truncated": True,
            "_message": (
                f"{label} list truncated to {cap} of {len(items)} entries to bound prompt size."
            ),
        }
    )
    return truncated


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


@tool
def list_tables() -> str:
    """List all tables and views available to the SQL agent.

    Returns a JSON array of ``{"name": <table_name>, "layer": <layer>}`` where
    layer is one of ``staging``, ``intermediate``, ``marts``, ``unspecified``.
    Always call this first when you need to discover what data is available.
    """
    log.debug(
        "task=list_tables previous=agent_requested_schema next=query_information_schema"
    )
    try:
        rows = _list_relations()
    except Exception as exc:
        return json.dumps({"error": f"list_tables failed: {exc}"})
    payload = _truncate(rows, _MAX_TABLES_RETURNED, "Tables")
    return json.dumps(payload, default=_json_default)


@tool
def describe_table(table: str) -> str:
    """Describe one table: its columns (name, data_type, description) and table description.

    Args:
        table: The unqualified table name (e.g. "mart_fan_loyalty"). Must be one
            of the names returned by ``list_tables``.

    Returns a JSON object with keys ``name``, ``description``, ``columns``.
    """
    log.debug(
        "task=describe_table previous=table_selected next=query_column_metadata table={}",
        table,
    )
    try:
        validated = _ensure_known_table(table)
    except ValueError as exc:
        return json.dumps({"error": str(exc)})

    schema = _dbt_schema()
    try:
        rows = _run_read_query(
            "SELECT column_name, data_type, is_nullable "
            "FROM information_schema.columns "
            "WHERE table_schema = %s AND table_name = %s "
            "ORDER BY ordinal_position",
            (schema, validated),
        )
    except Exception as exc:
        return json.dumps({"error": f"describe_table failed: {exc}"})

    yaml_entry = _yaml_models_index().get(validated, {})
    yaml_cols = yaml_entry.get("columns_by_name", {})
    columns = []
    for r in rows:
        name = r["column_name"]
        yaml_col = yaml_cols.get(name) or {}
        columns.append(
            {
                "name": name,
                "data_type": r["data_type"],
                "nullable": r["is_nullable"] == "YES",
                "description": (yaml_col.get("description") or "").strip(),
            }
        )
    columns = _truncate(columns, _MAX_COLUMNS_RETURNED, "Columns")
    payload = {
        "name": validated,
        "layer": yaml_entry.get("layer", "unspecified"),
        "description": yaml_entry.get("description", ""),
        "columns": columns,
    }
    return json.dumps(payload, default=_json_default)


@tool
def search_columns(pattern: str, limit: int = 20) -> str:
    """Search columns by name across all tables in the dbt schema (case-insensitive ILIKE).

    Args:
        pattern: Substring or SQL ILIKE pattern (e.g. ``"%spend%"``). Plain text
            without ``%`` is wrapped automatically.
        limit: Max results to return (capped at 100).

    Returns a JSON array of ``{table, column, data_type, description}``.
    """
    log.debug(
        "task=search_columns previous=search_requested "
        "next=query_information_schema pattern={} limit={}",
        pattern,
        limit,
    )
    if not isinstance(pattern, str) or not pattern.strip():
        return json.dumps({"error": "pattern must be a non-empty string"})
    schema = _dbt_schema()
    cap = max(1, min(int(limit), _MAX_SEARCH_RESULTS))
    pat = pattern.strip()
    if "%" not in pat:
        pat = f"%{pat}%"
    try:
        rows = _run_read_query(
            "SELECT table_name, column_name, data_type "
            "FROM information_schema.columns "
            "WHERE table_schema = %s AND column_name ILIKE %s "
            "ORDER BY table_name, ordinal_position "
            "LIMIT %s",
            (schema, pat, cap),
        )
    except Exception as exc:
        return json.dumps({"error": f"search_columns failed: {exc}"})

    yaml_idx = _yaml_models_index()
    out = []
    for r in rows:
        yc = (yaml_idx.get(r["table_name"], {}).get("columns_by_name", {}) or {}).get(
            r["column_name"], {}
        )
        out.append(
            {
                "table": r["table_name"],
                "column": r["column_name"],
                "data_type": r["data_type"],
                "description": (yc.get("description") or "").strip(),
            }
        )
    return json.dumps(out, default=_json_default)


@tool
def sample_table(table: str, limit: int = _DEFAULT_SAMPLE_ROWS) -> str:
    """Return a small sample of rows from one table to inspect its shape.

    Args:
        table: The unqualified table name. Must be in ``list_tables``.
        limit: Number of rows to return (capped at 10).

    Returns a JSON array of row objects.
    """
    log.debug(
        "task=sample_table previous=table_selected next=fetch_preview_rows table={} limit={}",
        table,
        limit,
    )
    try:
        validated = _ensure_known_table(table)
    except ValueError as exc:
        return json.dumps({"error": str(exc)})

    cap = max(1, min(int(limit), _MAX_SAMPLE_ROWS))
    schema = _dbt_schema()
    try:
        rows = _run_read_query(
            f'SELECT * FROM "{schema}"."{validated}" LIMIT {cap}'
        )
    except Exception as exc:
        return json.dumps({"error": f"sample_table failed: {exc}"})
    return json.dumps(rows, default=_json_default)


@tool
def get_semantic_layer() -> str:
    """Return the semantic layer (subjects, metrics, dimensions, joins, rules, style).

    Use this once at the start of the session to learn which mart tables to
    prefer for which subject (fans, matches, retail), what metrics are
    pre-defined, and the answer-style guidelines.

    Returns a JSON object (the parsed semantic layer YAML), or ``{}`` when no
    semantic layer file is configured.
    """
    log.debug(
        "task=get_semantic_layer previous=agent_requested_domain_rules next=load_semantic_yaml"
    )
    try:
        data = load_semantic_layer()
    except Exception as exc:
        return json.dumps({"error": f"get_semantic_layer failed: {exc}"})
    return json.dumps(data, default=_json_default)


@tool
def execute_select(sql: str) -> str:
    """Execute a single read-only SELECT/WITH query and return the rows.

    The SQL is sanitized (markdown fences stripped, dbt layer prefixes
    rewritten to ``dbt_dev.<table>``) and validated with sqlglot before
    execution. The query is wrapped in an outer ``LIMIT 100`` and runs with a
    10s ``statement_timeout`` as the ``llm_reader`` Postgres role.

    Args:
        sql: A single PostgreSQL SELECT or WITH ... SELECT statement. No
            trailing semicolon. No DDL/DML — those are rejected.

    Returns a JSON object: on success ``{"rows": [...], "row_count": N, "sql": "..."}``;
    on validation failure ``{"error": "...", "phase": "validation", "sql": "..."}``;
    on execution failure ``{"error": "...", "phase": "execution", "sql": "..."}``.
    Always inspect the result; on validation errors, fix the SQL and retry.
    """
    if not isinstance(sql, str) or not sql.strip():
        return json.dumps(
            {"error": "sql must be a non-empty string", "phase": "validation"}
        )
    cleaned = _rewrite_layer_schema_qualifiers(_strip_fences(sql))
    log.debug(
        "task=execute_select_validate previous=sql_received next=run_guardrails sql_preview={}",
        cleaned[:200],
    )
    try:
        _validate_sql(cleaned)
    except ValueError as exc:
        log.info("execute_select_validation_failed error={}", exc)
        return json.dumps(
            {"error": str(exc), "phase": "validation", "sql": cleaned}
        )
    log.debug(
        "task=execute_select_run previous=validation_passed next=query_database sql_preview={}",
        cleaned[:200],
    )
    t0 = time.perf_counter()
    try:
        rows = _execute_sql(cleaned)
    except Exception as exc:
        log.info("execute_select_runtime_failed error={}", exc)
        return json.dumps(
            {"error": str(exc), "phase": "execution", "sql": cleaned}
        )
    elapsed_ms = (time.perf_counter() - t0) * 1000
    log.info("execute_select_complete rows={} elapsed_ms={:.0f}", len(rows), elapsed_ms)
    return json.dumps(
        {"rows": rows, "row_count": len(rows), "sql": cleaned},
        default=_json_default,
    )


# Convenience: one place to grab the full toolkit.
ALL_TOOLS = [
    list_tables,
    describe_table,
    search_columns,
    sample_table,
    get_semantic_layer,
    execute_select,
]

# Tools the repair pass is allowed to call (intentionally limited).
REPAIR_TOOLS = [describe_table, execute_select]
