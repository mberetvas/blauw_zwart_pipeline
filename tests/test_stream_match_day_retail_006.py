"""006: match-day retail intensity increases event count over fixed simulated duration."""

from __future__ import annotations

import random
from datetime import datetime, timezone
from pathlib import Path

from fan_events.generation.retail_intensity import build_retail_rate_factor_fn
from fan_events.generation.v2_calendar import (
    filter_matches_by_date_range,
    load_calendar_json,
    validate_and_parse_matches,
)
from fan_events.generation.v3_retail import iter_retail_records

_REPO = Path(__file__).resolve().parents[1]
_CAL = _REPO / "match_day.example.json"

# Acceptance-test threshold aligned with SC-003 floor from retail-intensity-006.md (≥ 1.25).
# Window is 7 days starting Sep 21 UTC, which contains two dense home match days (Sep 21 + Sep 24)
# giving a theoretical ~1.33× boost and a stable empirical ratio well above the 1.25 floor.
MIN_INTENSITY_BOOST_RATIO = 1.25


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
    # 7-day window covering two consecutive home match days (Sep 21 + Sep 24) for a dense
    # F(t) > 1 signal, ensuring the boost ratio reliably meets the SC-003 ≥ 1.25 acceptance floor.
    duration = 86400.0 * 7
    rate = 0.12
    epoch = datetime(2025, 9, 21, 0, 0, 0, tzinfo=timezone.utc)
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
