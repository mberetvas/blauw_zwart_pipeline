"""CLI entry: consume Kafka NDJSON → Postgres (local Compose)."""

from __future__ import annotations

import argparse
import asyncio
import os
import signal
import sys

from confluent_kafka import Consumer, KafkaException

from common.logging_setup import configure_logging, get_logger
from fan_ingest.db import create_pool
from fan_ingest.runner import IngestRuntime

log = get_logger(__name__)


def _env_or_default(name: str, default: str) -> str:
    v = os.environ.get(name)
    return v if v is not None and v != "" else default


def _build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Ingest fan-events NDJSON from Kafka into Postgres.")
    p.add_argument(
        "--kafka-bootstrap-servers",
        default=_env_or_default("KAFKA_BOOTSTRAP_SERVERS", "broker:29092"),
        help="Bootstrap servers (Compose ingest: broker:29092; env KAFKA_BOOTSTRAP_SERVERS)",
    )
    p.add_argument(
        "--kafka-topic",
        default=_env_or_default("KAFKA_TOPIC", "fan_events"),
        help="Topic name (env KAFKA_TOPIC)",
    )
    p.add_argument(
        "--kafka-consumer-group",
        default=_env_or_default("KAFKA_CONSUMER_GROUP", "fan-ingest-local"),
        help="Consumer group id (env KAFKA_CONSUMER_GROUP)",
    )
    p.add_argument(
        "--database-url",
        default=os.environ.get("DATABASE_URL", ""),
        help="Postgres URL (env DATABASE_URL)",
    )
    return p


def _consumer_config(args: argparse.Namespace) -> dict:
    return {
        "bootstrap.servers": args.kafka_bootstrap_servers,
        "group.id": args.kafka_consumer_group,
        "enable.auto.commit": False,
        "auto.offset.reset": "earliest",
    }


async def _async_main(args: argparse.Namespace) -> None:
    if not args.database_url:
        raise SystemExit("DATABASE_URL is required (or pass --database-url)")

    pool = await create_pool(args.database_url)
    consumer = Consumer(_consumer_config(args))
    try:
        consumer.subscribe([args.kafka_topic])
    except KafkaException:
        await pool.close()
        raise

    loop = asyncio.get_running_loop()
    stop = asyncio.Event()

    def request_stop() -> None:
        stop.set()

    try:
        loop.add_signal_handler(signal.SIGINT, request_stop)
        loop.add_signal_handler(signal.SIGTERM, request_stop)
    except NotImplementedError:
        signal.signal(signal.SIGINT, lambda *_: loop.call_soon_threadsafe(request_stop))

    runtime = IngestRuntime(
        loop=loop,
        pool=pool,
        consumer=consumer,
        topic=args.kafka_topic,
    )
    runtime.start()
    log.info(
        "ingest_started topic={} bootstrap={} group={}",
        args.kafka_topic,
        args.kafka_bootstrap_servers,
        args.kafka_consumer_group,
    )

    await stop.wait()
    log.info("ingest_shutting_down")
    runtime.stop()
    runtime.join(timeout=120.0)

    await pool.close()


def main() -> None:
    configure_logging(level=os.environ.get("LOG_LEVEL", "INFO"))
    args = _build_arg_parser().parse_args()
    try:
        asyncio.run(_async_main(args))
    except KeyboardInterrupt:
        sys.exit(130)


if __name__ == "__main__":
    main()
