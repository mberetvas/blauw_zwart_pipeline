"""Retail v3 stream output: byte identity and monotonic timestamps."""

from __future__ import annotations

import json
import random

from fan_events.generation.v3_retail import retail_stream_ndjson


def test_stream_byte_identical_twice() -> None:
    rng1 = random.Random(99)
    rng2 = random.Random(99)
    a = retail_stream_ndjson(rng1, max_events=40)
    b = retail_stream_ndjson(rng2, max_events=40)
    assert a == b


def test_stream_timestamps_non_decreasing() -> None:
    rng = random.Random(3)
    text = retail_stream_ndjson(rng, max_events=100)
    lines = [json.loads(x) for x in text.strip().split("\n")]
    ts = [x["timestamp"] for x in lines]
    assert ts == sorted(ts)


def test_stream_zero_events_empty() -> None:
    rng = random.Random(1)
    assert retail_stream_ndjson(rng, max_events=0) == ""
