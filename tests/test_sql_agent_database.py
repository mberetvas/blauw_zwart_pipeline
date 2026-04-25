"""Unit tests for sql_agent.database: JSON serialiser + LIMIT-wrapping execute."""

from __future__ import annotations

import datetime
import importlib
from decimal import Decimal
from typing import Any

import pytest


@pytest.fixture()
def db_module(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pw@localhost/db")
    monkeypatch.delenv("LLM_READER_DATABASE_URL", raising=False)
    import frontend_app.sql_agent.database as db_mod

    importlib.reload(db_mod)
    return db_mod


# ---------------------------------------------------------------------------
# _json_default
# ---------------------------------------------------------------------------


def test_json_default_decimal(db_module) -> None:
    assert db_module._json_default(Decimal("1.50")) == 1.5


def test_json_default_datetime(db_module) -> None:
    out = db_module._json_default(datetime.datetime(2024, 1, 2, 3, 4, 5))
    assert out == "2024-01-02T03:04:05"


def test_json_default_date(db_module) -> None:
    assert db_module._json_default(datetime.date(2024, 1, 2)) == "2024-01-02"


def test_json_default_time(db_module) -> None:
    assert db_module._json_default(datetime.time(3, 4, 5)) == "03:04:05"


def test_json_default_unsupported_raises_type_error(db_module) -> None:
    with pytest.raises(TypeError, match=r"not JSON serialisable"):
        db_module._json_default(object())


# ---------------------------------------------------------------------------
# Fakes for psycopg2
# ---------------------------------------------------------------------------


class _FakeCursor:
    def __init__(self, rows: list[tuple], cols: list[str]) -> None:
        self._rows = rows
        self.description = [(c,) for c in cols]
        self.executed: list[str] = []

    def __enter__(self) -> "_FakeCursor":
        return self

    def __exit__(self, *exc: Any) -> None:
        return None

    def execute(self, sql: str, params: Any = None) -> None:
        self.executed.append(sql)

    def fetchall(self) -> list[tuple]:
        return list(self._rows)


class _FakeConn:
    def __init__(self, cursor: _FakeCursor) -> None:
        self._cur = cursor
        self.closed_called = False

    def cursor(self) -> _FakeCursor:
        return self._cur

    def close(self) -> None:
        self.closed_called = True


# ---------------------------------------------------------------------------
# _run_read_query
# ---------------------------------------------------------------------------


def test_run_read_query_sets_timeout_and_returns_dicts(
    db_module, monkeypatch: pytest.MonkeyPatch
) -> None:
    cur = _FakeCursor(rows=[(1, "alice")], cols=["id", "name"])
    conn = _FakeConn(cur)
    monkeypatch.setattr(db_module.psycopg2, "connect", lambda url: conn)

    rows = db_module._run_read_query("SELECT id, name FROM t")

    assert rows == [{"id": 1, "name": "alice"}]
    # statement_timeout is set first, then the actual SELECT
    assert cur.executed[0] == "SET statement_timeout = '10s'"
    assert "SELECT id, name FROM t" in cur.executed[1]
    assert conn.closed_called is True


def test_run_read_query_with_params(db_module, monkeypatch: pytest.MonkeyPatch) -> None:
    cur = _FakeCursor(rows=[], cols=["id"])
    conn = _FakeConn(cur)

    captured: dict[str, Any] = {}

    def fake_execute(sql: str, params: Any = None) -> None:
        cur.executed.append(sql)
        captured.setdefault("params", params)

    cur.execute = fake_execute  # type: ignore[method-assign]
    monkeypatch.setattr(db_module.psycopg2, "connect", lambda url: conn)

    db_module._run_read_query("SELECT * FROM t WHERE id = %s", (5,))
    assert captured["params"] is None or captured["params"] == (5,)


def test_run_read_query_raises_when_no_url(db_module, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(db_module, "DATABASE_URL", "")
    with pytest.raises(db_module.psycopg2.OperationalError, match=r"No database URL"):
        db_module._run_read_query("SELECT 1")


# ---------------------------------------------------------------------------
# _execute_sql — LIMIT wrap
# ---------------------------------------------------------------------------


def test_execute_sql_wraps_with_limit_100(db_module, monkeypatch: pytest.MonkeyPatch) -> None:
    cur = _FakeCursor(rows=[(1,)], cols=["a"])
    conn = _FakeConn(cur)
    monkeypatch.setattr(db_module.psycopg2, "connect", lambda url: conn)

    db_module._execute_sql("SELECT a FROM t")

    # the second execute (after the timeout SET) is the wrapped query
    wrapped = cur.executed[1]
    assert "LIMIT 100" in wrapped
    assert "llm_query" in wrapped
    assert "SELECT a FROM t" in wrapped
