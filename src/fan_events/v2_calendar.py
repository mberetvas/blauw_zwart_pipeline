"""Match calendar load, validation, and v2 NDJSON record generation."""

from __future__ import annotations

import heapq
import json
import random
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from fan_events.data import ITEMS, LOCATIONS, synthetic_line_amount_eur
from fan_events.domain import (
    DEFAULT_MERCH_FACTOR,
    DEFAULT_SCAN_FRACTION,
    JAN_BREYDEL_MAX_CAPACITY,
    MERCH_PURCHASE,
    TICKET_SCAN,
)
from fan_events.merge_keys import merge_key_tuple


class CalendarError(ValueError):
    """Invalid calendar document or row."""


@dataclass(frozen=True)
class MatchContext:
    row: dict[str, Any]
    kickoff_utc: datetime
    window_start: datetime
    window_end: datetime
    effective_cap: int


def load_calendar_json(path: Path) -> dict[str, Any]:
    raw = path.read_text(encoding="utf-8")
    try:
        doc = json.loads(raw)
    except json.JSONDecodeError as e:
        raise CalendarError(f"calendar JSON invalid: {e}") from e
    if not isinstance(doc, dict):
        raise CalendarError("calendar root must be a JSON object")
    return doc


def validate_and_parse_matches(doc: dict[str, Any]) -> list[dict[str, Any]]:
    matches = doc.get("matches")
    if matches is None:
        raise CalendarError("calendar must contain 'matches'")
    if not isinstance(matches, list):
        raise CalendarError("'matches' must be an array")
    seen: set[str] = set()
    for row in matches:
        if not isinstance(row, dict):
            raise CalendarError("each match must be an object")
        mid = row.get("match_id")
        if not mid or not isinstance(mid, str):
            raise CalendarError("match_id required (non-empty string)")
        if mid in seen:
            raise CalendarError(f"duplicate match_id: {mid!r}")
        seen.add(mid)
        for key in (
            "kickoff_local",
            "timezone",
            "attendance",
            "home_away",
            "venue_label",
        ):
            if key not in row:
                raise CalendarError(f"match {mid!r}: missing {key!r}")
        att = row["attendance"]
        if not isinstance(att, int) or isinstance(att, bool):
            raise CalendarError(f"match {mid!r}: attendance must be an integer")
        if att <= 0:
            raise CalendarError(f"match {mid!r}: attendance must be > 0")
        ha = row["home_away"]
        if ha not in ("home", "away"):
            raise CalendarError(f"match {mid!r}: home_away must be 'home' or 'away'")
        if ha == "home" and att > JAN_BREYDEL_MAX_CAPACITY:
            raise CalendarError(
                f"match {mid!r}: home attendance {att} exceeds Jan Breydel capacity "
                f"{JAN_BREYDEL_MAX_CAPACITY}"
            )
        try:
            ZoneInfo(str(row["timezone"]))
        except Exception as e:
            raise CalendarError(f"match {mid!r}: invalid timezone: {e}") from e
        try:
            datetime.fromisoformat(str(row["kickoff_local"]))
        except ValueError as e:
            raise CalendarError(f"match {mid!r}: invalid kickoff_local: {e}") from e
    return list(matches)


def kickoff_utc_for_row(row: dict[str, Any]) -> datetime:
    local_s = str(row["kickoff_local"])
    tz_name = str(row["timezone"])
    naive = datetime.fromisoformat(local_s)
    if naive.tzinfo is not None:
        mid = row.get("match_id")
        raise CalendarError(f"match {mid!r}: kickoff_local must be naive local time")
    tz = ZoneInfo(tz_name)
    aware = naive.replace(tzinfo=tz)
    return aware.astimezone(timezone.utc)


def match_window(
    kickoff: datetime,
    *,
    start_offset_min: int = 120,
    end_offset_min: int = 90,
) -> tuple[datetime, datetime]:
    start = kickoff - timedelta(minutes=start_offset_min)
    end = kickoff + timedelta(minutes=end_offset_min)
    return (start, end)


def effective_cap(row: dict[str, Any]) -> int:
    att = int(row["attendance"])
    if row["home_away"] == "home":
        return min(att, JAN_BREYDEL_MAX_CAPACITY)
    return att


def build_match_context(row: dict[str, Any]) -> MatchContext:
    ku = kickoff_utc_for_row(row)
    ws = int(row.get("window_start_offset_minutes", 120))
    we = int(row.get("window_end_offset_minutes", 90))
    w0, w1 = match_window(ku, start_offset_min=ws, end_offset_min=we)
    cap = effective_cap(row)
    return MatchContext(row=row, kickoff_utc=ku, window_start=w0, window_end=w1, effective_cap=cap)


