"""Tests for --calendar-loop: shifted contexts, match_id uniqueness, cap, and regression."""

from __future__ import annotations

import random
from datetime import timedelta
from pathlib import Path

import pytest

from fan_events.cli import (
    DEFAULT_CALENDAR_LOOP_SHIFT_DAYS,
    SUBCOMMAND_STREAM,
    parse_args,
    run_stream,
)
from fan_events.merge_keys import parse_timestamp_utc_z
from fan_events.v2_calendar import (
    filter_matches_by_date_range,
    iter_looped_v2_records,
    iter_v2_records_merged_sorted,
    load_calendar_json,
    shift_match_context,
    validate_and_parse_matches,
)

_FIX = Path(__file__).resolve().parent / "fixtures" / "calendar_two_tiny.json"


def _base_contexts():
    doc = load_calendar_json(_FIX)
    rows = validate_and_parse_matches(doc)
    return filter_matches_by_date_range(rows, None, None)


# ---------------------------------------------------------------------------
# shift_match_context: timestamps shift correctly, match_id suffixed
# ---------------------------------------------------------------------------


def test_shift_match_context_timestamps() -> None:
    contexts = _base_contexts()
    ctx = contexts[0]
    shift = timedelta(days=365)
    shifted = shift_match_context(ctx, shift, 1)

    assert shifted.kickoff_utc == ctx.kickoff_utc + shift
    assert shifted.window_start == ctx.window_start + shift
    assert shifted.window_end == ctx.window_end + shift
    assert shifted.effective_cap == ctx.effective_cap


def test_shift_match_context_match_id_suffix() -> None:
    contexts = _base_contexts()
    ctx = contexts[0]
    orig_id = ctx.row["match_id"]
    shifted = shift_match_context(ctx, timedelta(days=7), 3)
    assert shifted.row["match_id"] == f"{orig_id}:c3"


def test_shift_match_context_kickoff_local_updated() -> None:
    """kickoff_local in row dict is shifted consistently with kickoff_utc."""
    from datetime import datetime

    contexts = _base_contexts()
    ctx = contexts[0]
    shift = timedelta(days=14)
    shifted = shift_match_context(ctx, shift, 2)

    orig_naive = datetime.fromisoformat(str(ctx.row["kickoff_local"]))
    new_naive = datetime.fromisoformat(str(shifted.row["kickoff_local"]))
    assert new_naive == orig_naive + shift


# ---------------------------------------------------------------------------
# iter_looped_v2_records: cycle N timestamps are strictly later than cycle 0
# ---------------------------------------------------------------------------


def test_looped_records_cycle1_timestamps_later_than_cycle0() -> None:
    contexts = _base_contexts()
    # Calendar-year shift: cycle 1 kickoffs are ~1 year later than cycle 0.
    rng = random.Random(42)

    cycle0 = list(iter_v2_records_merged_sorted(contexts, rng))
    rng2 = random.Random(42)

    gen = iter_looped_v2_records(contexts, rng2)
    c0_recs = [next(gen) for _ in range(len(cycle0))]

    c1_first = next(gen)
    c0_max_ts = max(parse_timestamp_utc_z(r["timestamp"]) for r in c0_recs)
    c1_first_ts = parse_timestamp_utc_z(c1_first["timestamp"])

    assert c1_first_ts > c0_max_ts


def test_looped_records_monotonically_non_decreasing_per_cycle() -> None:
    """Each cycle's records are non-decreasing by merge_key_tuple."""
    from fan_events.merge_keys import merge_key_tuple

    contexts = _base_contexts()
    rng = random.Random(7)

    gen = iter_looped_v2_records(contexts, rng)

    # Check two complete cycles
    for _cycle in range(2):
        # Count expected records in one cycle
        rng_count = random.Random(99)
        one_cycle = list(iter_v2_records_merged_sorted(_base_contexts(), rng_count))
        n = len(one_cycle)
        recs = [next(gen) for _ in range(n)]
        keys = [merge_key_tuple(r) for r in recs]
        assert keys == sorted(keys), f"Cycle {_cycle} not sorted"


# ---------------------------------------------------------------------------
# match_id uniqueness across cycles
# ---------------------------------------------------------------------------


