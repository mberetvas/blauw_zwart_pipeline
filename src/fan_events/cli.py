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
import time
from datetime import date, datetime, timezone
from pathlib import Path

from fan_events.domain import (
    DEFAULT_MERCH_FACTOR,
    DEFAULT_RETAIL_SIM_EPOCH_UTC,
    DEFAULT_SCAN_FRACTION,
    MERCH_PURCHASE,
    TICKET_SCAN,
)
from fan_events.fan_profiles import build_fans_sidecar, format_fans_sidecar_json
from fan_events.ndjson_io import (
    records_to_ndjson_v1,
    records_to_ndjson_v2,
    records_to_ndjson_v3,
    write_atomic_text,
)
from fan_events.term_style import ColoredArgumentParser, ColoredHelpFormatter
from fan_events.v1_batch import FIXED_NOW_UTC, generate_batch
from fan_events.v2_calendar import (
    CalendarError,
    filter_matches_by_date_range,
    generate_v2_records,
    load_calendar_json,
    validate_and_parse_matches,
)
from fan_events.v3_retail import (
    generate_retail_batch,
    iter_retail_ndjson_lines,
    retail_stream_ndjson,
)

DEFAULT_OUTPUT = "out/fan_events.ndjson"
DEFAULT_RETAIL_OUTPUT = "out/retail.ndjson"


def _companion_fans_json_path(ndjson_path: str) -> str:
    """Sidecar fan master path: same location/stem as the NDJSON output, ``.json`` suffix."""
    return str(Path(ndjson_path).with_suffix(".json"))
DEFAULT_COUNT = 200
DEFAULT_DAYS = 90
# Aligned with fan_events.v3_retail.iter_retail_records (do not drift silently).
DEFAULT_RETAIL_IMPLIED_MAX_EVENTS = 200
DEFAULT_RETAIL_POISSON_RATE = 0.1
DEFAULT_RETAIL_FIXED_GAP_SECONDS = 60.0
_DEFAULT_RETAIL_EPOCH_HELP_STR = DEFAULT_RETAIL_SIM_EPOCH_UTC.strftime("%Y-%m-%dT%H:%M:%SZ")
SUBCOMMAND_EVENTS = "generate_events"
SUBCOMMAND_RETAIL = "generate_retail"

# Copy-paste examples (flags/paths align with README). Epilog is styled by ColoredHelpFormatter.
_HELP_DEV_NOTE = (
    "Without install, prefix with uv run or uv run python -m fan_events (same arguments).\n\n"
)

_EX_HELP_ROOT = "fan_events --help"
_EX_HELP_EVENTS = "fan_events generate_events --help"
_EX_HELP_RETAIL = "fan_events generate_retail --help"
_EX_V1_ROLLING = "fan_events generate_events -s 1 -n 200 -d 90 -o out/v1.ndjson"
_EX_V2_CAL_ALL = "fan_events generate_events -c my_calendar.json -s 42 -o out/v2.ndjson"
_EX_V2_DATE_RANGE = (
    "fan_events generate_events -c my_calendar.json "
    "--from-date 2026-09-01 --to-date 2026-12-31 -s 42 -o out/v2.ndjson"
)
_EX_V3_FILE = "fan_events generate_retail -o out/retail.ndjson -s 42"
_EX_V3_STREAM = "fan_events generate_retail -t -s 42 -n 100"
_EX_V3_STREAM_LIVE = (
    "fan_events generate_retail -t -s 42 -n 50 --emit-wall-clock-min 0.5 --emit-wall-clock-max 2.0"
)

EPILOG_ROOT = (
    _HELP_DEV_NOTE
    + "Examples:\n\n"
    + "\n".join(
        (
            _EX_HELP_ROOT,
            _EX_HELP_EVENTS,
            _EX_HELP_RETAIL,
            "",
            _EX_V1_ROLLING,
            _EX_V2_CAL_ALL,
            _EX_V2_DATE_RANGE,
            "",
            _EX_V3_FILE,
            _EX_V3_STREAM,
        )
    )
    + "\n"
)

EPILOG_GENERATE_EVENTS = (
    "Examples:\n\n"
    + "\n".join((_EX_HELP_EVENTS, _EX_V1_ROLLING, _EX_V2_CAL_ALL, _EX_V2_DATE_RANGE))
    + "\n"
)

EPILOG_GENERATE_RETAIL = (
    "Examples:\n\n"
    + "\n".join((_EX_HELP_RETAIL, _EX_V3_FILE, _EX_V3_STREAM, _EX_V3_STREAM_LIVE))
    + "\n"
)