def filter_matches_by_date_range(
    rows: list[dict[str, Any]],
    from_date: date | None,
    to_date: date | None,
) -> list[MatchContext]:
    contexts: list[MatchContext] = []
    for row in rows:
        ctx = build_match_context(row)
        kd = ctx.kickoff_utc.date()
        if from_date is not None and kd < from_date:
            continue
        if to_date is not None and kd > to_date:
            continue
        contexts.append(ctx)
    contexts.sort(key=lambda c: (c.kickoff_utc, c.row["match_id"]))
    return contexts


def _ts_string_from_epoch(rng: random.Random, start_sec: int, end_sec: int) -> str:
    if end_sec < start_sec:
        start_sec, end_sec = end_sec, start_sec
    sec = rng.randint(start_sec, end_sec)
    dt = datetime.fromtimestamp(sec, tz=timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _fan_index_upper(fan_pool_max: int | None) -> int:
    """Upper bound for fan index pool (inclusive range 1..upper)."""
    return fan_pool_max if fan_pool_max is not None else JAN_BREYDEL_MAX_CAPACITY


def records_for_match(
    ctx: MatchContext,
    rng: random.Random,
    *,
    scan_fraction: float = DEFAULT_SCAN_FRACTION,
    merch_factor: float = DEFAULT_MERCH_FACTOR,
    events_mode: str = "both",
    fan_pool_max: int | None = None,
) -> list[dict[str, Any]]:
    """
    Build v2 records for one match in the same order as legacy ``generate_v2_records``:
    all ticket_scan rows, then all merch_purchase rows.
    """
    row = ctx.row
    mid = str(row["match_id"])
    venue = str(row["venue_label"])
    cap = ctx.effective_cap
    start_sec = int(ctx.window_start.timestamp())
    end_sec = int(ctx.window_end.timestamp())

    upper = _fan_index_upper(fan_pool_max)
    fan_indices = list(range(1, upper + 1))
    rng.shuffle(fan_indices)
    pick_n = min(cap, len(fan_indices))
    pool = [f"fan_{fan_indices[i]:05d}" for i in range(pick_n)]

    records: list[dict[str, Any]] = []
    if events_mode == TICKET_SCAN:
        ts_count = max(1, int(cap * scan_fraction))
        merch_count = 0
    elif events_mode == MERCH_PURCHASE:
        ts_count = 0
        merch_count = max(1, int(cap * merch_factor))
    else:
        ts_count = max(1, int(cap * scan_fraction))
        merch_count = max(1, int(cap * merch_factor))

    for i in range(ts_count):
        fan_id = pool[i % len(pool)]
        loc = rng.choice(LOCATIONS) if row["home_away"] == "home" else venue
        ts = _ts_string_from_epoch(rng, start_sec, end_sec)
        records.append(
            {
                "event": TICKET_SCAN,
                "fan_id": fan_id,
                "location": loc,
                "match_id": mid,
                "timestamp": ts,
            }
        )
    for _ in range(merch_count):
        fan_id = pool[rng.randrange(0, len(pool))]
        ts = _ts_string_from_epoch(rng, start_sec, end_sec)
        item = rng.choice(ITEMS)
        amt = synthetic_line_amount_eur(item, rng)
        rec: dict[str, Any] = {
            "amount": amt,
            "event": MERCH_PURCHASE,
            "fan_id": fan_id,
            "item": item,
            "match_id": mid,
            "timestamp": ts,
        }
        rec["location"] = venue
        records.append(rec)
    return records


def generate_v2_records(
    contexts: list[MatchContext],
    rng: random.Random,
    *,
    scan_fraction: float = DEFAULT_SCAN_FRACTION,
    merch_factor: float = DEFAULT_MERCH_FACTOR,
    events_mode: str = "both",
    fan_pool_max: int | None = None,
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for ctx in contexts:
        records.extend(
            records_for_match(
                ctx,
                rng,
                scan_fraction=scan_fraction,
                merch_factor=merch_factor,
                events_mode=events_mode,
                fan_pool_max=fan_pool_max,
            )
        )
    return records


def iter_sorted_records_for_match(
    ctx: MatchContext,
    rng: random.Random,
    *,
    scan_fraction: float = DEFAULT_SCAN_FRACTION,
    merch_factor: float = DEFAULT_MERCH_FACTOR,
    events_mode: str = "both",
    fan_pool_max: int | None = None,
) -> Iterator[dict[str, Any]]:
    """
    Yield match records sorted by ``merge_key_tuple`` (non-decreasing).

    Preconditions: iteration order is suitable as one input to ``heapq.merge`` with the same key.
    """
    recs = records_for_match(
        ctx,
        rng,
        scan_fraction=scan_fraction,
        merch_factor=merch_factor,
        events_mode=events_mode,
        fan_pool_max=fan_pool_max,
    )
    recs.sort(key=merge_key_tuple)
    yield from recs


def iter_v2_records_merged_sorted(
    contexts: list[MatchContext],
    rng: random.Random,
    *,
    scan_fraction: float = DEFAULT_SCAN_FRACTION,
    merch_factor: float = DEFAULT_MERCH_FACTOR,
    events_mode: str = "both",
    fan_pool_max: int | None = None,
) -> Iterator[dict[str, Any]]:
    """
    Globally merge per-match streams with ``heapq.merge``.

    Each inner iterator from ``iter_sorted_records_for_match`` is non-decreasing by
    ``merge_key_tuple``.

    RNG is consumed in **match order** (same as ``generate_v2_records``): we materialize each
    match's sorted list before merging, so ``random.Random`` state matches batch generation.
    """
    per_match_iters: list[Iterator[dict[str, Any]]] = []
    for ctx in contexts:
        recs = list(
            iter_sorted_records_for_match(
                ctx,
                rng,
                scan_fraction=scan_fraction,
                merch_factor=merch_factor,
                events_mode=events_mode,
                fan_pool_max=fan_pool_max,
            )
        )
        per_match_iters.append(iter(recs))
    if not per_match_iters:
        return
    yield from heapq.merge(*per_match_iters, key=merge_key_tuple)


def add_calendar_years_to_naive_local(naive: datetime, years: int) -> datetime:
    """Add *years* to naive local datetime; Feb 29 clamps to Feb 28 in non-leap years."""
    y = naive.year + years
    m, d = naive.month, naive.day
    if m == 2 and d == 29:
        try:
            date(y, 2, 29)
        except ValueError:
            d = 28
    return naive.replace(year=y, month=m, day=d)


def shift_match_context_calendar_years(ctx: MatchContext, cycle: int) -> MatchContext:
    """Shift ``kickoff_local`` by *cycle* calendar years; suffix ``match_id`` with ``:c{cycle}``."""
    if cycle < 1:
        raise ValueError("cycle must be >= 1")
    new_row = dict(ctx.row)
    naive = datetime.fromisoformat(str(ctx.row["kickoff_local"]))
    new_naive = add_calendar_years_to_naive_local(naive, cycle)
    new_row["kickoff_local"] = new_naive.isoformat()
    new_row["match_id"] = f"{ctx.row['match_id']}:c{cycle}"
    return build_match_context(new_row)


def shift_match_context(ctx: MatchContext, shift: timedelta, cycle: int) -> MatchContext:
    """Return a new MatchContext with all timestamps shifted by *shift* and match_id suffixed.

    The ``kickoff_local`` string in the row dict is updated to keep it consistent with
    ``kickoff_utc`` (shift applied in UTC-equivalent wall-clock offset; the naive local string
    is shifted by the same delta, which is correct for a synthetic replay that does not need
    DST-aware rescheduling).
    """
    new_row = dict(ctx.row)
    naive = datetime.fromisoformat(str(ctx.row["kickoff_local"]))
    new_row["kickoff_local"] = (naive + shift).isoformat()
    new_row["match_id"] = f"{ctx.row['match_id']}:c{cycle}"
    return MatchContext(
        row=new_row,
        kickoff_utc=ctx.kickoff_utc + shift,
        window_start=ctx.window_start + shift,
        window_end=ctx.window_end + shift,
        effective_cap=ctx.effective_cap,
    )


def iter_looped_v2_records(
    base_contexts: list[MatchContext],
    rng: random.Random,
    *,
    scan_fraction: float = DEFAULT_SCAN_FRACTION,
    merch_factor: float = DEFAULT_MERCH_FACTOR,
    events_mode: str = "both",
    fan_pool_max: int | None = None,
) -> Iterator[dict[str, Any]]:
    """Yield v2 records indefinitely by cycling *base_contexts* with **+1 calendar year** per pass.

    Cycle 0 uses the original contexts; cycle N ≥ 1 applies ``shift_match_context_calendar_years``
    (Feb 29 → Feb 28 when needed). A **single RNG** is shared across cycles.

    Stops when the consumer stops pulling (``--max-events``, ``--max-duration``, ``Ctrl+C``, etc.).
    """
    if not base_contexts:
        return
    cycle = 0
    while True:
        if cycle == 0:
            contexts = base_contexts
        else:
            contexts = [
                shift_match_context_calendar_years(ctx, cycle) for ctx in base_contexts
            ]
        yield from iter_v2_records_merged_sorted(
            contexts,
            rng,
            scan_fraction=scan_fraction,
            merch_factor=merch_factor,
            events_mode=events_mode,
            fan_pool_max=fan_pool_max,
        )
        cycle += 1
