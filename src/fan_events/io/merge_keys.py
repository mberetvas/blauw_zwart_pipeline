"""Define the total ordering used to merge heterogeneous NDJSON streams.

The unified stream contract sorts records by UTC timestamp, then event name,
then canonical JSON bytes. These helpers are shared by the v2/v3 orchestrator
and any tests that need to assert stable cross-stream ordering.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fan_events.io.ndjson_io import dumps_canonical


def parse_timestamp_utc_z(ts: str) -> datetime:
    """Parse a canonical NDJSON timestamp into a UTC datetime.

    Args:
        ts: Timestamp string expected to end with ``Z``.

    Returns:
        Timezone-aware UTC datetime.

    Raises:
        ValueError: If ``ts`` is not a string ending with ``Z`` or cannot be
            parsed as ISO-8601.
    """
    if not isinstance(ts, str) or not ts.endswith("Z"):
        raise ValueError("timestamp must be a string ending with Z")
    return datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(timezone.utc)


def merge_key_tuple(record: dict[str, Any]) -> tuple[datetime, str, bytes]:
    """Return the total-order key for one v2 or v3 event record.

    Args:
        record: Valid v2 or v3 event dictionary containing ``timestamp`` and
            ``event`` fields.

    Returns:
        Three-tuple ``(timestamp_utc, event_name, canonical_json_bytes)``.

    Note:
        The final byte-string component ensures deterministic ordering even when
        timestamp and event type are identical.
    """
    ts = parse_timestamp_utc_z(str(record["timestamp"]))
    ev = str(record["event"])
    line = dumps_canonical(record).encode("utf-8")
    return (ts, ev, line)
