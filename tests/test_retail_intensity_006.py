"""006: piecewise F(t) for match-day retail."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from fan_events.retail_intensity import build_retail_rate_factor_fn
from fan_events.v2_calendar import build_match_context


def _ctx_row(**kwargs: object) -> dict:
    base = {
        "match_id": "m1",
        "kickoff_local": "2026-03-15T18:00:00",
        "timezone": "Europe/Brussels",
        "attendance": 20000,
        "home_away": "home",
        "venue_label": "Jan Breydel Stadium",
    }
    base.update(kwargs)
    return base


def test_inside_home_kickoff_window_is_h_times_e() -> None:
    ctx = build_match_context(_ctx_row())
    fn = build_retail_rate_factor_fn(
        [ctx],
        home_match_day_multiplier=2.0,
        home_kickoff_pre_minutes=90,
        home_kickoff_post_minutes=120,
        home_kickoff_extra_multiplier=1.5,
        away_match_day_enable=False,
        away_match_day_multiplier=1.75,
    )
    # kickoff 2026-03-15 17:00 UTC ≈ 18:00 Brussels — use instant at kickoff
    t = ctx.kickoff_utc
    assert fn(t) == pytest.approx(3.0)


def test_home_match_day_outside_window_is_h() -> None:
    ctx = build_match_context(_ctx_row())
    fn = build_retail_rate_factor_fn(
        [ctx],
        home_match_day_multiplier=2.0,
        home_kickoff_pre_minutes=90,
        home_kickoff_post_minutes=120,
        home_kickoff_extra_multiplier=1.5,
        away_match_day_enable=False,
        away_match_day_multiplier=1.75,
    )
    # Same local day, morning before pre-window
    t = datetime(2026, 3, 15, 6, 0, 0, tzinfo=timezone.utc)
    assert fn(t) == pytest.approx(2.0)


def test_away_only_day_with_enable_uses_a() -> None:
    home = build_match_context(_ctx_row(match_id="h1", kickoff_local="2026-03-20T18:00:00"))
    away = build_match_context(
        _ctx_row(
            match_id="a1",
            kickoff_local="2026-03-22T15:00:00",
            home_away="away",
            attendance=5000,
            venue_label="Away",
        )
    )
    fn = build_retail_rate_factor_fn(
        [home, away],
        home_match_day_multiplier=2.0,
        home_kickoff_pre_minutes=90,
        home_kickoff_post_minutes=120,
        home_kickoff_extra_multiplier=1.5,
        away_match_day_enable=True,
        away_match_day_multiplier=1.75,
    )
    t = datetime(2026, 3, 22, 12, 0, 0, tzinfo=timezone.utc)
    assert fn(t) == pytest.approx(1.75)


def test_away_only_ignored_when_disabled() -> None:
    away = build_match_context(
        _ctx_row(
            match_id="a1",
            kickoff_local="2026-04-10T15:00:00",
            home_away="away",
            attendance=5000,
            venue_label="Away",
        )
    )
    fn = build_retail_rate_factor_fn(
        [away],
        home_match_day_multiplier=2.0,
        home_kickoff_pre_minutes=90,
        home_kickoff_post_minutes=120,
        home_kickoff_extra_multiplier=1.5,
        away_match_day_enable=False,
        away_match_day_multiplier=1.75,
    )
    t = datetime(2026, 4, 10, 12, 0, 0, tzinfo=timezone.utc)
    assert fn(t) == 1.0
