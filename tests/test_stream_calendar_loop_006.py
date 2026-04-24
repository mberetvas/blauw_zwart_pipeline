"""006: default calendar loop, three event kinds, calendar-only loop."""

from __future__ import annotations

import json
import random
from pathlib import Path

import pytest

from fan_events.cli import SUBCOMMAND_STREAM, parse_args, run_stream
from fan_events.generation.v2_calendar import (
    filter_matches_by_date_range,
    iter_v2_records_merged_sorted,
    load_calendar_json,
    validate_and_parse_matches,
)

_REPO = Path(__file__).resolve().parents[1]
_TINY = _REPO / "tests" / "fixtures" / "calendar_two_tiny.json"


def _ts_monotonic(lines: list[str]) -> None:
    prev = None
    for ln in lines:
        rec = json.loads(ln)
        ts = rec["timestamp"]
        if prev is not None:
            assert ts >= prev
        prev = ts


def test_merged_stream_three_kinds(capsys: pytest.CaptureFixture[str]) -> None:
    """Small calendar: merged stream contains all three event kinds."""
    n = 400
    ns = parse_args(
        [
            SUBCOMMAND_STREAM,
            "--calendar",
            str(_TINY),
            "--seed",
            "11",
            "--max-events",
            str(n),
            "--poisson-rate",
            "0.02",
        ]
    )
    run_stream(ns)
    out = capsys.readouterr().out
    lines = [ln for ln in out.splitlines() if ln.strip()]
    assert len(lines) == n
    kinds = {json.loads(ln)["event"] for ln in lines}
    assert "ticket_scan" in kinds
    assert "merch_purchase" in kinds
    assert "retail_purchase" in kinds
    _ts_monotonic(lines)


def test_stream_loop_emits_second_pass_suffix_calendar_only(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Post-merge line cap is v2+retail; use calendar-only so line count tracks v2 cycles."""
    doc = load_calendar_json(_TINY)
    rows = validate_and_parse_matches(doc)
    contexts = filter_matches_by_date_range(rows, None, None)
    v2_rng = random.Random(f"v2:{11}")
    one_pass = len(list(iter_v2_records_merged_sorted(contexts, v2_rng)))
    n = one_pass + 5
    ns = parse_args(
        [
            SUBCOMMAND_STREAM,
            "--calendar",
            str(_TINY),
            "--no-retail",
            "--seed",
            "11",
            "--max-events",
            str(n),
        ]
    )
    run_stream(ns)
    lines = [ln for ln in capsys.readouterr().out.splitlines() if ln.strip()]
    assert len(lines) == n
    assert any(":c1" in ln for ln in lines)
    _ts_monotonic(lines)


def test_calendar_only_loops_without_no_calendar_loop(capsys: pytest.CaptureFixture[str]) -> None:
    doc = load_calendar_json(_TINY)
    rows = validate_and_parse_matches(doc)
    contexts = filter_matches_by_date_range(rows, None, None)
    v2_rng = random.Random(f"v2:{3}")
    one_pass = len(list(iter_v2_records_merged_sorted(contexts, v2_rng)))
    ns = parse_args(
        [
            SUBCOMMAND_STREAM,
            "--calendar",
            str(_TINY),
            "--no-retail",
            "--seed",
            "3",
            "--max-events",
            str(one_pass + 5),
        ]
    )
    run_stream(ns)
    lines = [ln for ln in capsys.readouterr().out.splitlines() if ln.strip()]
    assert len(lines) == one_pass + 5
    assert any(":c1" in ln for ln in lines)


def test_calendar_only_single_pass_no_loop(capsys: pytest.CaptureFixture[str]) -> None:
    ns = parse_args(
        [
            SUBCOMMAND_STREAM,
            "--calendar",
            str(_TINY),
            "--no-calendar-loop",
            "--no-retail",
            "--seed",
            "3",
            "--max-events",
            "500",
        ]
    )
    run_stream(ns)
    lines = [ln for ln in capsys.readouterr().out.splitlines() if ln.strip()]
    assert not any(":c1" in ln for ln in lines)