def _parse_iso_date(s: str) -> date:
    return date.fromisoformat(s)


def _write_fans_sidecar(path: Path, fan_ids: set[str], global_seed: int | None) -> None:
    doc = build_fans_sidecar(fan_ids, global_seed=global_seed)
    write_atomic_text(path, format_fans_sidecar_json(doc))


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
    if args.unlimited:
        kw["skip_default_event_cap"] = True
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

    emit_min = ns.emit_wall_clock_min
    emit_max = ns.emit_wall_clock_max
    if (emit_min is None) != (emit_max is None):
        p.error("--emit-wall-clock-min and --emit-wall-clock-max must be given together")
    if emit_min is not None:
        if not ns.stream:
            p.error("--emit-wall-clock-min/max require --stream")
        if emit_min < 0 or emit_max < 0:
            p.error("--emit-wall-clock-min/max must be >= 0")
        if emit_min > emit_max:
            p.error("--emit-wall-clock-min must be <= --emit-wall-clock-max")

    if ns.unlimited:
        if ns.max_events is not None:
            p.error("--unlimited cannot be used with --max-events")
        if ns.stream:
            if emit_min is None and ns.max_duration is None:
                p.error(
                    "--unlimited with --stream requires --emit-wall-clock-min/max "
                    "or --max-duration"
                )
        elif ns.max_duration is None:
            p.error("--unlimited without --stream requires --max-duration")


# Options that consume the next argv token as their value (same set argparse uses).
_OPTS_WITH_FOLLOWING_VALUE = frozenset({
    "-o",
    "--output",
    "-s",
    "--seed",
    "-c",
    "--calendar",
    "-d",
    "--days",
    "--from-date",
    "--to-date",
    "--scan-fraction",
    "--merch-factor",
    "-e",
    "--events",
    "-F",
    "--fans-out",
})


