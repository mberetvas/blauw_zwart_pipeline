"""asyncpg pool and idempotent inserts for fan_events_ingested."""

from __future__ import annotations

import logging
from typing import Any

import asyncpg

logger = logging.getLogger("fan_ingest.db")

INSERT_FAN_EVENT_SQL = """
INSERT INTO fan_events_ingested (
    kafka_topic, kafka_partition, kafka_offset, event_type, event_time, payload_json
) VALUES ($1, $2, $3, $4, $5, $6::jsonb)
ON CONFLICT (kafka_topic, kafka_partition, kafka_offset) DO NOTHING
RETURNING id
"""


async def create_pool(dsn: str, *, min_size: int = 1, max_size: int = 10) -> asyncpg.Pool:
    return await asyncpg.create_pool(dsn, min_size=min_size, max_size=max_size)


async def insert_fan_event_row(pool: asyncpg.Pool, row: dict[str, Any]) -> bool:
    """Insert one row; True if inserted, False on unique conflict (idempotent no-op)."""
    row_id = await pool.fetchval(
        INSERT_FAN_EVENT_SQL,
        row["kafka_topic"],
        row["kafka_partition"],
        row["kafka_offset"],
        row["event_type"],
        row["event_time"],
        row["payload_json"],
    )
    return row_id is not None


def log_write_error(
    *,
    kafka_topic: str,
    kafka_partition: int,
    kafka_offset: int,
) -> None:
    """Log a DB failure; call from an ``except`` block (uses ``exc_info=True``)."""
    logger.error(
        "ingest_db_error topic=%s partition=%s offset=%s",
        kafka_topic,
        kafka_partition,
        kafka_offset,
        exc_info=True,
        extra={
            "kafka_topic": kafka_topic,
            "kafka_partition": kafka_partition,
            "kafka_offset": kafka_offset,
        },
    )
