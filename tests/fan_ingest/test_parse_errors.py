"""Parse failures: no row and no DB insert on the skip path."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest

from fan_ingest.records import ParseError, kafka_message_to_row


async def _insert_if_parsed(value: bytes, insert: AsyncMock) -> None:
    try:
        row = kafka_message_to_row(
            kafka_topic="fan_events",
            kafka_partition=0,
            kafka_offset=99,
            value=value,
        )
    except ParseError:
        return
    await insert(row)


def test_skip_path_does_not_call_insert_for_invalid_payload() -> None:
    insert = AsyncMock()
    asyncio.run(_insert_if_parsed(b"{not json", insert))
    insert.assert_not_called()


def test_valid_payload_still_inserts() -> None:
    insert = AsyncMock()
    raw = b'{"event":"merch_purchase","timestamp":"2024-01-01T00:00:00Z"}'
    asyncio.run(_insert_if_parsed(raw, insert))
    insert.assert_awaited_once()


def test_parse_error_is_value_error_subclass() -> None:
    with pytest.raises(ValueError):
        kafka_message_to_row(kafka_topic="t", kafka_partition=0, kafka_offset=0, value=b"")
