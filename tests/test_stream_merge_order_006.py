"""006: merged stream merge_key_tuple non-decreasing for ≥1000 lines (v2-only: second ties)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from fan_events.cli import SUBCOMMAND_STREAM, parse_args, run_stream
from fan_events.io.merge_keys import merge_key_tuple

_REPO = Path(__file__).resolve().parents[1]
_FIX = _REPO / "match_day.example.json"


def test_stdout_merge_order_1000_lines(capsys: pytest.CaptureFixture[str]) -> None:
    # Calendar-only: v2 timestamps are second-resolved but ticket vs merch ordering per match
    # is merge-key-stable; retail can share timestamps across lines and break strict K order.
    ns = parse_args(
        [
            SUBCOMMAND_STREAM,
            "--calendar",
            str(_FIX),
            "--no-retail",
            "--seed",
            "21",
            "--max-events",
            "1200",
        ]
    )
    run_stream(ns)
    lines = [ln for ln in capsys.readouterr().out.splitlines() if ln.strip()]
    assert len(lines) >= 1000
    prev = None
    for ln in lines[:1000]:
        rec = json.loads(ln)
        k = merge_key_tuple(rec)
        if prev is not None:
            assert k >= prev, (prev, k, ln[:80])
        prev = k
