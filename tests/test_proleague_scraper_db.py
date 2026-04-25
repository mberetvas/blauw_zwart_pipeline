"""Unit tests for proleague_scraper.db (psycopg2 stubbed)."""

from __future__ import annotations

import datetime
import json
from typing import Any

import pytest

from proleague_scraper import db as scraper_db

# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class _FakeCursor:
    def __init__(self) -> None:
        self.executed: list[tuple[str, Any]] = []
        self._fetchall: list[tuple] = []
        self._fetchone: tuple | None = None

    def __enter__(self) -> "_FakeCursor":
        return self

    def __exit__(self, *exc: Any) -> None:
        return None

    def execute(self, sql: str, params: Any = None) -> None:
        self.executed.append((sql, params))

    def fetchall(self) -> list[tuple]:
        return list(self._fetchall)

    def fetchone(self) -> tuple | None:
        return self._fetchone


class _FakeConn:
    def __init__(self) -> None:
        self.cur = _FakeCursor()
        self.commits = 0
        self.closed = False

    def cursor(self) -> _FakeCursor:
        return self.cur

    def commit(self) -> None:
        self.commits += 1

    def close(self) -> None:
        self.closed = True


@pytest.fixture(autouse=True)
def _reset_ready_dict():
    """Clear the per-connection ensure cache between tests."""
    scraper_db._conn_player_stats_ready.clear()
    yield
    scraper_db._conn_player_stats_ready.clear()


# ---------------------------------------------------------------------------
# get_connection
# ---------------------------------------------------------------------------


def test_get_connection_raises_without_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(RuntimeError, match=r"DATABASE_URL"):
        scraper_db.get_connection()


def test_get_connection_uses_psycopg2_connect(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql://x/y")
    sentinel = object()
    monkeypatch.setattr(scraper_db.psycopg2, "connect", lambda url: sentinel)
    assert scraper_db.get_connection() is sentinel


# ---------------------------------------------------------------------------
# ensure_player_stats_table
# ---------------------------------------------------------------------------


def test_ensure_player_stats_table_runs_ddl_and_grants() -> None:
    conn = _FakeConn()
    scraper_db.ensure_player_stats_table(conn)

    # First exec is the CREATE TABLE block
    sql0, _ = conn.cur.executed[0]
    assert "CREATE TABLE IF NOT EXISTS raw_data.player_stats" in sql0
    # SAVEPOINT then GRANT statements
    joined = " | ".join(s for s, _ in conn.cur.executed)
    assert "SAVEPOINT grant_llm_reader_player_stats" in joined
    assert "GRANT USAGE ON SCHEMA raw_data TO llm_reader" in joined
    assert "GRANT SELECT ON raw_data.player_stats TO llm_reader" in joined
    assert conn.commits == 1


def _make_pg_error(msg: str, pgcode: str) -> Exception:
    """Build a psycopg2.Error subclass with the given pgcode as a class attr.

    The C-level ``pgcode`` slot is readonly on instances, so we attach it via a
    one-shot subclass.
    """
    cls = type("_PgError", (scraper_db.psycopg2.Error,), {"pgcode": pgcode})
    return cls(msg)


def test_ensure_player_stats_table_swallows_undefined_role() -> None:
    from psycopg2 import errorcodes

    conn = _FakeConn()
    real_execute = conn.cur.execute

    def execute(sql: str, params: Any = None) -> None:
        if "GRANT USAGE" in sql:
            raise _make_pg_error("role missing", errorcodes.UNDEFINED_OBJECT)
        real_execute(sql, params)

    conn.cur.execute = execute  # type: ignore[method-assign]
    scraper_db.ensure_player_stats_table(conn)
    # Should still commit
    assert conn.commits == 1


def test_ensure_player_stats_table_reraises_unknown_pg_error() -> None:
    conn = _FakeConn()
    real_execute = conn.cur.execute

    def execute(sql: str, params: Any = None) -> None:
        if "GRANT USAGE" in sql:
            raise _make_pg_error("other failure", "XX000")
        real_execute(sql, params)

    conn.cur.execute = execute  # type: ignore[method-assign]
    with pytest.raises(scraper_db.psycopg2.Error):
        scraper_db.ensure_player_stats_table(conn)


# ---------------------------------------------------------------------------
# upsert_players
# ---------------------------------------------------------------------------


def _player(player_id: str = "p1") -> dict[str, Any]:
    return {
        "player_id": player_id,
        "slug": "alice",
        "name": "Alice",
        "position": "FW",
        "field_position": "ST",
        "shirt_number": 9,
        "image_url": "https://x/img.png",
        "profile": {"age": 25},
        "stats": [{"goals": 3}],
        "competition": "Pro League",
    }


def test_upsert_players_writes_and_commits() -> None:
    conn = _FakeConn()
    n = scraper_db.upsert_players(
        conn, [_player("p1"), _player("p2")], "https://src", "2026-04-25T00:00:00Z"
    )
    assert n == 2
    # Ensure DDL ran first then 2 upsert executes.
    upsert_calls = [
        (s, p) for s, p in conn.cur.executed if "INSERT INTO raw_data.player_stats" in s
    ]
    assert len(upsert_calls) == 2
    assert upsert_calls[0][1]["player_id"] == "p1"
    assert upsert_calls[0][1]["profile"] == json.dumps({"age": 25})
    assert upsert_calls[0][1]["stats"] == json.dumps([{"goals": 3}])
    assert conn.commits >= 1


def test_upsert_players_skips_error_or_missing_id() -> None:
    conn = _FakeConn()
    rows = [
        {"error": "boom"},
        {"player_id": "", "name": "noid"},
        _player("p1"),
    ]
    n = scraper_db.upsert_players(conn, rows, "src", "ts")
    assert n == 1


def test_upsert_players_returns_zero_when_all_skipped() -> None:
    conn = _FakeConn()
    n = scraper_db.upsert_players(conn, [{"error": "x"}, {"error": "y"}], "s", "t")
    assert n == 0


# ---------------------------------------------------------------------------
# get_players
# ---------------------------------------------------------------------------


def test_get_players_normalises_rows() -> None:
    conn = _FakeConn()
    ts = datetime.datetime(2026, 4, 25, 12, 0, 0)
    conn.cur._fetchall = [
        (
            "p1",
            "alice",
            "Alice",
            "FW",
            "ST",
            9,
            "https://x/img.png",
            {"age": 25},
            [{"goals": 3}],
            "Pro League",
            "https://src",
            ts,
        ),
        (
            "p2",
            "bob",
            "Bob",
            None,
            None,
            None,
            None,
            '{"age": 30}',
            '[{"goals": 1}]',
            None,
            None,
            None,
        ),
    ]
    out = scraper_db.get_players(conn)
    assert len(out) == 2
    assert out[0]["player_id"] == "p1"
    assert out[0]["profile"] == {"age": 25}
    assert out[0]["stats"] == [{"goals": 3}]
    assert out[0]["scraped_at"] == ts.isoformat()
    # Second row exercises JSON-string and None branches.
    assert out[1]["position"] == ""
    assert out[1]["image_url"] == ""
    assert out[1]["profile"] == {"age": 30}
    assert out[1]["stats"] == [{"goals": 1}]
    assert out[1]["scraped_at"] is None


# ---------------------------------------------------------------------------
# count_players
# ---------------------------------------------------------------------------


def test_count_players_returns_int() -> None:
    conn = _FakeConn()
    conn.cur._fetchone = (42,)
    assert scraper_db.count_players(conn) == 42
    assert any("SELECT COUNT(*)" in s for s, _ in conn.cur.executed)
