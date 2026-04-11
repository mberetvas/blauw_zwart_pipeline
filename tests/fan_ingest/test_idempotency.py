"""Idempotent insert on (kafka_topic, kafka_partition, kafka_offset)."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest

from fan_ingest import db


def _sample_row() -> dict:
    return {
        "kafka_topic": "fan_events",
        "kafka_partition": 0,
        "kafka_offset": 42,
        "event_type": "merch_purchase",
        "event_time": datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC),
        "payload_json": {"event": "merch_purchase"},
    }


def test_insert_sql_uses_on_conflict_coord() -> None:
    assert "ON CONFLICT (kafka_topic, kafka_partition, kafka_offset)" in db.INSERT_FAN_EVENT_SQL
    assert "DO NOTHING" in db.INSERT_FAN_EVENT_SQL


@pytest.mark.parametrize("returned_id, expected", [(1, True), (None, False)])
def test_insert_fan_event_row_return_matches_returning(
    returned_id: int | None, expected: bool
) -> None:
    pool = AsyncMock()
    pool.fetchval = AsyncMock(return_value=returned_id)

    async def _run() -> bool:
        return await db.insert_fan_event_row(pool, _sample_row())

    assert asyncio.run(_run()) is expected
    pool.fetchval.assert_awaited_once()
    assert "ON CONFLICT" in pool.fetchval.await_args.args[0]
