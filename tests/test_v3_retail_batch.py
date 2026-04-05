"""Retail v3 batch generation: reproducibility and global sort."""

from __future__ import annotations

import json
import random

from fan_events.ndjson_io import records_to_ndjson_v3, sort_key_v3, validate_record_v3
from fan_events.v3_retail import (
    generate_retail_batch,
    generate_retail_ndjson,
    iter_retail_records,
)


def test_batch_byte_identical_twice() -> None:
    rng1 = random.Random(42)
    rng2 = random.Random(42)
    a = generate_retail_ndjson(rng1, max_events=50)
    b = generate_retail_ndjson(rng2, max_events=50)
    assert a == b
    assert a.endswith("\n")


def test_batch_matches_generate_retail_batch_compose() -> None:
    """CLI file mode uses generate_retail_batch + records_to_ndjson_v3 — same as helper."""
    a = generate_retail_ndjson(random.Random(99), max_events=20)
    b = records_to_ndjson_v3(generate_retail_batch(random.Random(99), max_events=20))
    assert a == b


def test_batch_empty_max_events_zero() -> None:
    rng = random.Random(1)
    assert generate_retail_ndjson(rng, max_events=0) == ""


def test_batch_lines_sorted_globally() -> None:
    rng = random.Random(7)
    text = generate_retail_ndjson(rng, max_events=30)
    lines = [json.loads(x) for x in text.strip().split("\n")]
    keys = [sort_key_v3(r) for r in lines]
    assert keys == sorted(keys)
    for line in lines:
        validate_record_v3(line)


def test_skip_default_event_cap_respects_max_duration() -> None:
    rng = random.Random(0)
    recs = list(
        iter_retail_records(
            rng,
            skip_default_event_cap=True,
            max_simulated_duration_seconds=500.0,
            arrival_mode="fixed",
            fixed_gap_seconds=1.0,
            max_events=None,
        )
    )
    assert len(recs) > 200
