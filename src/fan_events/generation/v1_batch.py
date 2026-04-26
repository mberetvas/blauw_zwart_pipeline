"""Generate legacy rolling-window synthetic fan events.

The v1 generator produces ticket-scan and merch-purchase records inside a
sliding window ending at ``now_utc``. It exists primarily for backward
compatibility and therefore preserves the historical RNG draw order used by the
 earliest fixtures and golden files.
"""

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
    """Build one v1 ticket-scan record.

    Args:
        fan_id: Synthetic fan identifier.
        location: Ticket-scan location label.
        timestamp: UTC timestamp string in ``YYYY-MM-DDTHH:MM:SSZ`` format.

    Returns:
        Dictionary in the closed v1 ticket-scan schema.
    """
    return {
        "event": TICKET_SCAN,
        "fan_id": fan_id,
        "location": location,
        "timestamp": timestamp,
    }


def make_merch_purchase(fan_id: str, item: str, amount: float, timestamp: str) -> dict[str, Any]:
    """Build one v1 merch-purchase record.

    Args:
        fan_id: Synthetic purchaser identifier.
        item: Merch catalog item name.
        amount: Rounded purchase amount in EUR.
        timestamp: UTC timestamp string in ``YYYY-MM-DDTHH:MM:SSZ`` format.

    Returns:
        Dictionary in the closed v1 merch-purchase schema.
    """
    return {
        "amount": amount,
        "event": MERCH_PURCHASE,
        "fan_id": fan_id,
        "item": item,
        "timestamp": timestamp,
    }


def _utc_ts_string(rng: random.Random, start_ts: int, end_ts: int) -> str:
    """Draw one UTC timestamp string uniformly from an inclusive epoch range."""
    sec = rng.randint(start_ts, end_ts)
    dt = datetime.fromtimestamp(sec, tz=timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _fan_id(rng: random.Random, pool: int) -> str:
    """Draw one synthetic fan ID from the inclusive ``1..pool`` range."""
    return f"fan_{rng.randint(1, pool):05d}"


def generate_batch(
    rng: random.Random,
    *,
    count: int,
    days: int,
    events_mode: str,
    now_utc: datetime,
) -> list[dict[str, Any]]:
    """Generate a v1 rolling-window batch of synthetic fan events.

    Args:
        rng: Random generator controlling reproducible output.
        count: Total number of events to emit.
        days: Number of days included in the trailing simulation window.
        events_mode: ``ticket_scan``, ``merch_purchase``, or ``both``.
        now_utc: Inclusive upper bound for generated timestamps.

    Returns:
        List of v1 event dictionaries in legacy generation order.

    Note:
        When ``events_mode`` is ``both``, the generator emits one ticket scan and
        one merch purchase before filling the remainder with a 50/50 split so the
        output always contains both event types.
    """
    if count == 0:
        return []

    # Derive one inclusive UTC window used by all timestamp draws in this batch.
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

    # Fast paths keep single-event-type modes simple and avoid the mixed-mode
    # bootstrap logic below.
    if events_mode == TICKET_SCAN:
        for _ in range(count):
            records.append(one_ticket())
        return records

    if events_mode == MERCH_PURCHASE:
        for _ in range(count):
            records.append(one_merch())
        return records

    # Mixed mode guarantees at least one record of each type before random fill.
    records.append(one_ticket())
    records.append(one_merch())
    for _ in range(count - 2):
        if rng.random() < 0.5:
            records.append(one_ticket())
        else:
            records.append(one_merch())
    return records
