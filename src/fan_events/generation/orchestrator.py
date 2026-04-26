"""Merge calendar-driven and retail-driven events into one NDJSON stream.

The orchestrator powers ``fan_events stream`` by interleaving already sorted v2
and v3 records, enforcing optional duration and event-count caps, and writing
LF-terminated NDJSON lines to a file or other text sink.
"""

from __future__ import annotations

import heapq
import random
import time
from collections.abc import Iterator
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, TextIO

from fan_events.core.domain import JAN_BREYDEL_MAX_CAPACITY, RETAIL_PURCHASE
from fan_events.io.merge_keys import merge_key_tuple, parse_timestamp_utc_z
from fan_events.io.ndjson_io import format_line_v2, format_line_v3


def compute_stream_t0(retail_epoch_utc: datetime, v2_contexts_pass0: list[Any]) -> datetime:
    """Compute the merged stream anchor used by ``--max-duration`` limits.

    Args:
        retail_epoch_utc: UTC epoch used by the retail generator.
        v2_contexts_pass0: Match contexts for the first calendar pass.

    Returns:
        Earliest UTC instant that should count as time zero for merged output.
    """
    re = retail_epoch_utc.astimezone(timezone.utc)
    if not v2_contexts_pass0:
        return re
    earliest_v2 = min(c.window_start for c in v2_contexts_pass0)
    return min(re, earliest_v2.astimezone(timezone.utc))


def default_unified_fan_pool_max(contexts: list[Any]) -> int:
    """Choose a shared fan-ID pool size for merged calendar and retail streams.

    Args:
        contexts: Match contexts that expose ``effective_cap`` estimates.

    Returns:
        Upper bound for ``fan_{i:05d}`` identifiers shared across generators.

    Note:
        The pool is intentionally padded beyond the biggest stadium capacity so
        merged simulations do not unrealistically reuse too few fan IDs.
    """
    if not contexts:
        return 500
    m = max(c.effective_cap for c in contexts)
    return min(JAN_BREYDEL_MAX_CAPACITY, max(500, m * 2))


def iter_merged_records(
    retail_iter: Iterator[dict[str, Any]],
    v2_iter: Iterator[dict[str, Any]],
) -> Iterator[dict[str, Any]]:
    """Merge two sorted record iterators into one globally ordered stream.

    Args:
        retail_iter: Iterator of retail records already sorted by
            :func:`fan_events.io.merge_keys.merge_key_tuple`.
        v2_iter: Iterator of v2 calendar records using the same ordering.

    Returns:
        Lazy iterator that yields records in merged key order.
    """
    return heapq.merge(retail_iter, v2_iter, key=merge_key_tuple)


def record_to_ndjson_line(rec: dict[str, Any]) -> str:
    """Serialize one merged record using its schema-specific formatter.

    Args:
        rec: Synthetic event record from either the v2 or v3 generator.

    Returns:
        LF-terminated canonical NDJSON line for the record.
    """
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
    """Write merged records to a text sink with optional pacing and cutoffs.

    Args:
        merged: Iterator of already merged record dictionaries.
        sink: Text sink that accepts LF-terminated NDJSON lines.
        max_events: Optional hard cap on the number of emitted lines.
        max_duration_seconds: Optional maximum simulated duration from the
            stream anchor.
        t0_anchor: Optional fixed UTC anchor for duration checks. When omitted,
            the first emitted record becomes the anchor.
        pacing_rng: Optional random generator used for wall-clock pacing.
        emit_wall_clock_min: Optional lower bound for inter-line sleep seconds.
        emit_wall_clock_max: Optional upper bound for inter-line sleep seconds.

    Returns:
        Number of NDJSON lines written to ``sink``.

    Note:
        When pacing bounds and ``pacing_rng`` are supplied, the function sleeps
        between emitted lines after the first to mimic streaming behavior.
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
        # Anchor the duration window once, either from the first record or from
        # the caller-supplied feature-006 stream start.
        if t_anchor is None:
            t_anchor = ts
        if max_duration_seconds is not None:
            dur_ref = t0_anchor if t0_anchor is not None else t_anchor
            if (ts - dur_ref).total_seconds() > max_duration_seconds:
                break
        # Optional pacing keeps file-backed streaming behavior aligned with the
        # retail generator's interactive ``--stream`` mode.
        if use_pacing and not first_line:
            time.sleep(pacing_rng.uniform(emit_wall_clock_min, emit_wall_clock_max))  # type: ignore[union-attr]
        # Serialize and flush each line immediately so downstream consumers can
        # tail the file in near-real time.
        line = record_to_ndjson_line(rec)
        sink.write(line)
        sink.flush()
        count += 1
        first_line = False
        if max_events is not None and count >= max_events:
            break
    return count


def open_append_sink(path: Path) -> TextIO:
    """Open a UTF-8 text sink suitable for appended NDJSON output.

    Args:
        path: Output path whose parent directories should exist.

    Returns:
        Text file handle opened for append with ``\n`` newlines.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    return path.open("a", encoding="utf-8", newline="\n")
