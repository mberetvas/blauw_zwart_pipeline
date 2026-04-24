"""Rolling-window (v1) synthetic fan event batch generation."""

from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone
from typing import Any

from fan_events.core.data import (
    ITEMS,
    LOCATIONS,
    SYNTHETIC_LINE_AMOUNT_RANDINT_HIGH,
    SYNTHETIC_LINE_AMOUNT_RANDINT_LOW,
    line_amount_eur_from_jitter_int,
)
from fan_events.core.domain import MERCH_PURCHASE, TICKET_SCAN

# When --seed is set, wall-clock "now" would change between runs and break byte identity (FR-005).
FIXED_NOW_UTC = datetime(2026, 4, 1, 15, 0, 0, tzinfo=timezone.utc)


def make_ticket_scan(fan_id: str, location: str, timestamp: str) -> dict[str, Any]:
    return {
        "event": TICKET_SCAN,
        "fan_id": fan_id,
        "location": location,
        "timestamp": timestamp,
    }


def make_merch_purchase(
    fan_id: str, item: str, amount: float, timestamp: str
) -> dict[str, Any]:
    return {
        "amount": amount,
        "event": MERCH_PURCHASE,
        "fan_id": fan_id,
        "item": item,
        "timestamp": timestamp,
    }


def _utc_ts_string(rng: random.Random, start_ts: int, end_ts: int) -> str:
    sec = rng.randint(start_ts, end_ts)
    dt = datetime.fromtimestamp(sec, tz=timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _fan_id(rng: random.Random, pool: int) -> str:
    return f"fan_{rng.randint(1, pool):05d}"


def generate_batch(
    rng: random.Random,
    *,
    count: int,
    days: int,
    events_mode: str,
    now_utc: datetime,
) -> list[dict[str, Any]]:
    if count == 0:
        return []

    window_start = now_utc - timedelta(days=days)
    start_ts = int(window_start.timestamp())
    end_ts = int(now_utc.timestamp())
    if start_ts > end_ts:
        start_ts = end_ts

    fan_pool = min(500, max(count * 2, 2))

    def one_ticket() -> dict[str, Any]:
        return make_ticket_scan(
            _fan_id(rng, fan_pool),
            rng.choice(LOCATIONS),
            _utc_ts_string(rng, start_ts, end_ts),
        )

    def one_merch() -> dict[str, Any]:
        # RNG order matches pre-refactor v1: jitter draw, then fan_id, item, timestamp.
        u = rng.randint(SYNTHETIC_LINE_AMOUNT_RANDINT_LOW, SYNTHETIC_LINE_AMOUNT_RANDINT_HIGH)
        fan = _fan_id(rng, fan_pool)
        item = rng.choice(ITEMS)
        amount = line_amount_eur_from_jitter_int(item, u)
        return make_merch_purchase(
            fan,
            item,
            amount,
            _utc_ts_string(rng, start_ts, end_ts),
        )

    records: list[dict[str, Any]] = []

    if events_mode == TICKET_SCAN:
        for _ in range(count):
            records.append(one_ticket())
        return records

    if events_mode == MERCH_PURCHASE:
        for _ in range(count):
            records.append(one_merch())
        return records

    records.append(one_ticket())
    records.append(one_merch())
    for _ in range(count - 2):
        if rng.random() < 0.5:
            records.append(one_ticket())
        else:
            records.append(one_merch())
    return records
