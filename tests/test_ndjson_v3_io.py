"""NDJSON v3 validation, sort keys, and batch serialization."""

from __future__ import annotations

import json

import pytest

from fan_events.domain import ITEMS, MERCH_PURCHASE, RETAIL_PURCHASE, SHOP_IDS
from fan_events.ndjson_io import (
    dumps_canonical,
    records_to_ndjson_v3,
    sort_key_v3,
    validate_record_v3,
)


def _valid(**kwargs: object) -> dict:
    base: dict = {
        "amount": 12.34,
        "event": RETAIL_PURCHASE,
        "fan_id": "fan_00001",
        "item": ITEMS[0],
        "shop": SHOP_IDS[0],
        "timestamp": "2026-01-01T00:00:01Z",
    }
    base.update(kwargs)
    return base


def test_validate_extra_key() -> None:
    r = _valid()
    r["match_id"] = "x"
    with pytest.raises(ValueError, match="exactly keys"):
        validate_record_v3(r)


def test_validate_wrong_event_value() -> None:
    r = _valid(event=MERCH_PURCHASE)
    with pytest.raises(ValueError, match="event must be"):
        validate_record_v3(r)


def test_validate_wrong_event_key_only() -> None:
    r = _valid()
    r["event"] = "ticket_scan"
    with pytest.raises(ValueError, match="exactly keys|event must be"):
        validate_record_v3(r)


def test_validate_missing_key() -> None:
    r = _valid()
    del r["amount"]
    with pytest.raises(ValueError, match="exactly keys"):
        validate_record_v3(r)


def test_validate_empty_fan_id() -> None:
    r = _valid(fan_id="")
    with pytest.raises(ValueError, match="fan_id"):
        validate_record_v3(r)


def test_validate_item_not_in_catalog() -> None:
    r = _valid(item="Not a real SKU")
    with pytest.raises(ValueError, match="ITEMS"):
        validate_record_v3(r)


def test_validate_bad_shop() -> None:
    r = _valid(shop="airport_kiosk")
    with pytest.raises(ValueError, match="shop"):
        validate_record_v3(r)


def test_validate_amount_non_positive() -> None:
    r = _valid(amount=0)
    with pytest.raises(ValueError, match="> 0"):
        validate_record_v3(r)


def test_validate_timestamp_no_z() -> None:
    r = _valid(timestamp="2026-01-01T00:00:00")
    with pytest.raises(ValueError, match="Z"):
        validate_record_v3(r)


def test_validate_timestamp_garbage() -> None:
    r = _valid(timestamp="not-a-dateZ")
    with pytest.raises(ValueError, match="timestamp"):
        validate_record_v3(r)


def test_sort_tie_breaker_same_timestamp() -> None:
    a = _valid(fan_id="fan_00002", item=ITEMS[1], amount=5.0, timestamp="2026-01-01T00:00:00Z")
    b = _valid(fan_id="fan_00001", item=ITEMS[0], amount=1.0, timestamp="2026-01-01T00:00:00Z")
    assert sort_key_v3(a) > sort_key_v3(b)


def test_records_to_ndjson_v3_sorts_and_trailing_newline() -> None:
    later = _valid(timestamp="2026-01-01T00:00:02Z", fan_id="fan_00001")
    earlier = _valid(timestamp="2026-01-01T00:00:01Z", fan_id="fan_00002")
    text = records_to_ndjson_v3([later, earlier])
    lines = text.strip().split("\n")
    assert len(lines) == 2
    first = json.loads(lines[0])
    assert first["timestamp"] == "2026-01-01T00:00:01Z"
    assert text.endswith("\n")
    assert not text.endswith("\n\n")


def test_records_to_ndjson_v3_empty() -> None:
    assert records_to_ndjson_v3([]) == ""


def test_non_ascii_item_roundtrip() -> None:
    """FR-010 ensure_ascii=False — ITEMS may contain apostrophes etc."""
    item_with_quote = next(x for x in ITEMS if "'" in x)
    r = _valid(item=item_with_quote)
    line = dumps_canonical(r)
    assert "'" in line
    validate_record_v3(r)
