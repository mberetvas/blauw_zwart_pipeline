"""NDJSON message bytes → row dict for fan_events_ingested (v1)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

_SENTINEL_UNKNOWN = "unknown"


class ParseError(ValueError):
    """Raised when a Kafka message cannot be parsed into a row (FR-012)."""


def parse_event_time_utc(value: Any) -> datetime | None:
    """Parse synthetic `timestamp` field (ISO-8601, optional Z) to aware UTC; else None."""
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
    """Return a row dict for insert, or raise :class:`ParseError` (FR-012).

    Raises on: missing/empty body, UTF-8 decode error, JSON parse error, or non-object JSON.
    On success: event_type from top-level string ``event``, else ``unknown``; event_time from
    ``timestamp`` when parseable, else NULL in DB.
    """
    if not value:
        raise ParseError("empty or missing message body")
    try:
        text = value.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ParseError(f"UTF-8 decode error: {exc}") from exc
    try:
        obj = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ParseError(f"JSON parse error: {exc}") from exc
    if not isinstance(obj, dict):
        raise ParseError(f"expected JSON object, got {type(obj).__name__}")

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