def _explicit_v1_rolling_flags_in_tokens(tokens: list[str]) -> bool:
    """
    True if -n / --count / -d / --days appear as rolling-window options.

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
        if t in ("-n", "--count", "--days", "-d"):
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
        epilog=EPILOG_ROOT,
    )
    sub = p.add_subparsers(dest="command", required=True, parser_class=ColoredArgumentParser)
    gen = sub.add_parser(
        SUBCOMMAND_EVENTS,
        help="Generate NDJSON to a file (v1 rolling or v2 calendar).",
        formatter_class=ColoredHelpFormatter,
        epilog=EPILOG_GENERATE_EVENTS,
    )
    gen.add_argument(
        "-o",
        "--output",
        default=DEFAULT_OUTPUT,
        help=f"Output NDJSON path (default: {DEFAULT_OUTPUT})",
    )
    gen.add_argument(
        "-s",
        "--seed",
        type=int,
        default=None,
        help=(
            "RNG seed for byte-identical reproducibility in v1/v2; v1 also fixes “now” when set "
            "(default: none — omit for non-deterministic v1/v2 output)"
        ),
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
        "-d",
        "--days",
        type=int,
        default=DEFAULT_DAYS,
        help=f"UTC rolling window length ending at generation time (default: {DEFAULT_DAYS})",
    )

    cal = gen.add_argument_group("Calendar (fan-events-ndjson-v2)")
    cal.add_argument(
        "-c",
        "--calendar",
        type=str,
        default=None,
        help=(
            "Path to calendar JSON (data-model.md); enables v2 output "
            "(default: none — omit for v1 rolling window)"
        ),
    )
    cal.add_argument(
        "--from-date",
        type=str,
        default=None,
        help=(
            "Inclusive lower bound on kickoff UTC date (YYYY-MM-DD) with --calendar "
            "(default: none — omit both --from-date and --to-date to include every match)"
        ),
    )
    cal.add_argument(
        "--to-date",
        type=str,
        default=None,
        help=(
            "Inclusive upper bound on kickoff UTC date (YYYY-MM-DD) with --calendar "
            "(default: none — omit both --from-date and --to-date to include every match)"
        ),
    )
    cal.add_argument(
        "--scan-fraction",
        type=float,
        default=None,
        help=(
            f"Fraction of capacity for ticket_scan volume when using --calendar "
            f"(default when omitted: {DEFAULT_SCAN_FRACTION})"
        ),
    )
    cal.add_argument(
        "--merch-factor",
        type=float,
        default=None,
        help=(
            f"Scale for merch_purchase event count vs capacity when using --calendar "
            f"(default when omitted: {DEFAULT_MERCH_FACTOR})"
        ),
    )

    gen.add_argument(
        "-e",
        "--events",
        choices=("both", TICKET_SCAN, MERCH_PURCHASE),
        default="both",
        help="Event types to emit (default: both)",
    )
    gen.add_argument(
        "-F",
        "--fans-out",
        type=str,
        default=None,
        metavar="PATH",
        help=(
            "Companion JSON path: synthetic fan master keyed by fan_id "
            "(join events.fan_id → fans[fan_id]; not part of NDJSON contracts). "
            f"Default when omitted: same path as -o/--output with a .json suffix "
            f"(e.g. {_companion_fans_json_path(DEFAULT_OUTPUT)})"
        ),
    )

    ret = sub.add_parser(
        SUBCOMMAND_RETAIL,
        help=(
            "Generate match-independent retail_purchase NDJSON (v3) to a file or stdout; "
            "optional wall-clock delays between stdout lines "
            "(--emit-wall-clock-min/max with --stream)."
        ),
        formatter_class=ColoredHelpFormatter,
        epilog=EPILOG_GENERATE_RETAIL,
    )
    ret.add_argument(
        "-o",
        "--output",
        default=DEFAULT_RETAIL_OUTPUT,
        help=f"Output NDJSON path when not using --stream (default: {DEFAULT_RETAIL_OUTPUT})",
    )
    ret.add_argument(
        "-s",
        "--seed",
        type=int,
        default=None,
        help=(
            "RNG seed for reproducible draws (batch, stream, wall-clock sleep intervals); "
            "(default: none — omit for non-deterministic output)"
        ),
    )
    ret.add_argument(
        "-t",
        "--stream",
        action="store_true",
        help=(
            "Write NDJSON to stdout in generation order (no global sort); ignores -o/--output "
            "(default: off — write a sorted batch file to -o). "
            "Without wall-clock emit flags, lines are written as fast as the CPU allows; "
            "with --emit-wall-clock-min/max, sleep a random interval in [min,max] seconds "
            "before each line after the first"
        ),
    )
    ret.add_argument(
        "-n",
        "--max-events",
        type=int,
        default=None,
        help=(
            "Stop after N events (0 → empty). Incompatible with --unlimited. "
            f"If omitted with no --max-duration and no --unlimited, implied cap is "
            f"{DEFAULT_RETAIL_IMPLIED_MAX_EVENTS} (same as v3 generator default)"
        ),
    )
    ret.add_argument(
        "-d",
        "--max-duration",
        type=float,
        default=None,
        dest="max_duration",
        metavar="SECONDS",
        help=(
            "Maximum simulated timeline length in seconds from epoch (timestamps in records) "
            "(default: none). With -n/--max-events, stop when either limit binds first. "
            "With --unlimited and file output, required to bound generation"
        ),
    )
    ret.add_argument(
        "-E",
        "--epoch",
        type=str,
        default=None,
        help=(
            "UTC start instant for the synthetic timeline (ISO-8601, e.g. "
            f"2026-01-01T00:00:00Z). Default when omitted: {_DEFAULT_RETAIL_EPOCH_HELP_STR}"
        ),
    )
    ret.add_argument(
        "--shop-weights",
        nargs=3,
        type=float,
        metavar=("W1", "W2", "W3"),
        default=None,
        help=(
            "Three non-negative weights for shops "
            "(order: jan_breydel_fan_shop, webshop, bruges_city_shop). "
            "Default when omitted: equal weight per shop (1/3 each)"
        ),
    )
    ret.add_argument(
        "--arrival-mode",
        choices=("poisson", "fixed", "weighted_gap"),
        default="poisson",
        help="Inter-arrival time model for synthetic timestamps (default: poisson)",
    )
    ret.add_argument(
        "--poisson-rate",
        type=float,
        default=DEFAULT_RETAIL_POISSON_RATE,
        help=(
            "Poisson rate (events per second) for expovariate gaps when --arrival-mode poisson "
            f"(default: {DEFAULT_RETAIL_POISSON_RATE})"
        ),
    )
    ret.add_argument(
        "--fixed-gap-seconds",
        type=float,
        default=DEFAULT_RETAIL_FIXED_GAP_SECONDS,
        help=(
            "Seconds between successive synthetic events when --arrival-mode fixed "
            f"(default: {DEFAULT_RETAIL_FIXED_GAP_SECONDS:g})"
        ),
    )
    ret.add_argument(
        "--weighted-gaps",
        nargs="+",
        type=float,
        default=None,
        metavar="SEC",
        help=(
            "Candidate gap lengths for --arrival-mode weighted_gap (default: none — requires "
            "--weighted-gap-weights)"
        ),
    )
    ret.add_argument(
        "--weighted-gap-weights",
        nargs="+",
        type=float,
        default=None,
        metavar="W",
        help=(
            "Weights for each --weighted-gaps value, same length (default: none — requires "
            "--weighted-gaps)"
        ),
    )
    ret.add_argument(
        "-p",
        "--fan-pool",
        type=int,
        default=None,
        metavar="N",
        help=(
            "Upper bound for fan_id numeric suffix pool (default when omitted: heuristic from "
            "implied event cap in v3 retail, typically up to 500)"
        ),
    )
    ret.add_argument(
        "--emit-wall-clock-min",
        type=float,
        default=None,
        metavar="SEC",
        dest="emit_wall_clock_min",
        help=(
            "Requires --stream. Lower bound (seconds) for random wall-clock sleep before each "
            "stdout line after the first; draw uses the same RNG as --seed "
            "(default: none — set with --emit-wall-clock-max). 0 <= min <= max"
        ),
    )
    ret.add_argument(
        "--emit-wall-clock-max",
        type=float,
        default=None,
        metavar="SEC",
        dest="emit_wall_clock_max",
        help=(
            "Requires --stream. Upper bound (seconds) for wall-clock sleep between lines "
            "(default: none — pair with --emit-wall-clock-min)"
        ),
    )
    ret.add_argument(
        "-u",
        "--unlimited",
        action="store_true",
        help=(
            f"Skip the implied --max-events {DEFAULT_RETAIL_IMPLIED_MAX_EVENTS} cap when both "
            "-n/--max-events and -d/--max-duration are omitted (run until Ctrl+C or until "
            "--max-duration ends the simulated timeline). Default: off. Incompatible with -n. "
            "With --stream, also requires wall-clock emit bounds and/or --max-duration so "
            "output cannot buffer forever"
        ),
    )
    ret.add_argument(
        "-F",
        "--fans-out",
        type=str,
        default=None,
        metavar="PATH",
        help=(
            "Companion JSON path: synthetic fan master keyed by fan_id "
            "(join events.fan_id → fans[fan_id]; not part of NDJSON contracts). "
            f"Default when omitted: same path as -o/--output with a .json suffix "
            f"(e.g. {_companion_fans_json_path(DEFAULT_RETAIL_OUTPUT)})"
        ),
    )

    ns = p.parse_args(argv)

    if ns.command == SUBCOMMAND_RETAIL:
        _validate_generate_retail(p, ns, argv)
        return ns

    raw = _tokens_for_flag_checks(argv)

    if ns.calendar:
        if _explicit_v1_rolling_flags_in_tokens(raw):
            p.error(
                "-n / --count / -d / --days cannot be used with --calendar (v2 calendar mode)"
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
    if args.fans_out:
        _write_fans_sidecar(Path(args.fans_out), {r["fan_id"] for r in records}, args.seed)


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
    if args.fans_out:
        _write_fans_sidecar(Path(args.fans_out), {r["fan_id"] for r in records}, args.seed)


def run_v3(args: argparse.Namespace) -> None:
    rng = random.Random(args.seed) if args.seed is not None else random.Random()
    kw = _retail_generator_kwargs(args)
    fan_ids: set[str] | None = set() if args.fans_out else None
    if args.stream:
        if args.emit_wall_clock_min is not None:
            first = True
            for line in iter_retail_ndjson_lines(rng, fan_ids=fan_ids, **kw):
                if not first:
                    time.sleep(
                        rng.uniform(args.emit_wall_clock_min, args.emit_wall_clock_max)
                    )
                sys.stdout.write(line)
                sys.stdout.flush()
                first = False
        else:
            if fan_ids is not None:
                for line in iter_retail_ndjson_lines(rng, fan_ids=fan_ids, **kw):
                    sys.stdout.write(line)
                    sys.stdout.flush()
            else:
                text = retail_stream_ndjson(rng, **kw)
                sys.stdout.write(text)
                sys.stdout.flush()
    else:
        records = generate_retail_batch(rng, **kw)
        text = records_to_ndjson_v3(records)
        write_atomic_text(Path(args.output), text)
        if fan_ids is not None:
            fan_ids.update(r["fan_id"] for r in records)
    if args.fans_out:
        assert fan_ids is not None
        _write_fans_sidecar(Path(args.fans_out), fan_ids, args.seed)


def main(argv: list[str] | None = None) -> None:
    try:
        args = parse_args(argv)
        if args.command in (SUBCOMMAND_EVENTS, SUBCOMMAND_RETAIL) and args.fans_out is None:
            args.fans_out = _companion_fans_json_path(args.output)
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
