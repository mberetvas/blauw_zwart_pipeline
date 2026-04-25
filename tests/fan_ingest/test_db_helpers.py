"""Phase 3 branch-fill tests for fan_ingest.db.

Covers the public async helpers (create_pool, ensure_fan_events_table,
insert_fan_event_row, log_write_error) without a real Postgres.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any
from unittest.mock import AsyncMock, MagicMock

from fan_ingest import db as db_mod


def test_create_pool_invokes_asyncpg_and_ensures_table(monkeypatch) -> None:
    pool = MagicMock()
    pool.acquire.return_value.__aenter__ = AsyncMock(
        return_value=MagicMock(execute=AsyncMock(return_value=None))
    )
    pool.acquire.return_value.__aexit__ = AsyncMock(return_value=None)

    async def fake_create_pool(dsn, min_size, max_size):
        return pool

    monkeypatch.setattr(db_mod.asyncpg, "create_pool", fake_create_pool)

    out = asyncio.run(db_mod.create_pool("postgresql://x/y", min_size=2, max_size=5))
    assert out is pool


def test_ensure_fan_events_table_executes_ddl() -> None:
    conn = MagicMock()
    conn.execute = AsyncMock(return_value=None)

    pool = MagicMock()
    pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
    pool.acquire.return_value.__aexit__ = AsyncMock(return_value=None)

    asyncio.run(db_mod.ensure_fan_events_table(pool))
    conn.execute.assert_awaited_once()
    sql = conn.execute.await_args.args[0]
    assert "CREATE TABLE IF NOT EXISTS raw_data.fan_events_ingested" in sql


def test_insert_fan_event_row_returns_true_on_insert() -> None:
    pool = MagicMock()
    pool.fetchval = AsyncMock(return_value=42)

    row: dict[str, Any] = {
        "kafka_topic": "fan_events",
        "kafka_partition": 0,
        "kafka_offset": 7,
        "event_type": "ticket_scan",
        "event_time": "2026-04-25T00:00:00Z",
        "payload_json": {"a": 1, "ünïcode": "ok"},
    }
    out = asyncio.run(db_mod.insert_fan_event_row(pool, row))
    assert out is True
    args = pool.fetchval.await_args.args
    assert args[0] == db_mod.INSERT_FAN_EVENT_SQL
    assert args[1:6] == (
        "fan_events",
        0,
        7,
        "ticket_scan",
        "2026-04-25T00:00:00Z",
    )
    # JSON payload uses ensure_ascii=False (unicode preserved).
    assert "ünïcode" in args[6]
    assert args[6] == json.dumps(row["payload_json"], ensure_ascii=False, separators=(",", ":"))


def test_insert_fan_event_row_returns_false_on_conflict() -> None:
    pool = MagicMock()
    pool.fetchval = AsyncMock(return_value=None)

    row = {
        "kafka_topic": "t",
        "kafka_partition": 0,
        "kafka_offset": 1,
        "event_type": "x",
        "event_time": None,
        "payload_json": {},
    }
    assert asyncio.run(db_mod.insert_fan_event_row(pool, row)) is False


def test_log_write_error_emits_error_with_extra(caplog) -> None:
    with caplog.at_level(logging.ERROR, logger="fan_ingest.db"):
        try:
            raise RuntimeError("db blew up")
        except RuntimeError:
            db_mod.log_write_error(
                kafka_topic="fan_events", kafka_partition=2, kafka_offset=99
            )

    record = caplog.records[-1]
    assert record.levelname == "ERROR"
    assert "ingest_db_error" in record.getMessage()
    assert getattr(record, "kafka_topic", None) == "fan_events"
    assert getattr(record, "kafka_partition", None) == 2
    assert getattr(record, "kafka_offset", None) == 99
    # exc_info=True populated by the helper.
    assert record.exc_info is not None
