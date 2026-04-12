"""006: first-triggered stop when both --max-events and --max-duration bind."""

from __future__ import annotations

from datetime import datetime, timezone
from io import StringIO

from fan_events.data import ITEMS
from fan_events.orchestrator import write_merged_stream
from fan_events.v3_retail import make_retail_purchase


def _r(ts: str) -> dict:
    return make_retail_purchase(
        fan_id="fan_00001",
        item=ITEMS[0],
        amount=10.0,
        timestamp=ts,
        shop="webshop",
    )


def test_max_events_wins_when_duration_would_allow_more() -> None:
    t0 = datetime(2020, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    merged = iter(
        [
            _r("2020-01-01T00:00:10Z"),
            _r("2020-01-01T00:00:20Z"),
            _r("2020-01-01T00:00:30Z"),
        ]
    )
    buf = StringIO()
    n = write_merged_stream(
        merged,
        buf,
        max_events=2,
        max_duration_seconds=1_000_000.0,
        t0_anchor=t0,
    )
    assert n == 2


def test_max_duration_wins_when_events_would_allow_more() -> None:
    t0 = datetime(2020, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    merged = iter(
        [
            _r("2020-01-01T00:00:10Z"),
            _r("2020-01-01T00:00:20Z"),
            _r("2020-01-01T01:00:00Z"),
        ]
    )
    buf = StringIO()
    n = write_merged_stream(
        merged,
        buf,
        max_events=100,
        max_duration_seconds=100.0,
        t0_anchor=t0,
    )
    assert n == 2
