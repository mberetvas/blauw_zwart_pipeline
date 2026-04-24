"""Total merge order for unified NDJSON stream (orchestrated-stream contract K1–K3)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fan_events.io.ndjson_io import dumps_canonical


def parse_timestamp_utc_z(ts: str) -> datetime:
    """Parse NDJSON ``timestamp`` field (UTC ending with ``Z``)."""
    if not isinstance(ts, str) or not ts.endswith("Z"):
        raise ValueError("timestamp must be a string ending with Z")
    return datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(timezone.utc)


def merge_key_tuple(record: dict[str, Any]) -> tuple[datetime, str, bytes]:
    """
    Sort key for ``heapq.merge`` / ordering: (K1 UTC instant, K2 ``event``, K3 UTF-8 line bytes).

    Preconditions: ``record`` is a valid v2 or v3 event dict with ``timestamp`` and ``event``.
    """
    ts = parse_timestamp_utc_z(str(record["timestamp"]))
    ev = str(record["event"])
    line = dumps_canonical(record).encode("utf-8")
    return (ts, ev, line)
