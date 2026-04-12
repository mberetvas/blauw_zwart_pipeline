"""006: merged --max-duration uses fixed t0, not first-emitted timestamp."""

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
        amount=12.0,
        timestamp=ts,
        shop="jan_breydel_fan_shop",
    )


def test_max_duration_uses_t0_anchor_not_first_emitted() -> None:
    """t0 before first line: duration window ends earlier than legacy first-emitted anchor."""
    t0 = datetime(2020, 1, 1, 17, 55, 0, tzinfo=timezone.utc)
    merged = iter(
        [
            _r("2020-01-01T18:00:00Z"),
            _r("2020-01-01T18:01:00Z"),
            _r("2020-01-01T18:05:00Z"),
        ]
    )
    buf = StringIO()
    n = write_merged_stream(
        merged,
        buf,
        max_duration_seconds=400.0,
        t0_anchor=t0,
    )
    assert n == 2

    merged2 = iter(
        [
            _r("2020-01-01T18:00:00Z"),
            _r("2020-01-01T18:01:00Z"),
            _r("2020-01-01T18:05:00Z"),
        ]
    )
    buf2 = StringIO()
    n2 = write_merged_stream(merged2, buf2, max_duration_seconds=400.0, t0_anchor=None)
    assert n2 == 3


def test_max_duration_t0_anchor_none_matches_first_emitted_behavior() -> None:
    merged = iter([_r("2020-01-01T12:00:00Z"), _r("2020-01-01T12:00:30Z")])
    buf = StringIO()
    n = write_merged_stream(merged, buf, max_duration_seconds=45.0, t0_anchor=None)
    assert n == 2
