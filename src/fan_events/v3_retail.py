"""Match-independent retail (NDJSON v3) synthetic event generation.

RNG draw order (for reproducibility): each event draws inter-arrival gap (mode-dependent),
then shop (weighted choice), item (uniform), amount (catalog EUR + jitter, one randint),
fan_id (pool).
"""

from __future__ import annotations

import random
from collections.abc import Callable, Iterator, Sequence
from datetime import datetime, timedelta, timezone
from typing import Any

from fan_events.data import ITEMS, SHOP_IDS, synthetic_line_amount_eur
from fan_events.domain import (
    DEFAULT_RETAIL_SIM_EPOCH_UTC,
    DEFAULT_SHOP_WEIGHTS,
    RETAIL_PURCHASE,
    validate_shop_weights,
)
from fan_events.ndjson_io import format_line_v3, records_to_ndjson_v3


def make_retail_purchase(
    *,
    fan_id: str,
    item: str,
    amount: float,
    timestamp: str,
    shop: str,
) -> dict[str, Any]:
    return {
        "amount": amount,
        "event": RETAIL_PURCHASE,
        "fan_id": fan_id,
        "item": item,
        "shop": shop,
        "timestamp": timestamp,
    }


def _dt_to_utc_z(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _fan_id(rng: random.Random, pool: int) -> str:
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
        return float(
            rng.choices(list(weighted_gaps), weights=list(weighted_gap_weights), k=1)[0]
        )
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
    """
    Deterministic order of RNG draws: inter-arrival gap, then shop, item, amount, fan_id per event.

    Stopping: default when both ``max_events`` and ``max_simulated_duration_seconds`` are ``None``,
    ``max_events`` is set to **200** unless ``skip_default_event_cap`` is true (then there is no
    event-count cap until ``max_simulated_duration_seconds`` binds, if set). When only duration is
    set, event count is unlimited until the duration window is exceeded. When both limits are set,
    generation stops when **either** is hit first (duration checked after advancing the synthetic
    clock, before emitting).

    When ``rate_factor_fn`` is set, Poisson mode uses ``λ_eff = poisson_rate * F(t)`` before each
    gap draw; non-poisson modes scale the gap inversely by ``F(t)`` (≥ 1).
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

    if fan_pool is None:
        est = cap_n if cap_n is not None else 500
        pool = min(500, max(est * 2, 2))
    else:
        pool = fan_pool

    t = epoch
    count = 0
    while True:
        if cap_n is not None and count >= cap_n:
            break
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
        if cap_d is not None and (t - epoch).total_seconds() > cap_d:
            break

        shop = rng.choices(SHOP_IDS, weights=list(w), k=1)[0]
        item = rng.choice(ITEMS)
        amount = synthetic_line_amount_eur(item, rng)
        fan = _fan_id(rng, pool)
        ts = _dt_to_utc_z(t)
        yield make_retail_purchase(
            fan_id=fan, item=item, amount=amount, timestamp=ts, shop=shop
        )
        count += 1


def generate_retail_batch(
    rng: random.Random,
    **kwargs: Any,
) -> list[dict[str, Any]]:
    return list(iter_retail_records(rng, **kwargs))


def generate_retail_ndjson(rng: random.Random, **kwargs: Any) -> str:
    return records_to_ndjson_v3(generate_retail_batch(rng, **kwargs))


def iter_retail_ndjson_lines(
    rng: random.Random,
    *,
    fan_ids: set[str] | None = None,
    **kwargs: Any,
) -> Iterator[str]:
    """Yield canonical NDJSON lines.

    If ``fan_ids`` is a set, each emitted ``fan_id`` is added to it.
    """
    for rec in iter_retail_records(rng, **kwargs):
        if fan_ids is not None:
            fan_ids.add(rec["fan_id"])
        yield format_line_v3(rec)


def retail_stream_ndjson(rng: random.Random, **kwargs: Any) -> str:
    return "".join(iter_retail_ndjson_lines(rng, **kwargs))
