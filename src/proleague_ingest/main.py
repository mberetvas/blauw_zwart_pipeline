"""CLI entry point for the proleague-ingest consumer service.

Reads configuration from environment variables:

    KAFKA_BOOTSTRAP_SERVERS   — default broker:29092
    SCRAPER_KAFKA_TOPIC       — default player_stats
    SCRAPER_KAFKA_CONSUMER_GROUP — default scraper-ingest-local
    DATABASE_URL              — required; write-access Postgres URL
"""

from __future__ import annotations

import logging
import os
import sys

from .consumer import run_consumer


def _env(name: str, default: str) -> str:
    v = os.environ.get(name)
    return v if v is not None and v != "" else default


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s %(name)s %(message)s",
    )

    bootstrap = _env("KAFKA_BOOTSTRAP_SERVERS", "broker:29092")
    topic = _env("SCRAPER_KAFKA_TOPIC", "player_stats")
    group = _env("SCRAPER_KAFKA_CONSUMER_GROUP", "scraper-ingest-local")
    database_url = os.environ.get("DATABASE_URL", "").strip()

    if not database_url:
        logging.error("DATABASE_URL is required")
        sys.exit(1)

    run_consumer(
        bootstrap_servers=bootstrap,
        topic=topic,
        consumer_group=group,
        database_url=database_url,
    )


if __name__ == "__main__":
    main()
