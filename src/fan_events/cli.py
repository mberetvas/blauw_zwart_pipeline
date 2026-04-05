"""
Synthetic fan events NDJSON generator (stdlib only).

Normative contracts:
  specs/001-synthetic-fan-events/contracts/fan-events-ndjson-v1.md  (rolling mode)
  specs/002-match-calendar-events/contracts/fan-events-ndjson-v2.md  (--calendar mode)
  specs/003-ndjson-v3-retail-sim/contracts/fan-events-ndjson-v3.md  (generate_retail)
"""

from __future__ import annotations

import argparse
import random
import sys
from datetime import date, datetime, timezone
from pathlib import Path

from fan_events.domain import (
    DEFAULT_MERCH_FACTOR,
    DEFAULT_SCAN_FRACTION,
    MERCH_PURCHASE,
    TICKET_SCAN,
)
from fan_events.ndjson_io import records_to_ndjson_v1, records_to_ndjson_v2, write_atomic_text
from fan_events.term_style import ColoredArgumentParser, ColoredHelpFormatter
from fan_events.v1_batch import FIXED_NOW_UTC, generate_batch
from fan_events.v2_calendar import (
    CalendarError,
    filter_matches_by_date_range,
    generate_v2_records,
    load_calendar_json,
    validate_and_parse_matches,
)
from fan_events.v3_retail import generate_retail_ndjson, retail_stream_ndjson

DEFAULT_OUTPUT = "out/fan_events.ndjson"
DEFAULT_RETAIL_OUTPUT = "out/retail.ndjson"
DEFAULT_COUNT = 200
DEFAULT_DAYS = 90
SUBCOMMAND_EVENTS = "generate_events"
SUBCOMMAND_RETAIL = "generate_retail"


def _parse_iso_date(s: str) -> date:
    return date.fromisoformat(s)


def _tokens_for_flag_checks(argv: list[str] | None) -> list[str]:
    """Tokens after optional subcommand name (for mutual-exclusion checks vs --calendar)."""
    tokens = list(argv) if argv is not None else sys.argv[1:]
    if tokens and tokens[0] == SUBCOMMAND_EVENTS:
        return tokens[1:]
    return tokens


def _tokens_after_subcommand(argv: list[str] | None, subcommand: str) -> list[str]:
    tokens = list(argv) if argv is not None else sys.argv[1:]
    try:
        i = tokens.index(subcommand)
    except ValueError:
        return []
    return tokens[i + 1 :]


_RETAIL_BANNED = frozenset({
    "--calendar",
    "--from-date",
    "--to-date",
    "--scan-fraction",
    "--merch-factor",
    "-n",
    "--count",
    "--days",
    "--events",
})


def _retail_forbidden_token(tokens: list[str]) -> str | None:
    for t in tokens:
        if t in _RETAIL_BANNED:
            return t
    return None


def _parse_epoch_utc(s: str) -> datetime:
    t = s.strip()
    if t.endswith("Z"):
        t = t[:-1] + "+00:00"
    dt = datetime.fromisoformat(t)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _retail_generator_kwargs(args: argparse.Namespace) -> dict[str, object]:
    kw: dict[str, object] = {}
    if args.epoch is not None:
        kw["epoch_utc"] = _parse_epoch_utc(args.epoch)
    if args.shop_weights is not None:
        kw["shop_weights"] = tuple(args.shop_weights)
    kw["max_events"] = args.max_events
    kw["max_simulated_duration_seconds"] = args.max_duration
    kw["arrival_mode"] = args.arrival_mode
    kw["poisson_rate"] = args.poisson_rate
    kw["fixed_gap_seconds"] = args.fixed_gap_seconds
    if args.arrival_mode == "weighted_gap":
        kw["weighted_gaps"] = args.weighted_gaps
        kw["weighted_gap_weights"] = args.weighted_gap_weights
    if args.fan_pool is not None:
        kw["fan_pool"] = args.fan_pool
    return kw


