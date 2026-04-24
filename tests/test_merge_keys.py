"""Merge key ordering for unified stream (orchestrated-stream contract)."""

from datetime import datetime, timezone

from fan_events.core.domain import MERCH_PURCHASE, RETAIL_PURCHASE, TICKET_SCAN
from fan_events.io.merge_keys import merge_key_tuple, parse_timestamp_utc_z


def test_parse_timestamp_utc_z() -> None:
    dt = parse_timestamp_utc_z("2026-06-01T12:00:00Z")
    assert dt == datetime(2026, 6, 1, 12, 0, 0, tzinfo=timezone.utc)


def test_merge_key_same_timestamp_event_order_merch_before_retail_before_ticket() -> None:
    ts = "2026-01-01T00:00:00Z"
    merch = {
        "amount": 10.0,
        "event": MERCH_PURCHASE,
        "fan_id": "fan_00001",
        "item": "scarf",
        "match_id": "m1",
        "timestamp": ts,
        "location": "Jan Breydel",
    }
    retail = {
        "amount": 5.0,
        "event": RETAIL_PURCHASE,
        "fan_id": "fan_00001",
        "item": "scarf",
        "shop": "jan_breydel_fan_shop",
        "timestamp": ts,
    }
    ticket = {
        "event": TICKET_SCAN,
        "fan_id": "fan_00001",
        "location": "gate_a",
        "match_id": "m1",
        "timestamp": ts,
    }
    keys = [merge_key_tuple(merch), merge_key_tuple(retail), merge_key_tuple(ticket)]
    assert keys == sorted(keys)


def test_merge_key_tie_break_canonical_line() -> None:
    ts = "2026-01-01T00:00:00Z"
    a = {
        "event": TICKET_SCAN,
        "fan_id": "fan_00002",
        "location": "gate_a",
        "match_id": "m1",
        "timestamp": ts,
    }
    b = {
        "event": TICKET_SCAN,
        "fan_id": "fan_00001",
        "location": "gate_a",
        "match_id": "m1",
        "timestamp": ts,
    }
    ka, kb = merge_key_tuple(a), merge_key_tuple(b)
    assert ka[:2] == kb[:2]
    assert (ka < kb) == (ka[2] < kb[2])
