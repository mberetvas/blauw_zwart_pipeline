"""Retail v3 arrival modes and shop weights."""

from __future__ import annotations

import random

import pytest

from fan_events.core.domain import validate_shop_weights
from fan_events.generation.v3_retail import generate_retail_ndjson, iter_retail_records


def test_invalid_weights_raise() -> None:
    with pytest.raises(ValueError):
        validate_shop_weights((0.2, 0.3))
    with pytest.raises(ValueError):
        validate_shop_weights((-0.1, 0.5, 0.6))


def test_different_weights_different_output_same_seed() -> None:
    w1 = (0.9, 0.05, 0.05)
    w2 = (0.05, 0.05, 0.9)
    rng1 = random.Random(1)
    rng2 = random.Random(1)
    a = generate_retail_ndjson(rng1, max_events=30, shop_weights=w1)
    b = generate_retail_ndjson(rng2, max_events=30, shop_weights=w2)
    assert a != b


def test_fixed_gap_minimum_spacing() -> None:
    rng = random.Random(0)
    recs = list(
        iter_retail_records(
            rng,
            max_events=5,
            arrival_mode="fixed",
            fixed_gap_seconds=120.0,
        )
    )
    assert len(recs) == 5
    # Timestamps strictly increase by 120s from epoch+120
    assert recs[0]["timestamp"] == "2026-01-01T00:02:00Z"
    assert recs[1]["timestamp"] == "2026-01-01T00:04:00Z"


def test_weighted_gap_draws_from_set() -> None:
    rng = random.Random(123)
    recs = list(
        iter_retail_records(
            rng,
            max_events=20,
            arrival_mode="weighted_gap",
            weighted_gaps=(10.0, 100.0),
            weighted_gap_weights=(0.5, 0.5),
        )
    )
    assert len(recs) == 20
