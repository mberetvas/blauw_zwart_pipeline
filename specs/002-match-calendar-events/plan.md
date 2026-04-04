# Implementation Plan: Match-calendar synthetic fan events

**Branch**: `002-match-calendar-events` | **Date**: 2026-04-04 | **Spec**: [`spec.md`](spec.md)  
**Input**: Feature specification from `/specs/002-match-calendar-events/spec.md`

## Summary

Add **calendar-driven** synthetic NDJSON generation ( **`fan-events-ndjson-v2.md`** ) alongside the existing **v1** rolling-window path in `scripts/generate_fan_events.py`. Inputs are a **UTF-8 JSON calendar** (`data-model.md`); per match the generator builds a **bounded attendee set**, emits **`ticket_scan`** and **`merch_purchase`** events only inside **kickoff-derived UTC windows**, sorts **globally** per v2 ordering, and writes **one file** with **atomic** semantics. **Stdlib only** for parse/generate (**`json`**, **`csv` not required**); **`zoneinfo`** for IANA timezones. Logic moves into **`src/fan_events/`** packages with **thin** `scripts/generate_fan_events.py` entrypoint; **pytest** + **ruff** validate behavior and contracts.

## Technical Context

**Language/Version**: Python 3.12+ (`pyproject.toml`)  
**Primary Dependencies**: **None** at runtime for generator (stdlib only per spec/constitution); dev: **pytest**, **ruff** (existing groups).  
**Storage**: Filesystem — calendar JSON in, single NDJSON out.  
**Testing**: `pytest` from repo root; contract tests for shape, sort order, UTF-8, golden byte identity.  
**Target Platform**: Dev laptops (Windows/Linux/macOS); Python 3.12+.  
**Project Type**: CLI + importable library package under `src/`.  
**Performance Goals**: Demo-scale: generate **full-season** files on a laptop in **minutes** for typical match counts (tens of matches, thousands–low millions of lines); no strict SLA.  
**Constraints**: Byte-identical output for fixed `--seed` + inputs; UTF-8 NDJSON; canonical JSON per v1/v2.  
**Scale/Scope**: Single NDJSON file per run; **collect all events in memory** then sort (same pattern as current script). **Streaming** writer deferred if file sizes become problematic.

## Constitution Check

*GATE: Satisfied after Phase 1 design.*

Per `.specify/memory/constitution.md`:

| Gate | Status |
|------|--------|
| Analytics / dbt marts named | **Provisional**: `fct_ticket_scans`, `fct_merch_purchases`, `dim_match` (unchanged from spec). |
| Raw append-only | **Met**: synthetic file emission only. |
| dbt tests | **When marts exist**; not blocking generator merge. |
| Demonstrable path | **Met**: file → raw landing story preserved. |
| Demo-first | **Met**: ship calendar + tests before polish. |
| Spec + contracts | **Met**: `spec.md`, `contracts/fan-events-ndjson-v2.md`, `data-model.md`, `quickstart.md`. |
| Reproducibility | **Met**: `--seed` + deterministic iteration order + pytest golden. |
| NDJSON tests | **Met**: shape, ordering, encoding in `tests/`. |
| v2 migration | **Met**: v2 doc + v1 unchanged for rolling mode. |
| UTC / `Z` | **Met**: `zoneinfo` + UTC output strings. |
| Named constants | **Met**: `JAN_BREYDEL_MAX_CAPACITY = 29062` in code + contract. |
| Python / UV / stdlib | **Met**: no new runtime deps; `uv run pytest` / `uv run python`. |

## Phase 0: Research

**Output**: [`research.md`](research.md)

- **Calendar format**: JSON document with `matches[]` (vs CSV) — **decided**: JSON.
- **Timezone**: **`zoneinfo.ZoneInfo`** — **decided**.
- **Ambiguous DST**: **fail fast** — **decided**.

No unresolved **NEEDS CLARIFICATION** items remain.

## Phase 1: Design

### 1. Input format (calendar)

- **Normative schema**: [`data-model.md`](data-model.md).
- **Validation**: On load — duplicate `match_id`, attendance ≤ 0, missing fields, home Jan Breydel attendance > 29,062 → **non-zero exit** with stderr message.
- **Example fixture**: [`fixtures/calendar_example.json`](fixtures/calendar_example.json).

### 2. Core algorithm (per match)

