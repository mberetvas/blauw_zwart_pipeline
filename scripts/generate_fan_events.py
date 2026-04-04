"""
Synthetic fan events NDJSON generator (stdlib only).

Normative contract:
  specs/001-synthetic-fan-events/contracts/fan-events-ndjson-v1.md
"""

from __future__ import annotations

import argparse
import json
import os
import random
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

# --- defaults (contract fan-events-ndjson-v1.md) ---
DEFAULT_OUTPUT = "out/fan_events.ndjson"
DEFAULT_COUNT = 200
DEFAULT_DAYS = 90

# When --seed is set, wall-clock "now" would change between runs and break byte identity (FR-005).
FIXED_NOW_UTC = datetime(2026, 4, 1, 15, 0, 0, tzinfo=timezone.utc)

TICKET_SCAN = "ticket_scan"
MERCH_PURCHASE = "merch_purchase"

LOCATIONS = [
    "Jan Breydel Noord A",
    "Jan Breydel Zuid B",
    "Tribune 3 Gate 7",
    "Fan Zone East",
    "VIP Ingang West",
]
ITEMS = [
    "Sjaal blauw-zwart",
    "Cap retro",
    "Drankbon 0,5L",
    "Programmaboekje",
    "Sticker set",
]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Generate synthetic fan events as UTF-8 NDJSON.",
    )
    p.add_argument(
        "-o",
        "--output",
        default=DEFAULT_OUTPUT,
        help=f"Output NDJSON path (default: {DEFAULT_OUTPUT})",
    )
    p.add_argument(
        "-n",
        "--count",
        type=int,
        default=DEFAULT_COUNT,
        help=f"Total events to emit (default: {DEFAULT_COUNT})",
    )
    p.add_argument(
        "--days",
        type=int,
        default=DEFAULT_DAYS,
        help=f"UTC rolling window length ending at generation time (default: {DEFAULT_DAYS})",
    )
    p.add_argument(
        "--seed",
        type=int,
        default=None,
        help="RNG seed for byte-identical reproducibility (omit for non-deterministic run)",
    )
    p.add_argument(
        "--events",
        choices=("both", TICKET_SCAN, MERCH_PURCHASE),
        default="both",
        help="Event types to emit (default: both)",
    )
    ns = p.parse_args(argv)
    if ns.count < 0:
        p.error("--count must be >= 0")
    if ns.days < 1:
        p.error("--days must be >= 1")
    if ns.events == "both" and ns.count == 1:
        p.error("--events both requires --count >= 2 (need at least one of each type)")
    return ns


def dumps_canonical(obj: dict[str, Any]) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def ensure_parent_dir(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def write_atomic_text(path: Path, content: str) -> None:
    path = path.resolve()
    ensure_parent_dir(path)
    tmp_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            delete=False,
            dir=str(path.parent),
            prefix=f".{path.name}.",
            suffix=".tmp",
        ) as tf:
            tf.write(content)
            tmp_name = tf.name
        os.replace(tmp_name, path)
        tmp_name = None
    except Exception:
        if tmp_name and os.path.exists(tmp_name):
            try:
                os.unlink(tmp_name)
            except OSError:
                pass
        raise


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


def validate_record(rec: dict[str, Any]) -> None:
    if not isinstance(rec, dict):
        raise ValueError("record must be a dict")
    ev = rec.get("event")
    if ev == TICKET_SCAN:
        allowed = {"event", "fan_id", "location", "timestamp"}
        if set(rec.keys()) != allowed:
            raise ValueError(f"ticket_scan must have exactly keys {sorted(allowed)}")
        if not rec["fan_id"] or not rec["location"] or not rec["timestamp"]:
            raise ValueError("ticket_scan: fan_id, location, timestamp must be non-empty")
    elif ev == MERCH_PURCHASE:
        allowed = {"amount", "event", "fan_id", "item", "timestamp"}
        if set(rec.keys()) != allowed:
            raise ValueError(f"merch_purchase must have exactly keys {sorted(allowed)}")
        if not rec["fan_id"] or not rec["item"] or not rec["timestamp"]:
            raise ValueError("merch_purchase: fan_id, item, timestamp must be non-empty")
        amt = rec["amount"]
        if not isinstance(amt, (int, float)) or isinstance(amt, bool):
            raise ValueError("merch_purchase: amount must be a number")
        if amt <= 0:
            raise ValueError("merch_purchase: amount must be > 0")
    else:
        raise ValueError(f"unknown event: {ev!r}")


def _event_rank(event: str) -> int:
    if event == TICKET_SCAN:
        return 0
    if event == MERCH_PURCHASE:
        return 1
    raise ValueError(f"unknown event for rank: {event!r}")


def sort_key(rec: dict[str, Any]) -> tuple:
    ev = rec["event"]
    ts = rec["timestamp"]
    fan = rec["fan_id"]
    rank = _event_rank(ev)
    if ev == TICKET_SCAN:
        return (ts, rank, fan, rec["location"], "", 0.0)
    return (ts, rank, fan, "", rec["item"], float(rec["amount"]))


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
        cents = rng.randint(1, 99999)
        amount = round(cents / 100.0, 2)
        return make_merch_purchase(
            _fan_id(rng, fan_pool),
            rng.choice(ITEMS),
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

    # both — count >= 2 enforced by argparse
    records.append(one_ticket())
    records.append(one_merch())
    for _ in range(count - 2):
        if rng.random() < 0.5:
            records.append(one_ticket())
        else:
            records.append(one_merch())
    return records


def records_to_ndjson(records: list[dict[str, Any]]) -> str:
    if not records:
        return ""
    for rec in records:
        validate_record(rec)
    ordered = sorted(records, key=sort_key)
    lines = [dumps_canonical(r) for r in ordered]
    body = "\n".join(lines)
    return body + "\n"


def main(argv: list[str] | None = None) -> None:
    try:
        args = parse_args(argv)
        rng = random.Random(args.seed) if args.seed is not None else random.Random()
        now = FIXED_NOW_UTC if args.seed is not None else datetime.now(timezone.utc)
        records = generate_batch(
            rng,
            count=args.count,
            days=args.days,
            events_mode=args.events,
            now_utc=now,
        )
        text = records_to_ndjson(records)
        out = Path(args.output)
        write_atomic_text(out, text)
    except SystemExit:
        raise
    except Exception as e:
        print(f"generate_fan_events: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
