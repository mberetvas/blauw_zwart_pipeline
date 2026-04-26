"""Generate synthetic retail purchases independent of the match calendar.

This module powers the NDJSON v3 retail stream used both standalone and inside
the merged stream orchestrator. It is intentionally deterministic: given the
same RNG seed and parameters, each event consumes random draws in the documented
order so tests and golden fixtures remain stable.

RNG draw order per emitted event is: inter-arrival gap, then shop, item,
amount jitter, and finally ``fan_id`` selection.
"""

from __future__ import annotations

import random
from collections.abc import Callable, Iterator, Sequence
from datetime import datetime, timedelta, timezone
from typing import Any

from fan_events.core.data import ITEMS, SHOP_IDS, synthetic_line_amount_eur
from fan_events.core.domain import (
    DEFAULT_RETAIL_SIM_EPOCH_UTC,
    DEFAULT_SHOP_WEIGHTS,
    RETAIL_PURCHASE,
    validate_shop_weights,
)
from fan_events.io.ndjson_io import format_line_v3, records_to_ndjson_v3


def make_retail_purchase(
    *,
    fan_id: str,
    item: str,
    amount: float,
    timestamp: str,
    shop: str,
) -> dict[str, Any]:
    """Build one retail purchase record in NDJSON v3 shape.

    Args:
        fan_id: Synthetic purchaser identifier.
        item: Retail catalog item name.
        amount: Rounded purchase amount in EUR.
        timestamp: UTC timestamp string in ``YYYY-MM-DDTHH:MM:SSZ`` format.
        shop: Stable shop identifier from :data:`fan_events.core.data.SHOP_IDS`.

    Returns:
        Dictionary ready for v3 validation or serialization.
    """
    return {
        "amount": amount,
        "event": RETAIL_PURCHASE,
        "fan_id": fan_id,
        "item": item,
        "shop": shop,
        "timestamp": timestamp,
    }


def _dt_to_utc_z(dt: datetime) -> str:
    """Format a datetime as the canonical UTC timestamp string."""
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _fan_id(rng: random.Random, pool: int) -> str:
    """Draw one synthetic fan ID from the configured inclusive pool."""
    return f"fan_{rng.randint(1, pool):05d}"


def _next_interarrival_seconds(
    rng: random.Random,
    *,
    arrival_mode: str,
    poisson_rate: float,
    fixed_gap_seconds: float,
    weighted_gaps: Sequence[float] | None,
    weighted_gap_weights: Sequence[float] | None,
) -> float:
    """Return the next inter-arrival gap for non-inline arrival strategies.

    Args:
        rng: Random generator used for deterministic draw order.
        arrival_mode: Gap strategy name.
        poisson_rate: Events-per-second rate for Poisson sampling.
        fixed_gap_seconds: Constant gap used by ``fixed`` mode.
        weighted_gaps: Candidate gap sizes for ``weighted_gap`` mode.
        weighted_gap_weights: Sampling weights paired with ``weighted_gaps``.

    Returns:
        Gap duration in seconds until the next synthetic purchase.

    Raises:
        ValueError: If the selected mode is misconfigured or unknown.
    """
    # Validate per-mode inputs here so the main loop can stay focused on the
    # synthetic clock and record emission sequence.
    if arrival_mode == "poisson":
        if poisson_rate <= 0:
            raise ValueError("poisson_rate must be > 0 for poisson arrival_mode")
        return float(rng.expovariate(poisson_rate))
    if arrival_mode == "fixed":
        if fixed_gap_seconds <= 0:
            raise ValueError("fixed_gap_seconds must be > 0 for fixed arrival_mode")
        return float(fixed_gap_seconds)
    if arrival_mode == "weighted_gap":
        if weighted_gaps is None or weighted_gap_weights is None:
            raise ValueError("weighted_gap mode requires weighted_gaps and weighted_gap_weights")
        if len(weighted_gaps) != len(weighted_gap_weights):
            raise ValueError("weighted_gaps and weighted_gap_weights must have the same length")
        return float(rng.choices(list(weighted_gaps), weights=list(weighted_gap_weights), k=1)[0])
    raise ValueError(f"unknown arrival_mode: {arrival_mode!r}")


