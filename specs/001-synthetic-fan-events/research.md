# Research: Synthetic fan event source

**Feature**: `001-synthetic-fan-events`  
**Date**: 2026-04-04

## R1 — Canonical JSON for byte-identical NDJSON

**Decision**: Use `json.dumps` with `sort_keys=True`, `separators=(",", ":")`, `ensure_ascii=False` so
Unicode in `location` / `item` is written as UTF-8 characters (not `\uXXXX` escapes), matching FR-004
UTF-8 on disk.

**Rationale**: Stable key order and minimal separators remove whitespace variance; `ensure_ascii=False`
avoids escape differences across identical strings.

**Alternatives considered**: `orjson` / `rapidjson` (rejected: third-party forbidden); default
`json.dumps` without `sort_keys` (rejected: unstable key order).

## R2 — Event-type tie-break (FR-007)

**Decision**: After primary sort on `timestamp`, break ties by **explicit enum order**: `ticket_scan`
then `merch_purchase` (not raw Unicode sort on the `event` string).

**Rationale**: Matches fan-journey intuition (entry before shop) and stays stable regardless of locale.

**Alternatives considered**: Lexical on `event` (merch before ticket alphabetically — rejected for demo
narrative).

## R3 — Total order when timestamp, event, and fan_id collide

**Decision**: Add deterministic tertiary keys: for `ticket_scan` use ascending `location`; for
`merch_purchase` use ascending `item`, then ascending `amount` (as decimal with two fractional digits in
generation logic).

**Rationale**: FR-007 requires a total order; synthetic data can still produce duplicates without these
keys.

## R4 — Atomic write (FR-008)

**Decision**: Write full content to a temporary file in the same directory as the target (or
`tempfile` + same-directory `os.replace`), then `os.replace(tmp, final)` so consumers never observe a
partial success file.

**Rationale**: Matches spec atomic-write guidance and Windows-safe replace semantics.

## R5 — RNG and reproducibility

**Decision**: With `--seed`, use `random.Random(seed)`. Without `--seed`, use `random.Random()` (no fixed
seed) so runs are **non-deterministic**; FR-005 applies only when seed and all other parameters match.

**Rationale**: User asked optional seed; explicit reproducibility when they opt in.

**Alternatives considered**: Default seed `0` (rejected: surprising); always require seed (rejected).

## R6 — Default parameters

**Decision**: `--days` default **90**; `--count` default **200** (must be ≥ 2 so default run can include
at least one of each type); split events roughly half/half with adjustment so both types appear; default
`--output` **`out/fan_events.ndjson`** (create parent directory if missing).

**Rationale**: Aligns with user input and FR-006 default demo includes both types.
