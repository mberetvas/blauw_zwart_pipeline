"""Merge v2 calendar + v3 retail into one NDJSON stream (``fan_events stream``)."""

from __future__ import annotations

import heapq
import random
import time
from collections.abc import Iterator
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, TextIO

from fan_events.domain import JAN_BREYDEL_MAX_CAPACITY, RETAIL_PURCHASE
from fan_events.merge_keys import merge_key_tuple, parse_timestamp_utc_z
from fan_events.ndjson_io import format_line_v2, format_line_v3


def compute_stream_t0(retail_epoch_utc: datetime, v2_contexts_pass0: list[Any]) -> datetime:
    """Anchor for merged ``--max-duration``: min(retail epoch, earliest v2 window start pass 0)."""
    re = retail_epoch_utc.astimezone(timezone.utc)
    if not v2_contexts_pass0:
        return re
    earliest_v2 = min(c.window_start for c in v2_contexts_pass0)
    return min(re, earliest_v2.astimezone(timezone.utc))


def default_unified_fan_pool_max(contexts: list[Any]) -> int:
    """Upper bound for shared ``fan_{i:05d}`` IDs when both v2 and retail are active."""
    if not contexts:
        return 500
    m = max(c.effective_cap for c in contexts)
    return min(JAN_BREYDEL_MAX_CAPACITY, max(500, m * 2))


def iter_merged_records(
    retail_iter: Iterator[dict[str, Any]],
    v2_iter: Iterator[dict[str, Any]],
) -> Iterator[dict[str, Any]]:
    """Merge two **sorted** iterators by ``merge_key_tuple`` (``heapq.merge``)."""
    return heapq.merge(retail_iter, v2_iter, key=merge_key_tuple)


def record_to_ndjson_line(rec: dict[str, Any]) -> str:
    if rec.get("event") == RETAIL_PURCHASE:
        return format_line_v3(rec)
    return format_line_v2(rec)


def write_merged_stream(
    merged: Iterator[dict[str, Any]],
    sink: TextIO,
    *,
    max_events: int | None = None,
    max_duration_seconds: float | None = None,
    t0_anchor: datetime | None = None,
    pacing_rng: random.Random | None = None,
    emit_wall_clock_min: float | None = None,
    emit_wall_clock_max: float | None = None,
) -> int:
    """
    Write LF-terminated NDJSON lines; return number of lines written.

    ``max_duration_seconds``: if ``t0_anchor`` is set (006), span from that fixed UTC instant;
    otherwise legacy anchor is the **first emitted** timestamp.

    Pacing: if min/max set, sleep between lines (after first) like ``generate_retail --stream``.
    """
    if max_events == 0:
        return 0
    count = 0
    t_anchor: datetime | None = None
    first_line = True
    use_pacing = (
        pacing_rng is not None
        and emit_wall_clock_min is not None
        and emit_wall_clock_max is not None
    )
    for rec in merged:
        ts = parse_timestamp_utc_z(str(rec["timestamp"]))
        if t_anchor is None:
            t_anchor = ts
        if max_duration_seconds is not None:
            dur_ref = t0_anchor if t0_anchor is not None else t_anchor
            if (ts - dur_ref).total_seconds() > max_duration_seconds:
                break
        if use_pacing and not first_line:
            time.sleep(pacing_rng.uniform(emit_wall_clock_min, emit_wall_clock_max))  # type: ignore[union-attr]
        line = record_to_ndjson_line(rec)
        sink.write(line)
        sink.flush()
        count += 1
        first_line = False
        if max_events is not None and count >= max_events:
            break
    return count


def open_append_sink(path: Path) -> TextIO:
    path.parent.mkdir(parents=True, exist_ok=True)
    return path.open("a", encoding="utf-8", newline="\n")
