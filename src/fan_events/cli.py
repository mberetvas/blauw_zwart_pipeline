"""
Synthetic fan events NDJSON generator (stdlib only).

Normative contracts:
  specs/001-synthetic-fan-events/contracts/fan-events-ndjson-v1.md  (rolling mode)
  specs/002-match-calendar-events/contracts/fan-events-ndjson-v2.md  (--calendar mode)
  specs/003-ndjson-v3-retail-sim/contracts/fan-events-ndjson-v3.md  (generate_retail)
  specs/004-unified-synthetic-stream/contracts/cli-stream.md  (stream)
"""

from __future__ import annotations

import argparse
import logging
import os
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
from fan_events.orchestrator import (
    default_unified_fan_pool_max,
    iter_merged_records,
    open_append_sink,
    write_merged_stream,
)
from fan_events.term_style import ColoredArgumentParser, ColoredHelpFormatter
from fan_events.v1_batch import FIXED_NOW_UTC, generate_batch
from fan_events.v2_calendar import (
    CalendarError,
    filter_matches_by_date_range,
    generate_v2_records,
    iter_v2_records_merged_sorted,
    load_calendar_json,
    validate_and_parse_matches,
)
from fan_events.v3_retail import (
    generate_retail_batch,
    iter_retail_ndjson_lines,
    iter_retail_records,
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
SUBCOMMAND_STREAM = "stream"

# Copy-paste examples (flags/paths align with README). Epilog is styled by ColoredHelpFormatter.
_HELP_DEV_NOTE = (
    "Without install, prefix with uv run or uv run python -m fan_events (same arguments).\n\n"
)

_EX_HELP_ROOT = "fan_events --help"
_EX_HELP_EVENTS = "fan_events generate_events --help"
_EX_HELP_RETAIL = "fan_events generate_retail --help"
_EX_HELP_STREAM = "fan_events stream --help"
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
_EX_STREAM_MERGED = (
    "fan_events stream -c my_calendar.json -s 42 -o out/mixed.ndjson "
    "--retail-max-events 500 --max-events 1000"
)
_EX_STREAM_RETAIL_ONLY = "fan_events stream -s 1 --retail-max-events 10"

EPILOG_ROOT = (
    _HELP_DEV_NOTE
    + "Examples:\n\n"
    + "\n".join(
        (
            _EX_HELP_ROOT,
            _EX_HELP_EVENTS,
            _EX_HELP_RETAIL,
            _EX_HELP_STREAM,
            "",
            _EX_V1_ROLLING,
            _EX_V2_CAL_ALL,
            _EX_V2_DATE_RANGE,
            "",
            _EX_V3_FILE,
            _EX_V3_STREAM,
            "",
            _EX_STREAM_MERGED,
            _EX_STREAM_RETAIL_ONLY,
        )
    )
    + "\n"
)

_EX_KAFKA_ENV = (
    "FAN_EVENTS_KAFKA_BOOTSTRAP_SERVERS=localhost:9092 "
    "FAN_EVENTS_KAFKA_TOPIC=fan-events "
    "fan_events stream -s 42 --retail-max-events 100 --max-events 50"
)
_EX_KAFKA_FLAGS = (
    "fan_events stream --kafka-topic fan-events "
    "--kafka-bootstrap-servers localhost:9092 --max-events 50"
)

EPILOG_STREAM = (
    "Without --max-events or --max-duration the stream runs until Ctrl+C or exhaustion.\n"
    "Start a local Kafka broker: just kafka\n\n"
    "Examples:\n\n"
    + "\n".join(
        (
            _EX_HELP_STREAM,
            _EX_STREAM_MERGED,
            "fan_events stream -c cal.json --no-retail -s 42",
            _EX_STREAM_RETAIL_ONLY,
            "",
            "# Kafka via env vars:",
            _EX_KAFKA_ENV,
            "# Kafka via CLI flags:",
            _EX_KAFKA_FLAGS,
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
    if ns.fan_pool is not None and ns.fan_pool < 1:
        p.error("--fan-pool must be >= 1")
    if ns.arrival_mode == "poisson" and ns.poisson_rate <= 0:
        p.error("--poisson-rate must be > 0")
    if ns.arrival_mode == "fixed" and ns.fixed_gap_seconds <= 0:
        p.error("--fixed-gap-seconds must be > 0")
    if ns.arrival_mode == "weighted_gap":
        if not ns.weighted_gaps or not ns.weighted_gap_weights:
            p.error("weighted_gap requires --weighted-gaps and --weighted-gap-weights")
        if len(ns.weighted_gaps) != len(ns.weighted_gap_weights):
            p.error("--weighted-gaps and --weighted-gap-weights must have the same length")
        if any(gap < 0 for gap in ns.weighted_gaps):
            p.error("--weighted-gaps values must be >= 0")
        if any(weight < 0 for weight in ns.weighted_gap_weights):
            p.error("--weighted-gap-weights values must be >= 0")
        if sum(ns.weighted_gap_weights) <= 0:
            p.error("--weighted-gap-weights must have a positive total weight")

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


def _stream_retail_kwargs(ns: argparse.Namespace) -> dict[str, object]:
    """Kwargs for ``iter_retail_records`` on ``stream``.

    Retail-internal caps use separate argparse destinations from post-merge limits.
    """
    kw: dict[str, object] = {}
    if ns.epoch is not None:
        kw["epoch_utc"] = _parse_epoch_utc(ns.epoch)
    if ns.shop_weights is not None:
        kw["shop_weights"] = tuple(ns.shop_weights)
    kw["max_events"] = ns.retail_max_events
    kw["max_simulated_duration_seconds"] = ns.retail_max_duration
    kw["arrival_mode"] = ns.arrival_mode
    kw["poisson_rate"] = ns.poisson_rate
    kw["fixed_gap_seconds"] = ns.fixed_gap_seconds
    if ns.arrival_mode == "weighted_gap":
        kw["weighted_gaps"] = ns.weighted_gaps
        kw["weighted_gap_weights"] = ns.weighted_gap_weights
    kw["skip_default_event_cap"] = (
        ns.retail_max_events is None and ns.retail_max_duration is None
    )
    return kw


def _validate_stream(
    p: argparse.ArgumentParser,
    ns: argparse.Namespace,
    argv: list[str] | None,
) -> None:
    if ns.no_retail and not ns.calendar:
        p.error("--no-retail requires --calendar (calendar-only mode)")
    tok = _tokens_after_subcommand(argv, SUBCOMMAND_STREAM)
    if _explicit_v1_rolling_flags_in_tokens(tok):
        p.error(
            "-n / --count / -d / --days (rolling window) are not valid on stream "
            "(v1 rolling is out of scope; use --retail-max-events / "
            "--retail-max-duration for retail)"
        )
    if ns.calendar:
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

    if ns.retail_max_events is not None and ns.retail_max_events < 0:
        p.error("--retail-max-events must be >= 0")
    if ns.retail_max_duration is not None and ns.retail_max_duration <= 0:
        p.error("--retail-max-duration must be > 0")
    if ns.max_events is not None and ns.max_events < 0:
        p.error("--max-events must be >= 0")
    if ns.max_duration is not None and ns.max_duration <= 0:
        p.error("--max-duration must be > 0")

    if ns.epoch is not None:
        _parse_epoch_utc(ns.epoch)
    if ns.fan_pool is not None and ns.fan_pool < 1:
        p.error("--fan-pool must be >= 1")
    if ns.arrival_mode == "poisson" and ns.poisson_rate <= 0:
        p.error("--poisson-rate must be > 0")
    if ns.arrival_mode == "fixed" and ns.fixed_gap_seconds <= 0:
        p.error("--fixed-gap-seconds must be > 0")
    if ns.arrival_mode == "weighted_gap":
        if not ns.weighted_gaps or not ns.weighted_gap_weights:
            p.error("weighted_gap requires --weighted-gaps and --weighted-gap-weights")
        if len(ns.weighted_gaps) != len(ns.weighted_gap_weights):
            p.error("--weighted-gaps and --weighted-gap-weights must have the same length")
        if any(gap < 0 for gap in ns.weighted_gaps):
            p.error("--weighted-gaps values must be >= 0")
        if any(weight < 0 for weight in ns.weighted_gap_weights):
            p.error("--weighted-gap-weights values must be >= 0")
        if sum(ns.weighted_gap_weights) <= 0:
            p.error("--weighted-gap-weights must have a positive total weight")

    emit_min = ns.emit_wall_clock_min
    emit_max = ns.emit_wall_clock_max
    if (emit_min is None) != (emit_max is None):
        p.error("--emit-wall-clock-min and --emit-wall-clock-max must be given together")
    if emit_min is not None and (emit_min < 0 or emit_max < 0):
        p.error("--emit-wall-clock-min/max must be >= 0")
    if emit_min is not None and emit_min > emit_max:
        p.error("--emit-wall-clock-min must be <= --emit-wall-clock-max")

    _validate_stream_kafka(p, ns)


def _validate_stream_kafka(p: argparse.ArgumentParser, ns: argparse.Namespace) -> None:
    """Validate Kafka-specific stream flags."""
    kafka_only_flags = {
        "--kafka-bootstrap-servers": ns.kafka_bootstrap_servers,
        "--kafka-client-id": ns.kafka_client_id,
        "--kafka-compression": ns.kafka_compression,
        "--kafka-acks": ns.kafka_acks,
    }
    stray = [name for name, val in kafka_only_flags.items() if val is not None]
    if stray and ns.kafka_topic is None:
        p.error(f"{', '.join(stray)} require --kafka-topic")
    if ns.kafka_topic is not None and ns.output is not None:
        p.error("--kafka-topic and -o / --output are mutually exclusive")


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
    "--kafka-topic",
    "--kafka-bootstrap-servers",
    "--kafka-client-id",
    "--kafka-compression",
    "--kafka-acks",
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
            "(v1 rolling, v2 calendar, v3 retail batch/stream, or unified stream)."
        ),
        formatter_class=ColoredHelpFormatter,
        epilog=EPILOG_ROOT,
    )
    sub = p.add_subparsers(dest="command", required=True, parser_class=ColoredArgumentParser)
    gen = sub.add_parser(
        SUBCOMMAND_EVENTS,
        help="Write v1 (rolling) or v2 (calendar) fan events to a file.",
        formatter_class=ColoredHelpFormatter,
        epilog=EPILOG_GENERATE_EVENTS,
    )
    gen.add_argument(
        "-o",
        "--output",
        default=DEFAULT_OUTPUT,
        help=f"Output NDJSON file path (default: {DEFAULT_OUTPUT})",
    )
    gen.add_argument(
        "-s",
        "--seed",
        type=int,
        default=None,
        help=(
            "RNG seed for reproducible output (default: random)"
        ),
    )

    rolling = gen.add_argument_group("Rolling window (v1)")
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
        help=f"Window length in days ending at generation time (default: {DEFAULT_DAYS})",
    )

    cal = gen.add_argument_group("Calendar (v2, requires --calendar)")
    cal.add_argument(
        "-c",
        "--calendar",
        type=str,
        default=None,
        help=(
            "Path to match calendar JSON; enables v2 output"
        ),
    )
    cal.add_argument(
        "--from-date",
        type=str,
        default=None,
        help=(
            "Earliest match date to include, YYYY-MM-DD (omit to include all)"
        ),
    )
    cal.add_argument(
        "--to-date",
        type=str,
        default=None,
        help=(
            "Latest match date to include, YYYY-MM-DD (omit to include all)"
        ),
    )
    cal.add_argument(
        "--scan-fraction",
        type=float,
        default=None,
        help=(
            f"Ticket scan volume as fraction of stadium capacity (default: {DEFAULT_SCAN_FRACTION})"
        ),
    )
    cal.add_argument(
        "--merch-factor",
        type=float,
        default=None,
        help=(
            f"Merch purchase count scale relative to capacity (default: {DEFAULT_MERCH_FACTOR})"
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
            f"Write synthetic fan profiles to this JSON file "
            f"(default: same path as --output with .json, e.g. {_companion_fans_json_path(DEFAULT_OUTPUT)})"
        ),
    )

    ret = sub.add_parser(
        SUBCOMMAND_RETAIL,
        help="Write v3 retail purchase events to a file or stream to stdout.",
        formatter_class=ColoredHelpFormatter,
        epilog=EPILOG_GENERATE_RETAIL,
    )
    ret.add_argument(
        "-o",
        "--output",
        default=DEFAULT_RETAIL_OUTPUT,
        help=f"Output NDJSON file path (default: {DEFAULT_RETAIL_OUTPUT})",
    )
    ret.add_argument(
        "-s",
        "--seed",
        type=int,
        default=None,
        help=(
            "RNG seed for reproducible output (default: random)"
        ),
    )
    ret.add_argument(
        "-t",
        "--stream",
        action="store_true",
        help=(
            "Stream NDJSON to stdout instead of writing to a file (default: off)"
        ),
    )
    ret.add_argument(
        "-n",
        "--max-events",
        type=int,
        default=None,
        help=(
            "Stop after N events; 0 = empty (default: 200 when no other limits set)"
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
            "Stop after N simulated seconds from epoch (default: none)"
        ),
    )
    ret.add_argument(
        "-E",
        "--epoch",
        type=str,
        default=None,
        help=(
            f"Start of simulated timeline, ISO-8601 UTC (default: {_DEFAULT_RETAIL_EPOCH_HELP_STR})"
        ),
    )
    ret.add_argument(
        "--shop-weights",
        nargs=3,
        type=float,
        metavar=("W1", "W2", "W3"),
        default=None,
        help=(
            "Relative weights for 3 shops: jan_breydel_fan_shop, webshop, bruges_city_shop (default: equal)"
        ),
    )
    ret.add_argument(
        "--arrival-mode",
        choices=("poisson", "fixed", "weighted_gap"),
        default="poisson",
        help="Time model between events: poisson, fixed, or weighted_gap (default: poisson)",
    )
    ret.add_argument(
        "--poisson-rate",
        type=float,
        default=DEFAULT_RETAIL_POISSON_RATE,
        help=(
            f"Arrival rate in events/second for poisson mode (default: {DEFAULT_RETAIL_POISSON_RATE})"
        ),
    )
    ret.add_argument(
        "--fixed-gap-seconds",
        type=float,
        default=DEFAULT_RETAIL_FIXED_GAP_SECONDS,
        help=(
            f"Gap in seconds between events for fixed mode (default: {DEFAULT_RETAIL_FIXED_GAP_SECONDS:g})"
        ),
    )
    ret.add_argument(
        "--weighted-gaps",
        nargs="+",
        type=float,
        default=None,
        metavar="SEC",
        help=(
            "Gap lengths in seconds for weighted_gap mode (requires --weighted-gap-weights)"
        ),
    )
    ret.add_argument(
        "--weighted-gap-weights",
        nargs="+",
        type=float,
        default=None,
        metavar="W",
        help=(
            "Probability weights for each --weighted-gaps value (same length)"
        ),
    )
    ret.add_argument(
        "-p",
        "--fan-pool",
        type=int,
        default=None,
        metavar="N",
        help=(
            "Max fan ID pool size (default: auto)"
        ),
    )
    ret.add_argument(
        "--emit-wall-clock-min",
        type=float,
        default=None,
        metavar="SEC",
        dest="emit_wall_clock_min",
        help=(
            "Min sleep in seconds between stdout lines; requires --stream and --emit-wall-clock-max"
        ),
    )
    ret.add_argument(
        "--emit-wall-clock-max",
        type=float,
        default=None,
        metavar="SEC",
        dest="emit_wall_clock_max",
        help=(
            "Max sleep in seconds between stdout lines; requires --stream and --emit-wall-clock-min"
        ),
    )
    ret.add_argument(
        "-u",
        "--unlimited",
        action="store_true",
        help=(
            f"Remove the default {DEFAULT_RETAIL_IMPLIED_MAX_EVENTS}-event cap; requires --max-duration or emit bounds with --stream"
        ),
    )
    ret.add_argument(
        "-F",
        "--fans-out",
        type=str,
        default=None,
        metavar="PATH",
        help=(
            f"Write synthetic fan profiles to this JSON file "
            f"(default: same path as --output with .json, e.g. {_companion_fans_json_path(DEFAULT_RETAIL_OUTPUT)})"
        ),
    )

    st = sub.add_parser(
        SUBCOMMAND_STREAM,
        help="Stream v2 match events and/or v3 retail as merged NDJSON sorted by time.",
        formatter_class=ColoredHelpFormatter,
        epilog=EPILOG_STREAM,
    )
    st.add_argument(
        "-o",
        "--output",
        type=str,
        default=None,
        metavar="PATH",
        help=(
            "Append output to this file; omit or use '-' for stdout (default: stdout)"
        ),
    )
    st.add_argument(
        "-s",
        "--seed",
        type=int,
        default=None,
        help=(
            "RNG seed for reproducible output (default: random)"
        ),
    )
    st.add_argument(
        "--no-retail",
        action="store_true",
        help="Only emit v2 match events, skip retail (requires --calendar)",
    )
    cal_s = st.add_argument_group("Calendar (fan-events-ndjson-v2), optional")
    cal_s.add_argument(
        "-c",
        "--calendar",
        type=str,
        default=None,
        help="Path to match calendar JSON; enables v2 events in the stream",
    )
    cal_s.add_argument(
        "--from-date",
        type=str,
        default=None,
        help="Earliest match date to include, YYYY-MM-DD (requires --calendar)",
    )
    cal_s.add_argument(
        "--to-date",
        type=str,
        default=None,
        help="Latest match date to include, YYYY-MM-DD (requires --calendar)",
    )
    cal_s.add_argument(
        "--scan-fraction",
        type=float,
        default=None,
        help=(
            f"Ticket scan volume as fraction of stadium capacity (default: {DEFAULT_SCAN_FRACTION})"
        ),
    )
    cal_s.add_argument(
        "--merch-factor",
        type=float,
        default=None,
        help=(
            f"Merch purchase count scale relative to capacity (default: {DEFAULT_MERCH_FACTOR})"
        ),
    )
    cal_s.add_argument(
        "-e",
        "--events",
        choices=("both", TICKET_SCAN, MERCH_PURCHASE),
        default="both",
        help="Event types for v2 calendar side (default: both)",
    )
    lim = st.add_argument_group("Post-merge limits (merged NDJSON line stream)")
    lim.add_argument(
        "--max-events",
        type=int,
        default=None,
        metavar="N",
        help=(
            "Stop after N merged output lines (default: none)"
        ),
    )
    lim.add_argument(
        "--max-duration",
        type=float,
        default=None,
        metavar="SECONDS",
        dest="max_duration",
        help=(
            "Stop after N simulated seconds from the first event (default: none)"
        ),
    )
    rlim = st.add_argument_group("Retail-only iterator limits (v3, before merge)")
    rlim.add_argument(
        "--retail-max-events",
        type=int,
        default=None,
        metavar="N",
        dest="retail_max_events",
        help=(
            "Cap retail events before merging (default: none)"
        ),
    )
    rlim.add_argument(
        "--retail-max-duration",
        type=float,
        default=None,
        metavar="SECONDS",
        dest="retail_max_duration",
        help="Max simulated retail timeline in seconds (default: none)",
    )
    st.add_argument(
        "-E",
        "--epoch",
        type=str,
        default=None,
        help=(
            f"Start of retail synthetic timeline, ISO-8601 UTC (default: {_DEFAULT_RETAIL_EPOCH_HELP_STR})"
        ),
    )
    st.add_argument(
        "--shop-weights",
        nargs=3,
        type=float,
        metavar=("W1", "W2", "W3"),
        default=None,
        help="Weights for 3 retail shops: jan_breydel_fan_shop, webshop, bruges_city_shop (default: equal)",
    )
    st.add_argument(
        "--arrival-mode",
        choices=("poisson", "fixed", "weighted_gap"),
        default="poisson",
        help="Time model between retail events: poisson, fixed, or weighted_gap (default: poisson)",
    )
    st.add_argument(
        "--poisson-rate",
        type=float,
        default=DEFAULT_RETAIL_POISSON_RATE,
        help=f"Arrival rate in events/second for poisson mode (default: {DEFAULT_RETAIL_POISSON_RATE})",
    )
    st.add_argument(
        "--fixed-gap-seconds",
        type=float,
        default=DEFAULT_RETAIL_FIXED_GAP_SECONDS,
        help=(
            f"Gap in seconds between retail events for fixed mode (default: {DEFAULT_RETAIL_FIXED_GAP_SECONDS:g})"
        ),
    )
    st.add_argument(
        "--weighted-gaps",
        nargs="+",
        type=float,
        default=None,
        metavar="SEC",
        help="Gap lengths in seconds for weighted_gap mode (requires --weighted-gap-weights)",
    )
    st.add_argument(
        "--weighted-gap-weights",
        nargs="+",
        type=float,
        default=None,
        metavar="W",
        help="Probability weights for each --weighted-gaps value (same length)",
    )
    st.add_argument(
        "-p",
        "--fan-pool",
        type=int,
        default=None,
        metavar="N",
        help=(
            "Max fan ID pool size; shared between v2 and v3 when both active (default: auto)"
        ),
    )
    st.add_argument(
        "--emit-wall-clock-min",
        type=float,
        default=None,
        metavar="SEC",
        dest="emit_wall_clock_min",
        help=(
            "Min sleep in seconds between output lines (requires --emit-wall-clock-max)"
        ),
    )
    st.add_argument(
        "--emit-wall-clock-max",
        type=float,
        default=None,
        metavar="SEC",
        dest="emit_wall_clock_max",
        help="Max sleep in seconds between output lines (requires --emit-wall-clock-min)",
    )
    kafka_g = st.add_argument_group(
        "Kafka output (mutually exclusive with -o / --output)",
        description=(
            "Publish to a Kafka topic instead of stdout or a file. "
            "Configure via FAN_EVENTS_KAFKA_* env vars or CLI flags. "
            "Start a local broker: just kafka"
        ),
    )
    kafka_g.add_argument(
        "--kafka-topic",
        type=str,
        default=os.environ.get("FAN_EVENTS_KAFKA_TOPIC"),
        metavar="TOPIC",
        dest="kafka_topic",
        help=(
            "Kafka topic to publish to; enables Kafka mode (env: FAN_EVENTS_KAFKA_TOPIC)"
        ),
    )
    kafka_g.add_argument(
        "--kafka-bootstrap-servers",
        type=str,
        default=None,
        metavar="SERVERS",
        dest="kafka_bootstrap_servers",
        help=(
            "Broker addresses, e.g. localhost:9092 (env: FAN_EVENTS_KAFKA_BOOTSTRAP_SERVERS)"
        ),
    )
    kafka_g.add_argument(
        "--kafka-client-id",
        type=str,
        default=None,
        metavar="ID",
        dest="kafka_client_id",
        help=(
            "Producer client ID (env: FAN_EVENTS_KAFKA_CLIENT_ID, default: fan-events-producer)"
        ),
    )
    kafka_g.add_argument(
        "--kafka-compression",
        choices=("none", "gzip", "snappy", "lz4", "zstd"),
        default=None,
        dest="kafka_compression",
        help=(
            "Message compression codec (env: FAN_EVENTS_KAFKA_COMPRESSION, default: none)"
        ),
    )
    kafka_g.add_argument(
        "--kafka-acks",
        type=str,
        default=None,
        metavar="ACKS",
        dest="kafka_acks",
        help=(
            "Required broker acks: 0, 1, or all/-1 (env: FAN_EVENTS_KAFKA_ACKS, default: 1)"
        ),
    )
    st.add_argument(
        "--verbose",
        action="store_true",
        default=False,
        dest="verbose",
        help="Raise Kafka logger to DEBUG for verbose broker diagnostics on stderr",
    )

    ns = p.parse_args(argv)

    if ns.command == SUBCOMMAND_STREAM:
        _validate_stream(p, ns, argv)
        return ns

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
    pacing_rng = (
        random.Random(f"pacing:{args.seed}") if args.seed is not None else random.Random()
    )
    kw = _retail_generator_kwargs(args)
    fan_ids: set[str] | None = set() if args.fans_out else None
    if args.stream:
        if args.emit_wall_clock_min is not None:
            first = True
            for line in iter_retail_ndjson_lines(rng, fan_ids=fan_ids, **kw):
                if not first:
                    time.sleep(
                        pacing_rng.uniform(args.emit_wall_clock_min, args.emit_wall_clock_max)
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


def run_stream(args: argparse.Namespace) -> None:
    rng = random.Random(args.seed) if args.seed is not None else random.Random()
    pacing_rng = (
        random.Random(f"pacing:{args.seed}") if args.seed is not None else random.Random()
    )

    contexts = []
    if args.calendar:
        path = Path(args.calendar)
        doc = load_calendar_json(path)
        rows = validate_and_parse_matches(doc)
        from_d = _parse_iso_date(args.from_date) if args.from_date is not None else None
        to_d = _parse_iso_date(args.to_date) if args.to_date is not None else None
        contexts = filter_matches_by_date_range(rows, from_d, to_d)

    include_v2 = args.calendar is not None
    include_retail = args.calendar is None or not args.no_retail

    unified: int | None = None
    if include_v2 and include_retail:
        unified = (
            args.fan_pool
            if args.fan_pool is not None
            else default_unified_fan_pool_max(contexts)
        )

    sf = DEFAULT_SCAN_FRACTION if args.scan_fraction is None else args.scan_fraction
    mf = DEFAULT_MERCH_FACTOR if args.merch_factor is None else args.merch_factor
    events_mode = args.events

    if include_v2:
        v2_iter = iter_v2_records_merged_sorted(
            contexts,
            rng,
            scan_fraction=sf,
            merch_factor=mf,
            events_mode=events_mode,
            fan_pool_max=unified,
        )
    else:
        v2_iter = iter(())

    retail_kw = _stream_retail_kwargs(args)
    if include_retail and include_v2:
        retail_kw["fan_pool"] = unified
    elif include_retail and args.fan_pool is not None:
        retail_kw["fan_pool"] = args.fan_pool

    retail_iter = iter_retail_records(rng, **retail_kw) if include_retail else iter(())

    merged = iter_merged_records(retail_iter, v2_iter)

    emit_min = args.emit_wall_clock_min
    emit_max = args.emit_wall_clock_max
    use_pacing = emit_min is not None and emit_max is not None
    prng = pacing_rng if use_pacing else None
    emin = emit_min if use_pacing else None
    emax = emit_max if use_pacing else None

    out = args.output
    if args.kafka_topic is not None:
        _run_stream_kafka(args, merged, prng, emin, emax)
    elif out is None or out == "-":
        write_merged_stream(
            merged,
            sys.stdout,
            max_events=args.max_events,
            max_duration_seconds=args.max_duration,
            pacing_rng=prng,
            emit_wall_clock_min=emin,
            emit_wall_clock_max=emax,
        )
    else:
        with open_append_sink(Path(out)) as sink:
            write_merged_stream(
                merged,
                sink,
                max_events=args.max_events,
                max_duration_seconds=args.max_duration,
                pacing_rng=prng,
                emit_wall_clock_min=emin,
                emit_wall_clock_max=emax,
            )


def _configure_kafka_observability(verbose: bool = False) -> None:
    """Attach a stderr handler to the ``fan_events.kafka`` logger.

    Called once when entering Kafka mode so non-Kafka subcommands are unaffected.
    The level is resolved as: ``--verbose`` → DEBUG, else ``FAN_EVENTS_LOG_LEVEL`` /
    ``LOGLEVEL`` env var, else INFO.
    """
    kafka_logger = logging.getLogger("fan_events.kafka")

    if verbose:
        level = logging.DEBUG
    else:
        env_level = os.environ.get("FAN_EVENTS_LOG_LEVEL") or os.environ.get("LOGLEVEL")
        if env_level:
            level = getattr(logging, env_level.upper(), logging.INFO)
        else:
            level = logging.INFO

    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter("%(levelname)s %(name)s: %(message)s"))
    kafka_logger.addHandler(handler)
    kafka_logger.setLevel(level)
    kafka_logger.propagate = False


def _run_stream_kafka(
    args: argparse.Namespace,
    merged: object,
    prng: random.Random | None,
    emin: float | None,
    emax: float | None,
) -> None:
    """Publish the merged stream to Kafka (called from run_stream when --kafka-topic is set)."""
    try:
        from confluent_kafka import Producer
    except ImportError:
        print(
            "fan_events: confluent-kafka is not installed. "
            "Enable the kafka extra:\n"
            "  uv sync --extra kafka          (local dev)\n"
            "  pip install 'blauw-zwart-fan-sim-pipeline[kafka]'  (installed package)",
            file=sys.stderr,
        )
        sys.exit(1)

    from fan_events.kafka_sink import (
        KafkaSink,
        build_producer_config,
        kafka_config_from_env,
        summarize_bootstrap_for_log,
    )

    _configure_kafka_observability(verbose=getattr(args, "verbose", False))
    kafka_logger = logging.getLogger("fan_events.kafka")

    cfg = kafka_config_from_env({
        "topic": args.kafka_topic,
        "bootstrap_servers": args.kafka_bootstrap_servers,
        "client_id": args.kafka_client_id,
        "compression": args.kafka_compression,
        "acks": args.kafka_acks,
    })

    kafka_logger.info(
        "Kafka mode — topic=%s  client_id=%s  bootstrap=%s",
        cfg.topic,
        cfg.client_id,
        summarize_bootstrap_for_log(cfg.bootstrap_servers),
    )
    kafka_logger.debug("Full bootstrap servers: %s", cfg.bootstrap_servers)

    producer = Producer(build_producer_config(cfg))
    sink = KafkaSink(producer, cfg.topic)
    try:
        write_merged_stream(
            merged,  # type: ignore[arg-type]
            sink,  # type: ignore[arg-type]
            max_events=args.max_events,
            max_duration_seconds=args.max_duration,
            pacing_rng=prng,
            emit_wall_clock_min=emin,
            emit_wall_clock_max=emax,
        )
    finally:
        # Always flush in-flight messages: normal completion and Ctrl+C alike.
        # KeyboardInterrupt re-propagates after finally; main() handles exit code 130.
        sink.close()


def main(argv: list[str] | None = None) -> None:
    try:
        args = parse_args(argv)
        if args.command == SUBCOMMAND_RETAIL:
            run_v3(args)
        elif args.command == SUBCOMMAND_STREAM:
            run_stream(args)
        elif args.calendar:
            run_v2(args)
        else:
            run_v1(args)
    except SystemExit:
        raise
    except KeyboardInterrupt:
        sys.exit(130)
    except CalendarError as e:
        print(f"fan_events: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"fan_events: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
