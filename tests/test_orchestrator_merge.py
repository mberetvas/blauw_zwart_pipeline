"""Orchestrator: merge v2 + v3, NDJSON lines, post-merge caps, pacing."""

import io
import random
from datetime import date
from itertools import pairwise
from pathlib import Path
from unittest.mock import patch

from fan_events.merge_keys import merge_key_tuple
from fan_events.orchestrator import (
    default_unified_fan_pool_max,
    iter_merged_records,
    record_to_ndjson_line,
    write_merged_stream,
)
from fan_events.v2_calendar import (
    filter_matches_by_date_range,
    iter_v2_records_merged_sorted,
    load_calendar_json,
    validate_and_parse_matches,
)
from fan_events.v3_retail import iter_retail_records

_FIX = Path(__file__).resolve().parent / "fixtures" / "calendar_two_tiny.json"


def test_iter_merged_records_non_decreasing_keys() -> None:
    doc = load_calendar_json(_FIX)
    rows = validate_and_parse_matches(doc)
    ctx = filter_matches_by_date_range(rows, date(2026, 1, 1), date(2027, 12, 31))
    rng = random.Random(99)
    v2 = iter_v2_records_merged_sorted(
        ctx,
        rng,
        fan_pool_max=default_unified_fan_pool_max(ctx),
    )
    rng2 = random.Random(99)
    retail = iter_retail_records(
        rng2,
        skip_default_event_cap=True,
        max_events=80,
        fan_pool=400,
    )
    merged = list(iter_merged_records(retail, v2))
    keys = [merge_key_tuple(r) for r in merged]
    assert keys == sorted(keys)


def test_iter_merged_records_empty_retail() -> None:
    doc = load_calendar_json(_FIX)
    rows = validate_and_parse_matches(doc)
    ctx = filter_matches_by_date_range(rows, date(2026, 1, 1), date(2027, 12, 31))
    rng = random.Random(3)
    v2 = iter_v2_records_merged_sorted(ctx, rng)
    merged = list(iter_merged_records(iter(()), v2))
    assert merged
    assert all(merge_key_tuple(a) <= merge_key_tuple(b) for a, b in pairwise(merged))


def test_iter_merged_records_empty_v2() -> None:
    rng = random.Random(1)
    retail = iter_retail_records(rng, skip_default_event_cap=True, max_events=5)
    merged = list(iter_merged_records(retail, iter(())))
    assert len(merged) == 5


def test_record_to_ndjson_line_v2_vs_v3() -> None:
    rng = random.Random(0)
    r3 = next(iter(iter_retail_records(rng, max_events=1)))
    line3 = record_to_ndjson_line(r3)
    assert '"event":"retail_purchase"' in line3
    assert line3.endswith("\n")


def test_write_merged_stream_max_events() -> None:
    rng = random.Random(2)
    retail = iter_retail_records(rng, skip_default_event_cap=True, max_events=100)
    buf = io.StringIO()
    n = write_merged_stream(iter_merged_records(retail, iter(())), buf, max_events=4)
    assert n == 4
    lines = buf.getvalue().splitlines()
    assert len(lines) == 4


def test_write_merged_stream_max_duration_zero_emits_first_line_only() -> None:
    """Duration window 0s: second event has strictly greater ts than anchor → stop before emit."""
    rng = random.Random(4)
    retail = iter_retail_records(rng, skip_default_event_cap=True, max_events=500)
    buf = io.StringIO()
    n = write_merged_stream(
        iter_merged_records(retail, iter(())),
        buf,
        max_duration_seconds=0.0,
    )
    assert n == 1


def test_write_merged_stream_pacing_respects_max_events() -> None:
    rng = random.Random(5)
    retail = iter_retail_records(rng, skip_default_event_cap=True, max_events=20)
    merged = iter_merged_records(retail, iter(()))
    pacing = random.Random("pacing:5")
    buf = io.StringIO()
    sleeps: list[float] = []

    def _track_sleep(sec: float) -> None:
        sleeps.append(sec)

    with patch("fan_events.orchestrator.time.sleep", side_effect=_track_sleep):
        n = write_merged_stream(
            merged,
            buf,
            max_events=3,
            pacing_rng=pacing,
            emit_wall_clock_min=0.0,
            emit_wall_clock_max=0.0,
        )
    assert n == 3
    assert len(sleeps) == 2


def test_golden_retail_only_stream_lines_match_seed() -> None:
    """Byte-identical NDJSON lines for fixed seed + caps (retail-only branch)."""
    rng = random.Random(12345)
    retail = iter_retail_records(rng, skip_default_event_cap=True, max_events=7)
    merged = iter_merged_records(retail, iter(()))
    buf = io.StringIO()
    write_merged_stream(merged, buf, max_events=7)
    first = buf.getvalue()

    rng = random.Random(12345)
    retail = iter_retail_records(rng, skip_default_event_cap=True, max_events=7)
    merged = iter_merged_records(retail, iter(()))
    buf2 = io.StringIO()
    write_merged_stream(merged, buf2, max_events=7)
    assert first == buf2.getvalue()
    assert first.count("\n") == 7
