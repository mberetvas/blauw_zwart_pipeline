"""v2 sorted iterators for unified stream merge."""

import random
from datetime import date
from pathlib import Path

from fan_events.merge_keys import merge_key_tuple
from fan_events.v2_calendar import (
    filter_matches_by_date_range,
    generate_v2_records,
    iter_v2_records_merged_sorted,
    load_calendar_json,
    validate_and_parse_matches,
)

_FIX = Path(__file__).resolve().parent / "fixtures" / "calendar_two_tiny.json"
_THREE = (
    Path(__file__).resolve().parents[1]
    / "specs"
    / "002-match-calendar-events"
    / "fixtures"
    / "calendar_three_matches.json"
)


def test_generate_v2_records_unchanged_vs_refactor() -> None:
    doc = load_calendar_json(_FIX)
    rows = validate_and_parse_matches(doc)
    ctx = filter_matches_by_date_range(rows, date(2026, 1, 1), date(2027, 12, 31))
    rng = random.Random(42)
    a = generate_v2_records(ctx, rng)
    rng2 = random.Random(42)
    b = generate_v2_records(ctx, rng2)
    assert a == b


def test_iter_sorted_non_decreasing_merge_key() -> None:
    doc = load_calendar_json(_FIX)
    rows = validate_and_parse_matches(doc)
    ctx = filter_matches_by_date_range(rows, date(2026, 1, 1), date(2027, 12, 31))
    rng = random.Random(7)
    merged = list(iter_v2_records_merged_sorted(ctx, rng))
    keys = [merge_key_tuple(r) for r in merged]
    assert keys == sorted(keys)


def test_multi_match_global_order() -> None:
    doc = load_calendar_json(_THREE)
    rows = validate_and_parse_matches(doc)
    ctx = filter_matches_by_date_range(rows, None, None)
    rng = random.Random(123)
    merged = list(iter_v2_records_merged_sorted(ctx, rng))
    keys = [merge_key_tuple(r) for r in merged]
    assert keys == sorted(keys)
    assert len(merged) > 0
