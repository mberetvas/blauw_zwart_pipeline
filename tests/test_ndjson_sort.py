"""Contract ordering for v1 and v2 sort keys."""

from fan_events.core.domain import MERCH_PURCHASE, TICKET_SCAN
from fan_events.io.ndjson_io import sort_key_v1, sort_key_v2


def test_sort_key_v2_orders_match_id_before_location_ties() -> None:
    a = {
        "event": TICKET_SCAN,
        "fan_id": "fan_00001",
        "location": "A",
        "match_id": "m-b",
        "timestamp": "2026-01-01T12:00:00Z",
    }
    b = {
        "event": TICKET_SCAN,
        "fan_id": "fan_00001",
        "location": "B",
        "match_id": "m-a",
        "timestamp": "2026-01-01T12:00:00Z",
    }
    rows = sorted([a, b], key=sort_key_v2)
    assert rows[0]["match_id"] == "m-a"


def test_sort_key_v1_unchanged_semantics() -> None:
    t = {
        "event": TICKET_SCAN,
        "fan_id": "f",
        "location": "L",
        "timestamp": "2026-01-01T12:00:00Z",
    }
    m = {
        "amount": 1.0,
        "event": MERCH_PURCHASE,
        "fan_id": "f",
        "item": "i",
        "timestamp": "2026-01-01T12:00:00Z",
    }
    assert sort_key_v1(t)[1] < sort_key_v1(m)[1]
