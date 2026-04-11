"""NDJSON → row fields per data-model / ingestion-persistence-v1."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from fan_ingest.records import ParseError, kafka_message_to_row, parse_event_time_utc


def test_parse_event_time_z_suffix() -> None:
    dt = parse_event_time_utc("2024-06-01T14:30:00Z")
    assert dt == datetime(2024, 6, 1, 14, 30, 0, tzinfo=UTC)


def test_parse_event_time_invalid_returns_none() -> None:
    assert parse_event_time_utc("not-a-date") is None
    assert parse_event_time_utc(None) is None


def test_v2_merch_purchase_row_shape() -> None:
    raw = (
        b'{"amount":12.5,"event":"merch_purchase","fan_id":"f1","item":"scarf",'
        b'"match_id":"m99","timestamp":"2024-01-01T12:00:00Z"}'
    )
    row = kafka_message_to_row(
        kafka_topic="fan_events",
        kafka_partition=2,
        kafka_offset=1001,
        value=raw,
    )
    assert row["kafka_topic"] == "fan_events"
    assert row["kafka_partition"] == 2
    assert row["kafka_offset"] == 1001
    assert row["event_type"] == "merch_purchase"
    assert row["event_time"] == datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC)
    assert row["payload_json"]["fan_id"] == "f1"
    assert row["payload_json"]["item"] == "scarf"


def test_v3_retail_purchase_row_shape() -> None:
    raw = (
        b'{"amount":9.99,"event":"retail_purchase","fan_id":"f2","item":"scarf",'
        b'"shop":"SHOP_A","timestamp":"2025-03-15T10:00:00Z"}'
    )
    row = kafka_message_to_row(
        kafka_topic="fan_events",
        kafka_partition=0,
        kafka_offset=7,
        value=raw,
    )
    assert row["event_type"] == "retail_purchase"
    assert row["payload_json"]["shop"] == "SHOP_A"


def test_missing_event_field_uses_unknown_sentinel() -> None:
    raw = b'{"timestamp":"2024-01-01T00:00:00Z","fan_id":"x"}'
    row = kafka_message_to_row(
        kafka_topic="t",
        kafka_partition=1,
        kafka_offset=3,
        value=raw,
    )
    assert row["event_type"] == "unknown"


def test_event_time_null_when_timestamp_missing() -> None:
    raw = b'{"event":"ticket_scan","fan_id":"f","location":"A","match_id":"m","timestamp":""}'
    row = kafka_message_to_row(kafka_topic="t", kafka_partition=0, kafka_offset=0, value=raw)
    assert row["event_time"] is None


@pytest.mark.parametrize(
    "value",
    [b"", b"not-json{", b"[1,2,3]", b'"string"'],
)
def test_parse_failure_raises_parse_error(value: bytes) -> None:
    with pytest.raises(ParseError):
        kafka_message_to_row(kafka_topic="t", kafka_partition=0, kafka_offset=0, value=value)


def test_parse_error_includes_detail_for_json_error() -> None:
    with pytest.raises(ParseError, match="JSON parse error"):
        kafka_message_to_row(
            kafka_topic="t", kafka_partition=0, kafka_offset=0, value=b"{not json"
        )


def test_parse_error_includes_detail_for_non_object() -> None:
    with pytest.raises(ParseError, match="expected JSON object"):
        kafka_message_to_row(
            kafka_topic="t", kafka_partition=0, kafka_offset=0, value=b"[1,2,3]"
        )


def test_parse_error_includes_detail_for_empty_body() -> None:
    with pytest.raises(ParseError, match="empty or missing"):
        kafka_message_to_row(
            kafka_topic="t", kafka_partition=0, kafka_offset=0, value=b""
        )
