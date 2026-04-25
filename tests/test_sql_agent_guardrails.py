"""Unit tests for SQL guardrails (sqlglot AST + legacy regex)."""

from __future__ import annotations

import pytest

from frontend_app.sql_agent.guardrails import (
    _rewrite_layer_schema_qualifiers,
    _strip_fences,
    _validate_sql,
    _validate_sql_with_sqlglot,
)

# ---------------------------------------------------------------------------
# _validate_sql — happy paths
# ---------------------------------------------------------------------------


def test_validate_sql_allows_plain_select() -> None:
    _validate_sql("SELECT 1")


def test_validate_sql_allows_with_cte() -> None:
    _validate_sql("WITH x AS (SELECT 1 AS a) SELECT a FROM x")


def test_validate_sql_allows_select_wrapped_in_parens() -> None:
    _validate_sql("(SELECT 1)")


def test_validate_sql_allows_lowercase_keywords() -> None:
    _validate_sql("select 1")


def test_validate_sql_allows_union() -> None:
    _validate_sql("SELECT 1 AS a UNION ALL SELECT 2 AS a")


# ---------------------------------------------------------------------------
# _validate_sql — rejection paths
# ---------------------------------------------------------------------------


def test_validate_sql_rejects_empty() -> None:
    with pytest.raises(ValueError, match=r"empty"):
        _validate_sql("")


def test_validate_sql_rejects_whitespace_only() -> None:
    with pytest.raises(ValueError, match=r"empty"):
        _validate_sql("   \n\t  ")


def test_validate_sql_rejects_non_select_prefix() -> None:
    with pytest.raises(ValueError, match=r"begin with SELECT or WITH"):
        _validate_sql("EXPLAIN SELECT 1")


def test_validate_sql_rejects_insert() -> None:
    with pytest.raises(ValueError, match=r"begin with SELECT or WITH"):
        _validate_sql("INSERT INTO t (a) VALUES (1)")


def test_validate_sql_rejects_drop() -> None:
    with pytest.raises(ValueError, match=r"begin with SELECT or WITH"):
        _validate_sql("DROP TABLE t")


def test_validate_sql_rejects_delete_in_cte() -> None:
    with pytest.raises(ValueError, match=r"(?i)delete|mutation not allowed"):
        _validate_sql("WITH d AS (DELETE FROM t RETURNING id) SELECT id FROM d")


def test_validate_sql_rejects_semicolon_in_query() -> None:
    # sqlglot's multi-statement check fires first; legacy regex covers single-stmt + ';'.
    with pytest.raises(ValueError, match=r"(?i)';'|exactly one statement"):
        _validate_sql("SELECT 1 ; SELECT 2")


def test_validate_sql_rejects_trailing_semicolon() -> None:
    with pytest.raises(ValueError, match=r"';'"):
        _validate_sql("SELECT 1;")


def test_validate_sql_rejects_parse_failure() -> None:
    with pytest.raises(ValueError, match=r"(?i)sqlglot|parse"):
        _validate_sql("SELECT FROM WHERE 1 ===")


def test_validate_sql_rejects_forbidden_keyword_via_regex() -> None:
    # GRANT lacks an AST class in our forbidden tuple but is a Command and matched by regex.
    with pytest.raises(ValueError):
        _validate_sql("SELECT 1 /* GRANT */")


# ---------------------------------------------------------------------------
# _validate_sql_with_sqlglot — direct branches
# ---------------------------------------------------------------------------


def test_validate_sql_with_sqlglot_rejects_multiple_statements() -> None:
    with pytest.raises(ValueError, match=r"exactly one statement"):
        _validate_sql_with_sqlglot("SELECT 1; SELECT 2")


def test_validate_sql_with_sqlglot_rejects_top_level_create() -> None:
    with pytest.raises(ValueError, match=r"(?i)single SELECT/WITH/UNION|mutation"):
        _validate_sql_with_sqlglot("CREATE TABLE t (id int)")


def test_validate_sql_with_sqlglot_rejects_truncate() -> None:
    with pytest.raises(ValueError, match=r"(?i)single SELECT|mutation"):
        _validate_sql_with_sqlglot("TRUNCATE TABLE t")


def test_validate_sql_with_sqlglot_rejects_empty_after_parse() -> None:
    # A pure comment parses to no statements → should hit the "empty after parsing" branch.
    with pytest.raises(ValueError, match=r"empty after parsing|parse"):
        _validate_sql_with_sqlglot("-- comment only")


# ---------------------------------------------------------------------------
# _strip_fences
# ---------------------------------------------------------------------------


def test_strip_fences_removes_sql_fence() -> None:
    raw = "```sql\nSELECT 1\n```"
    assert _strip_fences(raw) == "SELECT 1"


def test_strip_fences_removes_bare_fence() -> None:
    raw = "```\nSELECT 1\n```"
    assert _strip_fences(raw) == "SELECT 1"


def test_strip_fences_strips_trailing_semicolons() -> None:
    raw = "SELECT 1;;;"
    assert _strip_fences(raw) == "SELECT 1"


def test_strip_fences_no_fence_passthrough() -> None:
    assert _strip_fences("SELECT 1") == "SELECT 1"


# ---------------------------------------------------------------------------
# _rewrite_layer_schema_qualifiers
# ---------------------------------------------------------------------------


def test_rewrite_replaces_staging() -> None:
    assert _rewrite_layer_schema_qualifiers("SELECT * FROM staging.fans") == "SELECT * FROM dbt_dev.fans"


def test_rewrite_replaces_intermediate_and_marts() -> None:
    sql = "SELECT * FROM intermediate.x JOIN marts.y USING (id)"
    out = _rewrite_layer_schema_qualifiers(sql)
    assert "dbt_dev.x" in out and "dbt_dev.y" in out
    assert "intermediate." not in out and "marts." not in out


def test_rewrite_leaves_unrelated_qualifiers() -> None:
    sql = "SELECT * FROM dbt_dev.fans"
    assert _rewrite_layer_schema_qualifiers(sql) == sql
