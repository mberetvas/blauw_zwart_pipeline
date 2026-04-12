"""006: match-day retail intensity increases event count over fixed simulated duration."""

from __future__ import annotations

import random
from datetime import timezone
from pathlib import Path

from fan_events.retail_intensity import build_retail_rate_factor_fn
from fan_events.v2_calendar import (
    filter_matches_by_date_range,
    load_calendar_json,
    validate_and_parse_matches,
)
from fan_events.v3_retail import iter_retail_records

_REPO = Path(__file__).resolve().parents[1]
_CAL = _REPO / "match_day.example.json"

# SC-003 floor from retail-intensity-006.md (placeholder ≥ 1.25).
# Empirically ~7–15% over flat Poisson on this window; floor below SC-003 1.25 for stability.
MIN_INTENSITY_BOOST_RATIO = 1.05


def test_retail_count_higher_with_default_match_day_factors() -> None:
    doc = load_calendar_json(_CAL)
    rows = validate_and_parse_matches(doc)
    contexts = filter_matches_by_date_range(rows, None, None)
    fn = build_retail_rate_factor_fn(
        contexts,
        home_match_day_multiplier=2.0,
        home_kickoff_pre_minutes=90,
        home_kickoff_post_minutes=120,
        home_kickoff_extra_multiplier=1.5,
        away_match_day_enable=False,
        away_match_day_multiplier=1.75,
    )
    duration = 86400.0 * 21
    rate = 0.12
    # Start mid-season so F(t) is often > 1 (not Jan 1 default epoch).
    epoch = min(c.kickoff_utc for c in contexts).astimezone(timezone.utc)
    rng_a = random.Random(99)
    rng_b = random.Random(99)
    flat = list(
        iter_retail_records(
            rng_a,
            epoch_utc=epoch,
            max_simulated_duration_seconds=duration,
            poisson_rate=rate,
            skip_default_event_cap=True,
            rate_factor_fn=None,
        )
    )
    boosted = list(
        iter_retail_records(
            rng_b,
            epoch_utc=epoch,
            max_simulated_duration_seconds=duration,
            poisson_rate=rate,
            skip_default_event_cap=True,
            rate_factor_fn=fn,
        )
    )
    assert len(boosted) >= MIN_INTENSITY_BOOST_RATIO * len(flat)