def iter_retail_records(
    rng: random.Random,
    *,
    epoch_utc: datetime | None = None,
    shop_weights: Sequence[float] | None = None,
    max_events: int | None = None,
    max_simulated_duration_seconds: float | None = None,
    arrival_mode: str = "poisson",
    poisson_rate: float = 0.1,
    fixed_gap_seconds: float = 60.0,
    weighted_gaps: Sequence[float] | None = None,
    weighted_gap_weights: Sequence[float] | None = None,
    fan_pool: int | None = None,
    skip_default_event_cap: bool = False,
    rate_factor_fn: Callable[[datetime], float] | None = None,
) -> Iterator[dict[str, Any]]:
    """Yield deterministic synthetic retail purchase records.

    Args:
        rng: Random generator controlling all reproducible draws.
        epoch_utc: Optional UTC starting point for the synthetic clock.
        shop_weights: Optional per-shop weights matching ``SHOP_IDS`` order.
        max_events: Optional hard cap on emitted events.
        max_simulated_duration_seconds: Optional cap on simulated time elapsed
            from ``epoch_utc``.
        arrival_mode: Gap strategy name: ``poisson``, ``fixed``, or
            ``weighted_gap``.
        poisson_rate: Base events-per-second rate for Poisson arrivals.
        fixed_gap_seconds: Constant gap used by ``fixed`` mode.
        weighted_gaps: Candidate gap sizes for ``weighted_gap`` mode.
        weighted_gap_weights: Sampling weights paired with ``weighted_gaps``.
        fan_pool: Optional inclusive upper bound for generated fan IDs.
        skip_default_event_cap: Whether to disable the default 200-event cap
            when neither ``max_events`` nor duration is supplied.
        rate_factor_fn: Optional multiplier callback ``F(t)`` used to increase
            effective arrival intensity over time.

    Yields:
        NDJSON v3-compatible retail purchase dictionaries.

    Raises:
        ValueError: If arrival parameters are invalid for the chosen mode.

    Note:
        The RNG draw order per emitted event is inter-arrival gap, shop, item,
        amount jitter, then ``fan_id``. When ``rate_factor_fn`` is supplied,
        Poisson mode scales ``poisson_rate`` by ``F(t)`` while non-Poisson modes
        divide the drawn gap by ``F(t)``.
    """
    if max_events == 0:
        return

    epoch = epoch_utc if epoch_utc is not None else DEFAULT_RETAIL_SIM_EPOCH_UTC
    if shop_weights is None:
        w = DEFAULT_SHOP_WEIGHTS
    else:
        validate_shop_weights(shop_weights)
        w = tuple(shop_weights)

    me = max_events
    md = max_simulated_duration_seconds
    if me is None and md is None and not skip_default_event_cap:
        me = 200

    cap_n = me
    cap_d = md

    # Pick a conservative shared fan pool when the caller does not provide one.
    if fan_pool is None:
        est = cap_n if cap_n is not None else 500
        pool = min(500, max(est * 2, 2))
    else:
        pool = fan_pool

    t = epoch
    count = 0
    while True:
        # Stop as soon as the event-count cap is reached, before consuming any
        # more random draws.
        if cap_n is not None and count >= cap_n:
            break
        # Advance the synthetic clock according to the requested arrival model.
        if arrival_mode == "poisson":
            if poisson_rate <= 0:
                raise ValueError("poisson_rate must be > 0 for arrival_mode='poisson'")
            lam = poisson_rate
            if rate_factor_fn is not None:
                fac = max(1.0, float(rate_factor_fn(t)))
                lam = poisson_rate * fac
            if lam <= 0:
                raise ValueError("lam must be > 0 for arrival_mode='poisson'")
            gap = float(rng.expovariate(lam))
        else:
            gap = _next_interarrival_seconds(
                rng,
                arrival_mode=arrival_mode,
                poisson_rate=poisson_rate,
                fixed_gap_seconds=fixed_gap_seconds,
                weighted_gaps=weighted_gaps,
                weighted_gap_weights=weighted_gap_weights,
            )
            if rate_factor_fn is not None and gap > 0:
                fac = max(1.0, float(rate_factor_fn(t)))
                gap = float(gap) / fac
        t = t + timedelta(seconds=gap)
        # Duration checks apply after the clock advances but before emission so
        # callers never receive an out-of-window record.
        if cap_d is not None and (t - epoch).total_seconds() > cap_d:
            break

            # Emit one purchase using the documented shop → item → amount → fan draw order.
        shop = rng.choices(SHOP_IDS, weights=list(w), k=1)[0]
        item = rng.choice(ITEMS)
        amount = synthetic_line_amount_eur(item, rng)
        fan = _fan_id(rng, pool)
        ts = _dt_to_utc_z(t)
        yield make_retail_purchase(fan_id=fan, item=item, amount=amount, timestamp=ts, shop=shop)
        count += 1


def generate_retail_batch(
    rng: random.Random,
    **kwargs: Any,
) -> list[dict[str, Any]]:
    """Materialize retail records into a list.

    Args:
        rng: Random generator controlling event reproducibility.
        **kwargs: Keyword arguments forwarded to :func:`iter_retail_records`.

    Returns:
        List of generated retail purchase dictionaries.
    """
    return list(iter_retail_records(rng, **kwargs))


def generate_retail_ndjson(rng: random.Random, **kwargs: Any) -> str:
    """Generate a full retail batch and serialize it to NDJSON text.

    Args:
        rng: Random generator controlling event reproducibility.
        **kwargs: Keyword arguments forwarded to :func:`generate_retail_batch`.

    Returns:
        Canonical NDJSON text containing the generated retail records.
    """
    return records_to_ndjson_v3(generate_retail_batch(rng, **kwargs))


def iter_retail_ndjson_lines(
    rng: random.Random,
    *,
    fan_ids: set[str] | None = None,
    **kwargs: Any,
) -> Iterator[str]:
    """Yield canonical NDJSON lines for generated retail records.

    Args:
        rng: Random generator controlling event reproducibility.
        fan_ids: Optional mutable set that collects each emitted ``fan_id``.
        **kwargs: Keyword arguments forwarded to :func:`iter_retail_records`.

    Yields:
        Canonical LF-terminated NDJSON lines.
    """
    for rec in iter_retail_records(rng, **kwargs):
        if fan_ids is not None:
            fan_ids.add(rec["fan_id"])
        yield format_line_v3(rec)


def retail_stream_ndjson(rng: random.Random, **kwargs: Any) -> str:
    """Return all generated retail NDJSON lines as one concatenated string.

    Args:
        rng: Random generator controlling event reproducibility.
        **kwargs: Keyword arguments forwarded to :func:`iter_retail_ndjson_lines`.

    Returns:
        Single string containing all LF-terminated NDJSON lines.
    """
    return "".join(iter_retail_ndjson_lines(rng, **kwargs))
