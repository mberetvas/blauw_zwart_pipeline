#!/usr/bin/env python3
"""Consume messages from the ``fan_events`` Kafka topic and print them to stdout.

This is a local test harness for verifying end-to-end flow:

    producer (fan_events stream --kafka-topic fan_events) → Kafka broker → this consumer

Each consumed message is written as one UTF-8 line to **stdout** (NDJSON), so you can
pipe into ``jq``, ``grep``, ``wc -l``, etc.  Connection info and errors go to **stderr**.

Quick-start
-----------
1. Start the broker::

       docker compose up -d          # or: just kafka-up

2. Create the topic (first time only)::

       just kafka-create-topic        # creates 'fan_events' with 3 partitions

3. In terminal A – produce messages::

       just stream-kafka topic=fan_events

4. In terminal B – consume & verify::

       uv run python scripts/kafka_consume_fan_events.py

   Or with CLI overrides::

       uv run python scripts/kafka_consume_fan_events.py --topic fan_events --offset earliest

Usage
-----
::

    uv run python scripts/kafka_consume_fan_events.py [OPTIONS]

    --bootstrap   Bootstrap servers     (default: localhost:9092)
    --topic       Kafka topic           (default: fan_events)
    --group       Consumer group id     (default: fan-events-test-consumer)
    --offset      auto.offset.reset     (default: earliest)
                  'earliest' — replay all unconsumed messages (best for first-time verification)
                  'latest'   — only new messages after subscribing (lower noise on busy topics)
"""

from __future__ import annotations

import argparse
import sys


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Consume from a Kafka topic and print each message to stdout.",
    )
    p.add_argument(
        "--bootstrap",
        default="localhost:9092",
        help="Kafka bootstrap servers (default: localhost:9092)",
    )
    p.add_argument(
        "--topic",
        default="fan_events",
        help="Topic to consume from (default: fan_events)",
    )
    # Change the consumer group to isolate different test sessions or share offsets
    # across multiple runs.  Each unique group tracks its own committed offsets.
    p.add_argument(
        "--group",
        default="fan-events-test-consumer",
        help="Consumer group id (default: fan-events-test-consumer)",
    )
    p.add_argument(
        "--offset",
        choices=["earliest", "latest"],
        default="earliest",
        help=(
            "auto.offset.reset policy (default: earliest). "
            "'earliest' replays from the start; 'latest' sees only new messages."
        ),
    )
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = _parse_args(argv)

    try:
        from confluent_kafka import Consumer, KafkaError, KafkaException
    except ImportError:
        print(
            "confluent-kafka is not installed. Run:  uv sync --extra kafka",
            file=sys.stderr,
        )
        sys.exit(1)

    conf = {
        "bootstrap.servers": args.bootstrap,
        "group.id": args.group,
        "auto.offset.reset": args.offset,
        "enable.auto.commit": True,
    }

    consumer = Consumer(conf)
    try:
        consumer.list_topics(topic=args.topic, timeout=5.0)
    except KafkaException as exc:
        print(
            f"Unable to reach Kafka broker at {args.bootstrap}: {exc}",
            file=sys.stderr,
        )
        consumer.close()
        sys.exit(1)

    consumer.subscribe([args.topic])

    print(
        f"Subscribed to '{args.topic}' (group={args.group}, "
        f"offset={args.offset}, bootstrap={args.bootstrap})",
        file=sys.stderr,
    )
    print("Waiting for messages — press Ctrl+C to stop …", file=sys.stderr)

    try:
        while True:
            msg = consumer.poll(timeout=1.0)
            if msg is None:
                continue
            err = msg.error()
            if err is not None:
                if err.code() == KafkaError._PARTITION_EOF:
                    # End of partition; not a real error — keep polling.
                    continue
                raise KafkaException(err)
            value = msg.value()
            if value is not None:
                sys.stdout.write(value.decode("utf-8", errors="replace"))
                # Ensure each message ends with a newline for clean NDJSON output.
                if not value.endswith(b"\n"):
                    sys.stdout.write("\n")
                sys.stdout.flush()
    except KeyboardInterrupt:
        print("\nInterrupted — closing consumer.", file=sys.stderr)
    finally:
        consumer.close()


if __name__ == "__main__":
    main()
