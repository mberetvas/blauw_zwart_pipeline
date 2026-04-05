"""Optional large-batch check (SC-003); run with ``pytest -m slow``."""

from __future__ import annotations

import json
import random

import pytest

from fan_events.ndjson_io import records_to_ndjson_v3, sort_key_v3, validate_record_v3
from fan_events.v3_retail import generate_retail_batch


@pytest.mark.slow
def test_large_batch_sorted_and_valid() -> None:
    rng = random.Random(20260405)
    records = generate_retail_batch(rng, max_events=50_000)
    text = records_to_ndjson_v3(records)
    lines = text.strip().split("\n")
    assert len(lines) == 50_000
    parsed = [json.loads(x) for x in lines]
    keys = [sort_key_v3(r) for r in parsed]
    assert keys == sorted(keys)
    for rec in parsed:
        validate_record_v3(rec)
