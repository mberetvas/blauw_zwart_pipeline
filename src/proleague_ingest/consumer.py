"""Synchronous Kafka consumer: player_stats topic → Postgres player_stats table.

Each Kafka message carries a JSON envelope (schema v1) containing a single player dict.
Messages are processed and committed one-by-one; throughput is ~30 messages/day so
synchronous psycopg2 is more than sufficient.

Idempotency: ``proleague_scraper.db.upsert_players`` uses
``ON CONFLICT (player_id) DO UPDATE`` so duplicate messages or re-runs are safe.

Message schema (v1)
-------------------
.. code-block:: json

    {
        "_schema_version": 1,
        "event_type": "player_stats_scraped",
        "source_url": "https://...",
        "scraped_at": "2026-04-13T21:00:00Z",
        "player": { ...normalised player dict... }
    }
"""

from __future__ import annotations

import json
import logging
import signal
import time
from typing import Any

from confluent_kafka import Consumer, KafkaError, KafkaException

from proleague_scraper.db import upsert_players

log = logging.getLogger("proleague_ingest.consumer")

SUPPORTED_SCHEMA_VERSION = 1


def parse_envelope(raw_value: bytes) -> dict[str, Any]:
    """Decode and validate a player_stats Kafka message.

    Raises ``ValueError`` with a descriptive message on any validation failure so
    the caller can log-and-skip bad messages without crashing the consumer loop.
    """
    try:
        obj = json.loads(raw_value.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"JSON decode error: {exc}") from exc
    if not isinstance(obj, dict):
        raise ValueError(f"expected JSON object, got {type(obj).__name__}")
    version = obj.get("_schema_version")
    if version != SUPPORTED_SCHEMA_VERSION:
        raise ValueError(f"unsupported _schema_version: {version!r}")
    if obj.get("event_type") != "player_stats_scraped":
        raise ValueError(f"unexpected event_type: {obj.get('event_type')!r}")
    player = obj.get("player")
    if not isinstance(player, dict) or not player.get("player_id"):
        raise ValueError("missing or invalid 'player' field")
    return obj


def run_consumer(
    *,
    bootstrap_servers: str,
    topic: str,
    consumer_group: str,
    database_url: str,
) -> None:
    """Poll *topic* and upsert each player into ``public.player_stats``.

    Runs until SIGINT/SIGTERM; commits offsets only after a successful upsert.
    DB reconnects automatically on connection loss.
    """
    conf = {
        "bootstrap.servers": bootstrap_servers,
        "group.id": consumer_group,
        "enable.auto.commit": False,
        "auto.offset.reset": "earliest",
    }
    consumer = Consumer(conf)
    consumer.subscribe([topic])

    stop = False

    def _handle_signal(signum, _frame):  # noqa: ANN001
        nonlocal stop
        log.info("ingest_shutdown_requested signal=%s", signum)
        stop = True

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    log.info(
        "proleague_ingest_started topic=%s group=%s bootstrap=%s",
        topic,
        consumer_group,
        bootstrap_servers,
    )

    # Lazy DB connection — opened on first message, reconnected after errors.
    conn = None
    processed = skipped = errors = 0
    try:
        while not stop:
            msg = consumer.poll(0.5)
            if msg is None:
                continue
            if msg.error():
                err = msg.error()
                if err.code() == KafkaError._PARTITION_EOF:
                    continue
                log.error(
                    "consumer_error topic=%s partition=%s: %s",
                    msg.topic(),
                    msg.partition(),
                    err,
                )
                continue

            try:
                envelope = parse_envelope(msg.value())
            except ValueError as exc:
                log.warning(
                    "ingest_parse_skip topic=%s partition=%s offset=%s error=%s",
                    msg.topic(),
                    msg.partition(),
                    msg.offset(),
                    exc,
                )
                # Commit so we don't stall on persistently bad messages.
                consumer.commit(msg, asynchronous=False)
                skipped += 1
                continue

            player = envelope["player"]
            source_url = envelope.get("source_url", "")
            scraped_at = envelope.get("scraped_at", "")

            # Lazy DB connect / reconnect.
            if conn is None or conn.closed:
                conn = _connect(database_url)

            try:
                upsert_players(conn, [player], source_url, scraped_at)
                consumer.commit(msg, asynchronous=False)
                processed += 1
                log.info(
                    "ingest_upserted player_id=%s name=%s topic=%s partition=%s offset=%s",
                    player.get("player_id"),
                    player.get("name"),
                    msg.topic(),
                    msg.partition(),
                    msg.offset(),
                )
            except Exception as exc:
                errors += 1
                log.error(
                    "ingest_db_error player_id=%s topic=%s partition=%s offset=%s: %s",
                    player.get("player_id"),
                    msg.topic(),
                    msg.partition(),
                    msg.offset(),
                    exc,
                    exc_info=True,
                )
                # Close and reconnect on next iteration.
                try:
                    conn.close()
                except Exception:
                    pass
                conn = None
                time.sleep(2.0)

    except KafkaException:
        log.exception("consumer_fatal_kafka_error")
    finally:
        consumer.close()
        if conn and not conn.closed:
            conn.close()
        log.info(
            "proleague_ingest_stopped processed=%d skipped=%d errors=%d",
            processed,
            skipped,
            errors,
        )


def _connect(database_url: str):  # noqa: ANN001
    """Open a psycopg2 connection from an explicit URL (bypasses DATABASE_URL env var)."""
    import psycopg2

    return psycopg2.connect(database_url)
