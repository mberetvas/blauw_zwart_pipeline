"""SQL guardrails: validation, fence stripping, schema qualifier rewriting."""

from __future__ import annotations

import re

# ---------------------------------------------------------------------------
# Security: forbidden SQL keywords that would mutate state
# ---------------------------------------------------------------------------

_MUTATING = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|TRUNCATE|ALTER|CREATE|REPLACE"
    r"|GRANT|REVOKE|EXECUTE|EXEC|CALL|COPY|VACUUM|ANALYZE|COMMENT"
    r"|LOCK|CLUSTER|REINDEX|REFRESH|SET\s+ROLE|RESET)\b",
    re.IGNORECASE,
)


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


def _rewrite_layer_schema_qualifiers(sql: str) -> str:
    """Map dbt layer labels used as schema qualifiers to dbt_dev.

    Some smaller LLMs infer that "Layer: intermediate" means a SQL schema and
    emit relation names such as intermediate.match_events. In this project, dbt
    builds all relations into the single dbt_dev schema.
    """
    return re.sub(r"\b(?:staging|intermediate|marts)\.(\w+)\b", r"dbt_dev.\1", sql)
