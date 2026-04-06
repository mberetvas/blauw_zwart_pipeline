# Feature 004 — Research: unified orchestrated NDJSON stream

**Date**: 2026-04-06  
**Plan**: [plan.md](./plan.md)

## 1. Merge algorithm (streaming vs full sort)

**Decision**: Use **`heapq.merge`** (Python 3.12+) over **one iterator per sorted partition**, with a shared **merge key** matching [`contracts/orchestrated-stream.md`](./contracts/orchestrated-stream.md) (K1 timestamp, K2 `event`, K3 UTF-8 line bytes).

**Rationale**: `heapq.merge` is O(n) total with O(k) extra state for k streams; avoids loading all events into RAM.

**Alternatives considered**:
- **Materialize + `sorted(records)`** — rejected for large calendars / long retail runs (memory).
- **Single sorted iterator** — v2 is not globally sorted by current `generate_v2_records` (per-match batches in kickoff order); requires restructuring.

## 2. v2 iterator sortability

**Problem**: `generate_v2_records` returns a **flat list** of records in match iteration order; timestamps within a match are random in the window.

**Decision**:
  - **Per match**: produce records for that match (or reuse existing generator), then **sort** by `(timestamp, event, dumps_canonical(rec))` (or equivalent tuple) so each match yields a **sorted** iterator.
  - **Across matches**: merge all per-match sorted iterators with **`heapq.merge`** using the **same** merge key as the global contract.

**Precondition**: Each input iterator MUST yield records in **non-decreasing** merge-key order (strictly sorted by the tuple used for merge).

**Alternatives**: Pre-sort entire v2 list once — acceptable for moderate match counts but **not** streaming; prefer per-match lazy iterators for consistency with retail.

## 3. Retail iterator (`iter_retail_records`)

**Decision**: **Reuse as-is**; synthetic timestamps are strictly increasing by construction (positive gaps), so the global merge key order matches generation order.

**Rationale**: No change to v3 RNG semantics unless a test proves a tie on identical timestamps; if ties occur, **K2/K3** in contract resolve.

## 4. Unified `fan_id` population (FR-012)

**Problem**: v2 builds per-match pools from `fan_00001..fan_{capacity}`; v3 draws `fan_{rng.randint(1, pool):05d}` with a **pool** heuristic.

**Decision** (implementation direction):
  - Introduce a **shared `fan_pool_size`** (CLI flag or derived from `max(retail_fan_pool, v2_need)`).
  - Use **one** RNG stream discipline for fan assignment when both sources are active: **same** `fan_{i:05d}` namespace and **documented** allocation rules (plan: v2 continues to use pool subsets per match; retail draws from same ID space — tests must assert IDs stay within `fan_00001..fan_{pool}`).

**Rationale**: Meets spec coherence without a second “parallel universe” of IDs.

**Alternatives**: Independent pools — **rejected** by clarification **B**.

## 5. Global limits (`max_events`, `max_simulated_duration`)

**Decision**: Apply limits **after merge** on the unified iterator:
  - **max_events**: stop after N **emitted** NDJSON lines.
  - **max_simulated_duration**: define `t0` as **minimum** of (retail epoch, earliest v2 synthetic timestamp in the merged stream) **or** document `t0` = retail epoch when retail enabled; else earliest v2 event time — **stop before emitting** a line whose `timestamp` is **after** `t0 + duration` (parse ISO-8601 `Z`).

**Rationale**: Matches operator mental model (“simulated timeline”); align with `iter_retail_records` duration checks where retail-only.

**Alternatives**: Separate limits per source — **rejected** (spec says unified stream).

## 6. Unbounded default (spec clarification A)

**Decision**: If **no** `--max-events` and **no** `--max-duration`, run **until** KeyboardInterrupt, generator exhaustion, or error. **CLI help** and **epilog** must warn (disk/CPU).

**Note**: `iter_retail_records` applies an **implied** 200 cap by default — **stream** must pass **`skip_default_event_cap=True`** when spec requires unbounded retail side, or document that retail implied cap applies unless overridden — **align with spec** in implementation: **orchestrator** should mirror clarified spec (unbounded) by default; **explicit** flags to mirror retail defaults when desired.

**Resolution**: Plan **explicit** `--max-events` / `--max-duration` for `stream`; when omitted, **do not** apply retail’s implied 200 default (pass `skip_default_event_cap=True` or equivalent) **unless** product decides otherwise — **spec wins**: unbounded → **skip** implied cap.

## 7. Wall-clock pacing

**Decision**: After emitting each **merged** line (including first), optionally sleep **before** the next line using a **separate pacing RNG** derived from `--seed` (same pattern as `run_v3`).

**Rationale**: Parity with `generate_retail --stream --emit-wall-clock-*`.

## 8. Interrupt handling (FR-009)

**Decision**: **Document** in `quickstart.md` / help: on **Ctrl+C**, process exits; **no partial line** if each write is `line` + `flush()` for complete lines.

**Rationale**: Matches line-buffered writes.

## 9. Tie-break field name

**Decision**: Use JSON field **`event`** (matches `ndjson_io` and v2/v3 records). Contract updated from `event_type` → `event` for K2.

**Rationale**: Aligns code, validators, and NDJSON on disk.

## 10. `kcat` / documentation

**Decision**: Document both supported paths: default **stdout** output for piping to external tools such as `kcat`, and native Kafka output when the optional **`confluent-kafka`** extra is installed.

**Rationale**: Constitution VI still applies because the core/default install does **not** require a Kafka client dependency; native Kafka support is explicitly **optional** and opt-in via `pip install 'blauw-zwart-fan-sim-pipeline[kafka]'`, preserving a minimal baseline while allowing a justified integration extra for users who need direct Kafka publishing.