def test_looped_records_match_ids_unique_across_two_cycles() -> None:
    contexts = _base_contexts()
    rng = random.Random(1)
    gen = iter_looped_v2_records(contexts, rng)

    # Determine cycle size
    rng2 = random.Random(1)
    cycle_size = len(list(iter_v2_records_merged_sorted(contexts, rng2)))

    seen_ids: set[str] = set()
    for _ in range(cycle_size * 2):
        rec = next(gen)
        mid = rec["match_id"]
        # Each (match_id, event, timestamp) combination should be distinct enough;
        # but we specifically check that cycle-0 and cycle-1 match_ids differ.
        seen_ids.add(mid)

    # Cycle 0 has unmodified match_ids; cycle 1 has :c1 suffix
    cycle0_ids = {ctx.row["match_id"] for ctx in contexts}
    cycle1_ids = {f"{ctx.row['match_id']}:c1" for ctx in contexts}
    assert cycle0_ids.issubset(seen_ids)
    assert cycle1_ids.issubset(seen_ids)
    # No overlap between cycle 0 and cycle 1 match_ids
    assert cycle0_ids.isdisjoint(cycle1_ids)


# ---------------------------------------------------------------------------
# --max-events cap is respected with the loop flag
# ---------------------------------------------------------------------------


def test_stream_calendar_loop_max_events_stops_at_cap(
    capsys: pytest.CaptureFixture[str],
) -> None:
    ns = parse_args(
        [
            SUBCOMMAND_STREAM,
            "--calendar",
            str(_FIX),
            "--no-retail",
            "--seed",
            "42",
            "--max-events",
            "5",
        ]
    )
    run_stream(ns)
    captured = capsys.readouterr()
    lines = [ln for ln in captured.out.splitlines() if ln.strip()]
    assert len(lines) == 5


def test_stream_calendar_loop_produces_more_than_one_season(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """With --calendar-loop, events beyond the single-season total are emitted."""
    contexts = _base_contexts()
    rng_size = random.Random(42)
    one_season_count = len(list(iter_v2_records_merged_sorted(contexts, rng_size)))

    # Request slightly more than one season to confirm looping happens
    target = one_season_count + 2
    ns = parse_args(
        [
            SUBCOMMAND_STREAM,
            "--calendar",
            str(_FIX),
            "--no-retail",
            "--seed",
            "42",
            "--max-events",
            str(target),
        ]
    )
    run_stream(ns)
    captured = capsys.readouterr()
    lines = [ln for ln in captured.out.splitlines() if ln.strip()]
    assert len(lines) == target


# ---------------------------------------------------------------------------
# Regression: without --calendar-loop, output is unchanged
# ---------------------------------------------------------------------------


def test_stream_without_loop_unchanged(capsys: pytest.CaptureFixture[str]) -> None:
    """--no-calendar-loop stops after one pass over the calendar."""
    contexts = _base_contexts()
    rng_size = random.Random(42)
    expected_count = len(list(iter_v2_records_merged_sorted(contexts, rng_size)))

    ns = parse_args(
        [
            SUBCOMMAND_STREAM,
            "--calendar",
            str(_FIX),
            "--no-calendar-loop",
            "--no-retail",
            "--seed",
            "42",
        ]
    )
    run_stream(ns)
    captured = capsys.readouterr()
    lines = [ln for ln in captured.out.splitlines() if ln.strip()]
    assert len(lines) == expected_count


# ---------------------------------------------------------------------------
# CLI flag validation
# ---------------------------------------------------------------------------


def test_parse_calendar_loop_requires_calendar() -> None:
    with pytest.raises(SystemExit):
        parse_args([SUBCOMMAND_STREAM, "--calendar-loop", "--seed", "1"])


def test_parse_calendar_loop_defaults() -> None:
    ns = parse_args(
        [
            SUBCOMMAND_STREAM,
            "--calendar",
            str(_FIX),
            "--no-retail",
            "--max-events",
            "1",
            "--calendar-loop",
        ]
    )
    assert ns.calendar_loop is True
    assert ns.calendar_loop_shift is None  # default resolved at runtime


def test_parse_calendar_loop_shift_explicit() -> None:
    ns = parse_args(
        [
            SUBCOMMAND_STREAM,
            "--calendar",
            str(_FIX),
            "--no-retail",
            "--max-events",
            "1",
            "--calendar-loop",
            "--calendar-loop-shift",
            "7",
        ]
    )
    assert ns.calendar_loop_shift == 7.0


def test_parse_calendar_loop_shift_invalid() -> None:
    with pytest.raises(SystemExit):
        parse_args(
            [
                SUBCOMMAND_STREAM,
                "--calendar",
                str(_FIX),
                "--no-retail",
                "--max-events",
                "1",
                "--calendar-loop",
                "--calendar-loop-shift",
                "-1",
            ]
        )


def test_default_loop_shift_days_constant() -> None:
    assert DEFAULT_CALENDAR_LOOP_SHIFT_DAYS == 365
