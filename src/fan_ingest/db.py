"""Manage asyncpg connections and idempotent writes for ingested fan events.

The ingestion service stores every Kafka message once per topic/partition/offset
triple. This module ensures the target table exists, exposes the insert SQL used
by partition workers, and provides structured logging helpers for DB failures.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import asyncpg

logger = logging.getLogger("fan_ingest.db")

# Same DDL as docker/postgres/init/001_fan_events_ingested.sql — run at runtime so
# existing DB volumes (created before raw_data schema) get the table without a manual migration.
_ENSURE_FAN_EVENTS_SQL = """
CREATE SCHEMA IF NOT EXISTS raw_data;
CREATE TABLE IF NOT EXISTS raw_data.fan_events_ingested (
    id               BIGSERIAL   PRIMARY KEY,
    ingested_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    kafka_topic      TEXT        NOT NULL,
    kafka_partition  INTEGER     NOT NULL CHECK (kafka_partition >= 0),
    kafka_offset     BIGINT      NOT NULL,
    event_type       TEXT        NOT NULL,
    event_time       TIMESTAMPTZ,
    payload_json     JSONB       NOT NULL,
    CONSTRAINT fan_events_ingested_kafka_coord_uniq UNIQUE (
        kafka_topic,
        kafka_partition,
        kafka_offset
    )
);
"""

INSERT_FAN_EVENT_SQL = """
INSERT INTO raw_data.fan_events_ingested (
    kafka_topic, kafka_partition, kafka_offset, event_type, event_time, payload_json
) VALUES ($1, $2, $3, $4, $5, $6::jsonb)
ON CONFLICT (kafka_topic, kafka_partition, kafka_offset) DO NOTHING
RETURNING id
"""


async def create_pool(dsn: str, *, min_size: int = 1, max_size: int = 10) -> asyncpg.Pool:
    """Create an asyncpg pool and ensure the target table exists.

    Args:
        dsn: PostgreSQL connection string.
        min_size: Minimum pool size.
        max_size: Maximum pool size.

    Returns:
        Ready-to-use asyncpg pool.
    """
    pool = await asyncpg.create_pool(dsn, min_size=min_size, max_size=max_size)
    await ensure_fan_events_table(pool)
    return pool


async def ensure_fan_events_table(pool: asyncpg.Pool) -> None:
    """Create ``raw_data.fan_events_ingested`` if it does not already exist.

    Args:
        pool: Asyncpg pool used to execute the idempotent DDL.

    Note:
        Docker init scripts only run on empty data volumes, so runtime DDL keeps
        upgraded local environments from needing a manual migration step.
    """
    async with pool.acquire() as conn:
        await conn.execute(_ENSURE_FAN_EVENTS_SQL)
    logger.debug("ensure_fan_events_table: raw_data.fan_events_ingested ready")


async def insert_fan_event_row(pool: asyncpg.Pool, row: dict[str, Any]) -> bool:
    """Insert one ingested Kafka message into Postgres.

    Args:
        pool: Asyncpg pool used for the insert.
        row: Parsed ingestion row from :func:`fan_ingest.records.kafka_message_to_row`.

    Returns:
        ``True`` when a new row was inserted, or ``False`` when the unique
        topic/partition/offset constraint turned it into an idempotent no-op.
    """
    row_id = await pool.fetchval(
        INSERT_FAN_EVENT_SQL,
        row["kafka_topic"],
        row["kafka_partition"],
        row["kafka_offset"],
        row["event_type"],
        row["event_time"],
        json.dumps(row["payload_json"], ensure_ascii=False, separators=(",", ":")),
    )
    return row_id is not None


def log_write_error(
    *,
    kafka_topic: str,
    kafka_partition: int,
    kafka_offset: int,
) -> None:
    """Log a database write failure with Kafka coordinates attached.

    Args:
        kafka_topic: Topic name for the failed message.
        kafka_partition: Partition number for the failed message.
        kafka_offset: Offset for the failed message.
    """
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