def _validate_generate_retail(
    p: argparse.ArgumentParser,
    ns: argparse.Namespace,
    argv: list[str] | None,
) -> None:
    tok = _tokens_after_subcommand(argv, SUBCOMMAND_RETAIL)
    bad = _retail_forbidden_token(tok)
    if bad is not None:
        p.error(
            f"{bad} cannot be used with generate_retail "
            "(v1/v2 options belong under generate_events)"
        )
    if ns.max_events is not None and ns.max_events < 0:
        p.error("--max-events must be >= 0")
    if ns.max_duration is not None and ns.max_duration <= 0:
        p.error("--max-duration must be > 0")
    if ns.epoch is not None:
        _parse_epoch_utc(ns.epoch)
    if ns.arrival_mode == "weighted_gap":
        if not ns.weighted_gaps or not ns.weighted_gap_weights:
            p.error("weighted_gap requires --weighted-gaps and --weighted-gap-weights")
        if len(ns.weighted_gaps) != len(ns.weighted_gap_weights):
            p.error("--weighted-gaps and --weighted-gap-weights must have the same length")


# Options that consume the next argv token as their value (same set argparse uses).
_OPTS_WITH_FOLLOWING_VALUE = frozenset({
    "-o",
    "--output",
    "--seed",
    "--calendar",
    "--from-date",
    "--to-date",
    "--scan-fraction",
    "--merch-factor",
    "--events",
})