1. **Sort matches for iteration** deterministically: by **kickoff UTC**, then **`match_id`** (lexical).
2. **Kickoff UTC**: `kickoff_local` + `timezone` → aware datetime → UTC.
3. **Window** (UTC): `[kickoff_utc - start_off, kickoff_utc + end_off]` with defaults **120** / **90** minutes unless overridden on row.
4. **Capacity**: `effective_cap = min(attendance, JAN_BREYDEL_MAX_CAPACITY)` for **home** at Jan Breydel; **away** uses `attendance` as cap (subject to spec/clarifications).
5. **Attendee set**: Build `n = min(effective_cap, attendance)` distinct **`fan_id`** strings from a **deterministic global pool** (e.g. ordered ids `fan_00001` …) using **`random.Random(seed)`** with a **fixed consumption order**: iterate matches in order, then for each match draw subsets / events without varying match order between runs.
6. **Event counts**: `ticket_scan` count = `floor(n * scan_fraction)` with **documented rounding** (lock in tests); `merch_purchase` count from **`merch_factor`** (or equivalent) — **deterministic** integer formulas from `n` and parameters.
7. **Timestamps**: For each event, pick integer seconds uniformly (or deterministic hash-based) within `[window_start, window_end]` using the same RNG stream in **documented order** (e.g. all ticket_scans for match, then merch, or interleaved — **must be fixed** for byte identity).
8. **Locations**: `ticket_scan.location` = stand/venue string from scenario (e.g. rotate `LOCATIONS` subset or `venue_label`); `merch_purchase` optional **`location`** populated per spec (same venue string when applicable).
9. **Aggregate** all records → **validate** → **sort** with v2 **`sort_key`** → **canonical JSON lines** → **atomic write**.

**RNG discipline**: Single `random.Random(seed)` for the whole run; **do not** mix wall-clock time when `--seed` is set (mirror v1 `FIXED_NOW_UTC` pattern if any “now” remains in rolling mode only).

### 3. CLI design

- **One script** `scripts/generate_fan_events.py` with two modes:
  - **Rolling (v1 default)**: existing flags `--days`, `--count`, no `--calendar`.
  - **Calendar (v2)**: `--calendar PATH` **required**; **`--from-date` / `--to-date`** inclusive filter on kickoff UTC (ISO dates).
- **Mutual exclusion**: If `--calendar` is set, **`--days` and `--count` are rejected** (argparse `MutuallyExclusiveGroup` or explicit check). **`--events`** may apply to calendar mode or be ignored with a clear rule — **recommend**: support `both` | `ticket_scan` | `merch_purchase` in both modes for parity.
- **Deprecation**: Do **not** deprecate v1 flags; they remain the default path for `001`.

### 4. Contract

- **Path**: `specs/002-match-calendar-events/contracts/fan-events-ndjson-v2.md`
- **Version**: **2.0**
- **Sort rules**: Extended with **`match_id`** before per-type tie-breaks; canonical **`json.dumps`** unchanged from v1.
- **v1** file: `specs/001-synthetic-fan-events/contracts/fan-events-ndjson-v1.md` (unchanged semantics for rolling mode).

### 5. Module layout

```text
src/
└── fan_events/
    ├── __init__.py
    ├── v1_batch.py          # moved from script: rolling window generation + v1 records
    ├── v2_calendar.py       # calendar load, validate, v2 generation
    ├── ndjson_io.py         # canonical dump, sort_key v1 + v2, atomic write
    └── domain.py            # constants (JAN_BREYDEL_MAX_CAPACITY), LOCATIONS, ITEMS

scripts/
└── generate_fan_events.py   # argparse + dispatch v1 vs v2

tests/
├── test_v1_rolling.py       # existing behavior if moved
├── test_calendar_v2.py      # fixture load, golden NDJSON, sort, errors
└── test_contract_sort.py    # sort_key totality
```

**Rationale**: **Testable** pure functions in `src/`; script stays **I/O + argparse**.

### 6. Documentation

- [`quickstart.md`](quickstart.md) — one season example, capacity/timezone pointers, UV commands.
- **README** (repo): optionally link `002` quickstart when implementing — **follow-up** in tasks (not required in this plan file per user rule).

### 7. Risks & mitigations

| Risk | Mitigation |
|------|------------|
| **Large NDJSON** (full season × high attendance × many events) | **In-memory collect + sort** for v1 parity; document **~RAM ≈ event count × row size**; add **note** in plan: if memory becomes an issue, future **streaming sort** or **chunked merge** (out of scope for `002`). |
| **Slow sort** on millions of rows | Acceptable for demo; **optional** progress logging not required. |
| **Timezone errors** | Fail with message; tests for DST edge (if feasible). |
| **Scope creep** | **Per spec**: no **per-matchday files**; no new deps. |

## Project Structure

### Documentation (this feature)

```text
specs/002-match-calendar-events/
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── spec.md
├── contracts/
│   └── fan-events-ndjson-v2.md
├── fixtures/
│   └── calendar_example.json
└── tasks.md              # /speckit.tasks (not created here)
```

### Source Code (repository root)

```text
src/fan_events/
scripts/generate_fan_events.py
tests/
```

**Structure Decision**: New **`src/fan_events`** package introduced; `tests/` at repo root (pytest discovers `test_*.py`). Existing monolithic script logic is **refactored** into `src/fan_events` during implementation tasks.

## Constitution Check (post-design)

All gates in the table above remain **satisfied**; no Complexity Tracking violations required.

## Complexity Tracking

> No unjustified constitution violations.

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| — | — | — |
