"""Parse Kafka message payloads into database-ready ingestion rows.

The consumer stores the original JSON payload plus a few extracted fields that
support indexing and debugging. These helpers perform tolerant timestamp
parsing, classify malformed messages, and translate valid NDJSON events into the
row shape expected by :mod:`fan_ingest.db`.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

_SENTINEL_UNKNOWN = "unknown"


class ParseError(ValueError):
    """Raised when a Kafka message cannot be parsed into a row (FR-012)."""


def parse_event_time_utc(value: Any) -> datetime | None:
    """Parse an event timestamp into an aware UTC datetime.

    Args:
        value: Candidate timestamp value from the JSON payload.

    Returns:
        UTC datetime when parsing succeeds, otherwise ``None``.
    """
    if not isinstance(value, str) or not value.strip():
        return None
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def kafka_message_to_row(
    *,
    kafka_topic: str,
    kafka_partition: int,
    kafka_offset: int,
    value: bytes | None,
) -> dict[str, Any]:
    """Convert one Kafka message payload into the DB row shape.

    Args:
        kafka_topic: Topic name used for idempotent uniqueness and logging.
        kafka_partition: Kafka partition number.
        kafka_offset: Kafka offset inside the partition.
        value: Raw message bytes from Kafka.

    Returns:
        Row dictionary ready for :func:`fan_ingest.db.insert_fan_event_row`.

    Raises:
        ParseError: If the body is missing, not UTF-8, invalid JSON, or not a
            JSON object.
    """
    if not value:
        raise ParseError("empty or missing message body")
    try:
        # Decode and parse before we trust any payload fields.
        text = value.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ParseError(f"UTF-8 decode error: {exc}") from exc
    try:
        obj = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ParseError(f"JSON parse error: {exc}") from exc
    if not isinstance(obj, dict):
        raise ParseError(f"expected JSON object, got {type(obj).__name__}")

    # Event type is optional in the schema, so fall back to a sentinel rather
    # than failing ingestion for otherwise valid payloads.
    ev = obj.get("event")
    if isinstance(ev, str) and ev:
        event_type = ev
    else:
        event_type = _SENTINEL_UNKNOWN

    event_time = parse_event_time_utc(obj.get("timestamp"))

    return {
        "kafka_topic": kafka_topic,
        "kafka_partition": kafka_partition,
        "kafka_offset": kafka_offset,
        "event_type": event_type,
        "event_time": event_time,
        "payload_json": obj,
    }
