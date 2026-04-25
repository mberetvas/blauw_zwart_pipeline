"""Daily scrape scheduler for the Pro League squad.

Runs on startup (configurable via ``SCRAPER_RUN_ON_STARTUP``) then sleeps
``SCRAPER_INTERVAL_HOURS`` between subsequent runs.

On each run, ``scrape_squad`` fetches all player pages and publishes one Kafka
message per valid player to ``SCRAPER_KAFKA_TOPIC``.  The ``proleague-ingest``
consumer service then persists those messages to the ``player_stats`` Postgres table.

Choosing a dedicated service + sleep loop over alternatives
-----------------------------------------------------------
* ``restart: unless-stopped`` only restarts crashed containers — useless for scheduling.
* A cron sidecar (e.g. cron + shell script) requires additional image complexity and
  makes logs hard to stream.
* Mixing the scheduler into the HTTP server couples scrape latency to request handling.
* A dedicated ``proleague-scheduler`` Compose service using the same Docker image with a
  different ``command:`` (matching the ``dbt-scheduler`` pattern already in this stack)
  is the simplest correct solution: one process, structured logs, graceful shutdown.

Message schema (v1)
-------------------
.. code-block:: json

    {
        "_schema_version": 1,
        "event_type":  "player_stats_scraped",
        "source_url":  "https://...",
        "scraped_at":  "2026-04-13T21:00:00Z",
        "player":      { ...normalised player dict... }
    }

Key: ``player_id`` bytes — routes the same player to the same partition so messages
arrive in order for any future ordered-consumer use.

IMPORTANT: Operators must verify proleague.be robots.txt and Terms of Use.
"""

from __future__ import annotations

import json
import os
import time
from typing import Any

from confluent_kafka import KafkaException, Producer

from common.logging_setup import configure_logging, get_logger

from .scraper import DEFAULT_SQUAD_URL, scrape_squad

log = get_logger(__name__)

_SCHEMA_VERSION = 1
_EVENT_TYPE = "player_stats_scraped"


# ---------------------------------------------------------------------------
# Kafka helpers
# ---------------------------------------------------------------------------


def _delivery_report(err: Any, msg: Any) -> None:
    if err:
        log.info("scraper_produce_failed topic={} key={} error={}", msg.topic(), msg.key(), err)
    else:
        log.debug(
            "task=produce_delivery_report previous=message_queued next=continue_batch "
            "topic={} partition={} offset={} key={}",
            msg.topic(),
            msg.partition(),
            msg.offset(),
            msg.key().decode() if msg.key() else None,
        )


def build_envelope(
    player: dict[str, Any],
    *,
    source_url: str,
    scraped_at: str,
) -> bytes:
    """Serialise a player dict into a Kafka message value (UTF-8 JSON)."""
    payload = {
        "_schema_version": _SCHEMA_VERSION,
        "event_type": _EVENT_TYPE,
        "source_url": source_url,
        "scraped_at": scraped_at,
        "player": player,
    }
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()


# ---------------------------------------------------------------------------
# Single scrape run
# ---------------------------------------------------------------------------


def run_once(
    *,
    squad_url: str,
    bootstrap_servers: str,
    topic: str,
) -> int:
    """Scrape the squad and publish one Kafka message per valid player.

    Returns the number of successfully enqueued messages.
    Raises on scrape failure; individual produce errors are logged but not raised.
    """
    log.info("scraper_run_start url={} topic={} bootstrap={}", squad_url, topic, bootstrap_servers)
    t0 = time.monotonic()

    log.debug(
        "task=scrape_squad previous=run_initialized next=fetch_squad_listing url={}",
        squad_url,
    )
    result = scrape_squad(squad_url)
    players: list[dict[str, Any]] = result.get("players", [])
    scraped_at: str = result.get("fetched_at", "")
    source_url: str = result.get("source_url", squad_url)

    valid = [p for p in players if p.get("player_id") and not p.get("error")]
    log.info(
        "scraper_run_scraped total={} valid={} elapsed_s={:.1f}",
        len(players),
        len(valid),
        time.monotonic() - t0,
    )

    producer = Producer({"bootstrap.servers": bootstrap_servers})
    produced = 0
    for player in valid:
        try:
            log.debug(
                "task=produce_player_event previous=validated_player next=enqueue_kafka_message "
                "player_id={} topic={}",
                player["player_id"],
                topic,
            )
            producer.produce(
                topic=topic,
                key=player["player_id"].encode(),
                value=build_envelope(player, source_url=source_url, scraped_at=scraped_at),
                callback=_delivery_report,
            )
            produced += 1
        except KafkaException as exc:
            log.info("scraper_produce_error player_id={} error={}", player["player_id"], exc)

    # Flush ensures all pending deliveries complete before we sleep.
    remaining = producer.flush(timeout=60)
    if remaining:
        log.info("scraper_flush_incomplete remaining={}", remaining)

    log.info(
        "scraper_run_done produced={}/{} elapsed_s={:.1f}",
        produced,
        len(valid),
        time.monotonic() - t0,
    )
    return produced


# ---------------------------------------------------------------------------
# Scheduler entry point
# ---------------------------------------------------------------------------


def main() -> None:
    configure_logging(level=os.environ.get("LOG_LEVEL", "INFO"))

    squad_url = os.environ.get("PROLEAGUE_SQUAD_URL", DEFAULT_SQUAD_URL).strip()
    bootstrap = os.environ.get("KAFKA_BOOTSTRAP_SERVERS", "broker:29092").strip()
    topic = os.environ.get("SCRAPER_KAFKA_TOPIC", "player_stats").strip()
    _raw_interval = os.environ.get("SCRAPER_INTERVAL_HOURS", "24").strip()
    try:
        interval_h = float(_raw_interval)
        if interval_h <= 0:
            raise ValueError("must be positive")
    except ValueError as exc:
        raise SystemExit(
            f"Invalid SCRAPER_INTERVAL_HOURS={_raw_interval!r}: {exc}"
        ) from exc
    run_on_startup = os.environ.get("SCRAPER_RUN_ON_STARTUP", "1").strip() == "1"
    interval_s = interval_h * 3600

    log.info(
        "scheduler_init url={} topic={} interval_h={:.1f} run_on_startup={}",
        squad_url,
        topic,
        interval_h,
        run_on_startup,
    )

    if not run_on_startup:
        log.info("scheduler_waiting_first_interval seconds={:.0f}", interval_s)
        time.sleep(interval_s)

    while True:
        try:
            run_once(squad_url=squad_url, bootstrap_servers=bootstrap, topic=topic)
        except Exception as exc:  # noqa: BLE001
            log.info("scheduler_run_failed error={} next=retry_after_sleep", exc)
        log.info("scheduler_sleeping seconds={:.0f}", interval_s)
        time.sleep(interval_s)


if __name__ == "__main__":
    main()