def _explicit_v1_rolling_flags_in_tokens(tokens: list[str]) -> bool:
    """
    True if -n / --count / --days appear as rolling-window options.

    Values of other flags (e.g. ``--calendar -n`` where ``-n`` is a path) are skipped
    so they are not mistaken for rolling flags.
    """
    i = 0
    n_tok = len(tokens)
    while i < n_tok:
        t = tokens[i]
        if t.startswith("--") and "=" in t:
            name, _, _ = t.partition("=")
            if name in ("--count", "--days"):
                return True
            i += 1
            continue
        if len(t) > 2 and t.startswith("-n") and t[2:].isdigit():
            return True
        if t in ("-n", "--count", "--days"):
            return True
        if t in _OPTS_WITH_FOLLOWING_VALUE:
            i += 2
            continue
        i += 1
    return False


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = ColoredArgumentParser(
        prog="fan_events",
        description=(
            "Generate synthetic fan events as UTF-8 NDJSON "
            "(v1 rolling, v2 calendar, or v3 retail)."
        ),
        formatter_class=ColoredHelpFormatter,
    )
    sub = p.add_subparsers(dest="command", required=True, parser_class=ColoredArgumentParser)
    gen = sub.add_parser(
        SUBCOMMAND_EVENTS,
        help="Generate NDJSON to a file (v1 rolling or v2 calendar).",
        formatter_class=ColoredHelpFormatter,
    )
    gen.add_argument(
        "-o",
        "--output",
        default=DEFAULT_OUTPUT,
        help=f"Output NDJSON path (default: {DEFAULT_OUTPUT})",
    )
    gen.add_argument(
        "--seed",
        type=int,
        default=None,
        help="RNG seed for byte-identical reproducibility (omit for non-deterministic run in v1)",
    )

    rolling = gen.add_argument_group("Rolling window (fan-events-ndjson-v1)")
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

    cal = gen.add_argument_group("Calendar (fan-events-ndjson-v2)")
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

    gen.add_argument(
        "--events",
        choices=("both", TICKET_SCAN, MERCH_PURCHASE),
        default="both",
        help="Event types to emit (default: both)",
    )

    ret = sub.add_parser(
        SUBCOMMAND_RETAIL,
        help="Generate match-independent retail_purchase NDJSON (v3) to a file or stdout.",
        formatter_class=ColoredHelpFormatter,
    )
    ret.add_argument(
        "-o",
        "--output",
        default=DEFAULT_RETAIL_OUTPUT,
        help=f"Output NDJSON path when not using --stream (default: {DEFAULT_RETAIL_OUTPUT})",
    )
    ret.add_argument(
        "--seed",
        type=int,
        default=None,
        help="RNG seed for byte-identical reproducibility (batch and stream)",
    )
    ret.add_argument(
        "--stream",
        action="store_true",
        help="Write NDJSON to stdout in generation order (no global sort); ignores file output",
    )
    ret.add_argument(
        "--max-events",
        type=int,
        default=None,
        help="Stop after N events (0 → empty). If omitted with no --max-duration, defaults to 200.",
    )
    ret.add_argument(
        "--max-duration",
        type=float,
        default=None,
        dest="max_duration",
        metavar="SECONDS",
        help=(
            "Maximum simulated timeline length in seconds from epoch; "
            "with --max-events, stop when either binds first"
        ),
    )
    ret.add_argument(
        "--epoch",
        type=str,
        default=None,
        help="UTC start instant for the synthetic timeline (ISO-8601, e.g. 2026-01-01T00:00:00Z)",
    )
    ret.add_argument(
        "--shop-weights",
        nargs=3,
        type=float,
        metavar=("W1", "W2", "W3"),
        default=None,
        help=(
            "Three non-negative weights for shops "
            "(order: jan_breydel_fan_shop, webshop, bruges_city_shop)"
        ),
    )
    ret.add_argument(
        "--arrival-mode",
        choices=("poisson", "fixed", "weighted_gap"),
        default="poisson",
        help="Inter-arrival model (default: poisson)",
    )
    ret.add_argument(
        "--poisson-rate",
        type=float,
        default=0.1,
        help="Poisson rate (events per second) for expovariate gaps (default: 0.1)",
    )
    ret.add_argument(
        "--fixed-gap-seconds",
        type=float,
        default=60.0,
        help="Fixed seconds between successive events when --arrival-mode fixed (default: 60)",
    )
    ret.add_argument(
        "--weighted-gaps",
        nargs="+",
        type=float,
        default=None,
        metavar="SEC",
        help="Candidate gap lengths for weighted_gap mode (use with --weighted-gap-weights)",
    )
    ret.add_argument(
        "--weighted-gap-weights",
        nargs="+",
        type=float,
        default=None,
        metavar="W",
        help="Weights for each value in --weighted-gaps (same length)",
    )
    ret.add_argument(
        "--fan-pool",
        type=int,
        default=None,
        metavar="N",
        help="Upper bound for fan_id numeric suffix pool (default: heuristic from max_events)",
    )

    ns = p.parse_args(argv)

    if ns.command == SUBCOMMAND_RETAIL:
        _validate_generate_retail(p, ns, argv)
        return ns

    raw = _tokens_for_flag_checks(argv)

    if ns.calendar:
        if _explicit_v1_rolling_flags_in_tokens(raw):
            p.error(
                "-n / --count / --days cannot be used with --calendar (v2 calendar mode)"
            )
        if (ns.from_date is None) != (ns.to_date is None):
            p.error(
                "--from-date and --to-date must be given together, "
                "or omit both to include all matches"
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


def run_v3(args: argparse.Namespace) -> None:
    rng = random.Random(args.seed) if args.seed is not None else random.Random()
    kw = _retail_generator_kwargs(args)
    if args.stream:
        text = retail_stream_ndjson(rng, **kw)
        sys.stdout.write(text)
        sys.stdout.flush()
    else:
        text = generate_retail_ndjson(rng, **kw)
        write_atomic_text(Path(args.output), text)


def main(argv: list[str] | None = None) -> None:
    try:
        args = parse_args(argv)
        if args.command == SUBCOMMAND_RETAIL:
            run_v3(args)
        elif args.calendar:
            run_v2(args)
        else:
            run_v1(args)
    except SystemExit:
        raise
    except CalendarError as e:
        print(f"fan_events: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"fan_events: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
