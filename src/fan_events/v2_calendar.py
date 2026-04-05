"""Match calendar load, validation, and v2 NDJSON record generation."""

from __future__ import annotations

import json
import random
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


def generate_v2_records(
    contexts: list[MatchContext],
    rng: random.Random,
    *,
    scan_fraction: float = DEFAULT_SCAN_FRACTION,
    merch_factor: float = DEFAULT_MERCH_FACTOR,
    events_mode: str = "both",
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for ctx in contexts:
        row = ctx.row
        mid = str(row["match_id"])
        venue = str(row["venue_label"])
        cap = ctx.effective_cap
        start_sec = int(ctx.window_start.timestamp())
        end_sec = int(ctx.window_end.timestamp())

        fan_indices = list(range(1, JAN_BREYDEL_MAX_CAPACITY + 1))
        rng.shuffle(fan_indices)
        pick_n = min(cap, len(fan_indices))
        pool = [f"fan_{fan_indices[i]:05d}" for i in range(pick_n)]

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
