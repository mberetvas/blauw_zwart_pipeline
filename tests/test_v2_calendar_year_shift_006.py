"""006: calendar-year shift on naive local kickoff (Feb 29 clamp)."""

from __future__ import annotations

from datetime import datetime

import pytest

from fan_events.generation.v2_calendar import (
    add_calendar_years_to_naive_local,
    build_match_context,
    shift_match_context_calendar_years,
)


def test_add_calendar_years_feb29_to_non_leap_clamps() -> None:
    naive = datetime(2024, 2, 29, 18, 30, 0)
    out = add_calendar_years_to_naive_local(naive, 1)
    assert out == datetime(2025, 2, 28, 18, 30, 0)


def test_add_calendar_years_feb29_stays_on_leap_year() -> None:
    naive = datetime(2024, 2, 29, 12, 0, 0)
    out = add_calendar_years_to_naive_local(naive, 4)
    assert out == datetime(2028, 2, 29, 12, 0, 0)


def test_shift_match_context_calendar_years_rebuilds_utc() -> None:
    row = {
        "match_id": "leap-home",
        "kickoff_local": "2024-02-29T20:00:00",
        "timezone": "Europe/Brussels",
        "attendance": 1000,
        "home_away": "home",
        "venue_label": "Jan Breydel Stadium",
    }
    ctx0 = build_match_context(row)
    ctx1 = shift_match_context_calendar_years(ctx0, 1)
    assert "2025-02-28" in ctx1.row["kickoff_local"]
    assert ctx1.row["match_id"] == "leap-home:c1"
    assert ctx1.kickoff_utc > ctx0.kickoff_utc


def test_shift_match_context_calendar_years_rejects_cycle_zero() -> None:
    row = {
        "match_id": "x",
        "kickoff_local": "2025-07-01T18:00:00",
        "timezone": "Europe/Brussels",
        "attendance": 5000,
        "home_away": "home",
        "venue_label": "Jan Breydel Stadium",
    }
    ctx = build_match_context(row)
    with pytest.raises(ValueError, match="cycle"):
        shift_match_context_calendar_years(ctx, 0)
