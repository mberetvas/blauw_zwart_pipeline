"""SQL guardrails: validation (sqlglot + regex), fence stripping, schema rewriting."""

from __future__ import annotations

import re

import sqlglot
from sqlglot import exp
from sqlglot.errors import ParseError

# ---------------------------------------------------------------------------
# Security: forbidden SQL keywords (legacy belt-and-braces second pass).
# The primary check is now AST-based via sqlglot; this regex remains so any
# input the legacy validator rejected is still rejected.
# ---------------------------------------------------------------------------

_MUTATING = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|TRUNCATE|ALTER|CREATE|REPLACE"
    r"|GRANT|REVOKE|EXECUTE|EXEC|CALL|COPY|VACUUM|ANALYZE|COMMENT"
    r"|LOCK|CLUSTER|REINDEX|REFRESH|SET\s+ROLE|RESET)\b",
    re.IGNORECASE,
)

# AST node types that imply mutation or otherwise unsafe operations. Any
# occurrence anywhere in the parsed tree causes rejection.
_MUTATING_AST_TYPES: tuple[type[exp.Expression], ...] = (
    exp.Insert,
    exp.Update,
    exp.Delete,
    exp.Drop,
    exp.Create,
    exp.Alter,
    exp.AlterColumn,
    exp.TruncateTable,
    exp.Merge,
    exp.Copy,
    exp.Command,  # catch-all for unparsed statements like GRANT / REVOKE
)


def _validate_sql_with_sqlglot(sql: str) -> None:
    """Parse-only validation with sqlglot (Postgres dialect).

    Raises ``ValueError`` when the SQL fails to parse, contains more than one
    top-level statement, or has any mutating AST node anywhere in the tree.
    """
    try:
        statements = sqlglot.parse(sql, dialect="postgres")
    except ParseError as exc:
        raise ValueError(f"Generated SQL failed to parse (sqlglot): {exc}") from exc

    statements = [s for s in statements if s is not None]
    if not statements:
        raise ValueError("Generated SQL is empty after parsing.")
    if len(statements) > 1:
        raise ValueError(
            f"Generated SQL must contain exactly one statement; sqlglot parsed {len(statements)}."
        )

    root = statements[0]
    if not isinstance(root, (exp.Select, exp.Subquery, exp.Union, exp.With, exp.Paren)):
        raise ValueError(
            "Generated SQL must be a single SELECT/WITH/UNION read query. "
            f"Got top-level node: {type(root).__name__}"
        )

    for node in root.walk():
        candidate = node[0] if isinstance(node, tuple) else node
        if isinstance(candidate, _MUTATING_AST_TYPES):
            raise ValueError(
                "Generated SQL contains forbidden node "
                f"'{type(candidate).__name__}' (mutation not allowed)."
            )


def _validate_sql(sql: str) -> None:
    """Raise ``ValueError`` if *sql* is not a safe, read-only SELECT statement.

    Two layers of validation run, in order:

    1. **sqlglot** parses the SQL with the Postgres dialect and rejects any
       AST that implies mutation (INSERT/UPDATE/DELETE/DROP/...), parse
       failures, or multiple top-level statements.
    2. The legacy regex check rejects mutating keywords and stray ``;`` chars.
       It exists so any input the previous validator rejected is still
       rejected (belt-and-braces).
    """
    stripped = sql.strip()
    if not stripped:
        raise ValueError("Generated SQL is empty.")

    starts_with = stripped.upper().lstrip("(\n\r\t ")
    if not (starts_with.startswith("SELECT") or starts_with.startswith("WITH")):
        raise ValueError(
            f"Generated SQL must begin with SELECT or WITH. Received: {stripped[:120]!r}"
        )

    _validate_sql_with_sqlglot(stripped)

    if ";" in stripped:
        raise ValueError(
            "Generated SQL must contain exactly one SELECT statement and cannot include "
            "';' inside the query."
        )
    match = _MUTATING.search(stripped)
    if match:
        raise ValueError(f"Generated SQL contains forbidden keyword '{match.group()}'.")


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
