"""
Synthetic fan events NDJSON generator (stdlib only).

Normative contracts:
  specs/001-synthetic-fan-events/contracts/fan-events-ndjson-v1.md  (rolling mode)
  specs/002-match-calendar-events/contracts/fan-events-ndjson-v2.md  (--calendar mode)
"""

from __future__ import annotations

import argparse
import random
import sys
from datetime import date, datetime, timezone
from pathlib import Path

from fan_events.domain import MERCH_PURCHASE, TICKET_SCAN
from fan_events.ndjson_io import records_to_ndjson_v1, records_to_ndjson_v2, write_atomic_text
from fan_events.v1_batch import FIXED_NOW_UTC, generate_batch
from fan_events.v2_calendar import (
    CalendarError,
    filter_matches_by_date_range,
    generate_v2_records,
    load_calendar_json,
    validate_and_parse_matches,
)

DEFAULT_OUTPUT = "out/fan_events.ndjson"
DEFAULT_COUNT = 200
DEFAULT_DAYS = 90


def _parse_iso_date(s: str) -> date:
    return date.fromisoformat(s)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Generate synthetic fan events as UTF-8 NDJSON (v1 rolling or v2 calendar).",
    )
    p.add_argument(
        "-o",
        "--output",
        default=DEFAULT_OUTPUT,
        help=f"Output NDJSON path (default: {DEFAULT_OUTPUT})",
    )
    p.add_argument(
        "--seed",
        type=int,
        default=None,
        help="RNG seed for byte-identical reproducibility (omit for non-deterministic run in v1)",
    )

    rolling = p.add_argument_group("Rolling window (fan-events-ndjson-v1)")
    rolling.add_argument(
        "-n",
        "--count",
        type=int,
        default=DEFAULT_COUNT,
        help=f"Total events to emit (default: {DEFAULT_COUNT})",
    )
    rolling.add_argument(
        "--days",
        type=int,
        default=DEFAULT_DAYS,
        help=f"UTC rolling window length ending at generation time (default: {DEFAULT_DAYS})",
    )

    cal = p.add_argument_group("Calendar (fan-events-ndjson-v2)")
    cal.add_argument(
        "--calendar",
        type=str,
        default=None,
        help="Path to calendar JSON (data-model.md); enables v2 output",
    )
    cal.add_argument(
        "--from-date",
        type=str,
        default=None,
        help=(
            "Inclusive lower bound on kickoff UTC date (YYYY-MM-DD); "
            "omit both --from-date and --to-date to include every match"
        ),
    )
    cal.add_argument(
        "--to-date",
        type=str,
        default=None,
        help=(
            "Inclusive upper bound on kickoff UTC date (YYYY-MM-DD); "
            "omit both --from-date and --to-date to include every match"
        ),
    )
    cal.add_argument(
        "--scan-fraction",
        type=float,
        default=None,
        help="Fraction of capacity for ticket_scan volume (default: from fan_events.domain)",
    )
    cal.add_argument(
        "--merch-factor",
        type=float,
        default=None,
        help="Scale for merch_purchase event count vs capacity (default: from fan_events.domain)",
    )

    p.add_argument(
        "--events",
        choices=("both", TICKET_SCAN, MERCH_PURCHASE),
        default="both",
        help="Event types to emit (default: both)",
    )
    raw = list(argv) if argv is not None else sys.argv[1:]
    ns = p.parse_args(argv)

    if ns.calendar:
        for flag in ("-n", "--count", "--days"):
            if flag in raw:
                p.error(f"{flag} cannot be used with --calendar (v2 calendar mode)")
        if (ns.from_date is None) != (ns.to_date is None):
            p.error(
                "--from-date and --to-date must be given together, or omit both to include all matches"
            )
    else:
        if ns.from_date is not None or ns.to_date is not None:
            p.error("--from-date / --to-date require --calendar")
        if ns.scan_fraction is not None or ns.merch_factor is not None:
            p.error("--scan-fraction / --merch-factor require --calendar")

    if not ns.calendar:
        if ns.count < 0:
            p.error("--count must be >= 0")
        if ns.days < 1:
            p.error("--days must be >= 1")
        if ns.events == "both" and ns.count == 1:
            p.error("--events both requires --count >= 2 (need at least one of each type)")
    return ns


def run_v1(args: argparse.Namespace) -> None:
    rng = random.Random(args.seed) if args.seed is not None else random.Random()
    now = FIXED_NOW_UTC if args.seed is not None else datetime.now(timezone.utc)
    records = generate_batch(
        rng,
        count=args.count,
        days=args.days,
        events_mode=args.events,
        now_utc=now,
    )
    text = records_to_ndjson_v1(records)
    write_atomic_text(Path(args.output), text)


def run_v2(args: argparse.Namespace) -> None:
    from fan_events.domain import DEFAULT_MERCH_FACTOR, DEFAULT_SCAN_FRACTION

    path = Path(args.calendar)
    doc = load_calendar_json(path)
    rows = validate_and_parse_matches(doc)
    from_d = _parse_iso_date(args.from_date) if args.from_date is not None else None
    to_d = _parse_iso_date(args.to_date) if args.to_date is not None else None
    contexts = filter_matches_by_date_range(rows, from_d, to_d)
    rng = random.Random(args.seed) if args.seed is not None else random.Random()
    sf = DEFAULT_SCAN_FRACTION if args.scan_fraction is None else args.scan_fraction
    mf = DEFAULT_MERCH_FACTOR if args.merch_factor is None else args.merch_factor
    records = generate_v2_records(
        contexts,
        rng,
        scan_fraction=sf,
        merch_factor=mf,
        events_mode=args.events,
    )
    text = records_to_ndjson_v2(records)
    write_atomic_text(Path(args.output), text)


def main(argv: list[str] | None = None) -> None:
    try:
        args = parse_args(argv)
        if args.calendar:
            run_v2(args)
        else:
            run_v1(args)
    except SystemExit:
        raise
    except CalendarError as e:
        print(f"generate_fan_events: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"generate_fan_events: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
