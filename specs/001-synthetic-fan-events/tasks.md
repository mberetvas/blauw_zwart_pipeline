---
description: "Task list for synthetic fan event source (001-synthetic-fan-events)"
---

# Tasks: Synthetic fan event source

**Input**: Design documents from `/specs/001-synthetic-fan-events/`  
**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/, quickstart.md

**Tests**: No automated test suite required by the spec for this slice. **dbt tests** apply when
warehouse models land in a follow-up feature; not part of these tasks. Validate via manual steps in
`specs/001-synthetic-fan-events/quickstart.md` (byte-identical runs with `--seed`).

**Organization**: Phases follow user story priorities (P1 → P2 → P3) after shared setup and foundation.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependency on incomplete sibling)
- **[Story]**: US1, US2, US3 map to spec user stories
- Every task includes at least one concrete file path

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Repository hygiene and script entrypoint shell

- [x] T001 [P] Add `out/` to `.gitignore` at repository root so default NDJSON output stays untracked
- [x] T002 Create `scripts/generate_fan_events.py` with module docstring linking to `specs/001-synthetic-fan-events/contracts/fan-events-ndjson-v1.md` and `if __name__ == "__main__"` guard (stub `main()`)

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: CLI, canonical JSON, and atomic write utilities every story builds on

**⚠️ CRITICAL**: Complete before user-story implementation

- [x] T003 Implement `argparse` in `scripts/generate_fan_events.py` with `--output`/`-o`, `--count`/`-n`, `--days`, optional `--seed`, `--events` with choices `both|ticket_scan|merch_purchase` and defaults matching `specs/001-synthetic-fan-events/contracts/fan-events-ndjson-v1.md`
- [x] T004 Implement `dumps_canonical(obj: dict) -> str` using `json.dumps(..., sort_keys=True, separators=(",", ":"), ensure_ascii=False)` in `scripts/generate_fan_events.py`
- [x] T005 Implement UTF-8 `write_atomic_text(path: pathlib.Path, content: str) -> None` using a temp file in the target directory plus `os.replace`, and `ensure_parent_dir(path: pathlib.Path) -> None` with `Path.mkdir(parents=True, exist_ok=True)` in `scripts/generate_fan_events.py`

**Checkpoint**: Utilities ready — implement record shapes and orchestration

---

## Phase 3: User Story 1 — Published contract and valid events (Priority: P1) 🎯 MVP

**Goal**: Each emitted line is a valid `ticket_scan` or `merch_purchase` per the contract and data model.

**Independent Test**: Parse each line as JSON; assert required keys and `amount > 0` for merch; wrong shapes fail before write.

### Implementation for User Story 1

- [x] T006 [US1] Implement `make_ticket_scan(fan_id: str, location: str, timestamp: str) -> dict` and `make_merch_purchase(fan_id: str, item: str, amount: float, timestamp: str) -> dict` with **only** the keys defined in `specs/001-synthetic-fan-events/data-model.md` in `scripts/generate_fan_events.py`
- [x] T007 [US1] Implement `validate_record(rec: dict) -> None` that raises on any contract violation (unknown `event`, missing keys, forbidden cross-type keys, `amount <= 0`) per `specs/001-synthetic-fan-events/contracts/fan-events-ndjson-v1.md` in `scripts/generate_fan_events.py`

**Checkpoint**: Validators and builders usable without full generator loop

---

## Phase 4: User Story 2 — Reproducible demo output (Priority: P2)

**Goal**: Same `--seed` and CLI args → **byte-identical** output file; optional seed → non-deterministic.

**Independent Test**: Two runs with identical flags including `--seed`; `fc /B` (Windows) or `cmp` (Unix) shows no diff.

### Implementation for User Story 2

- [x] T008 [US2] Implement `_event_rank(event: str) -> int` with `ticket_scan` before `merch_purchase` (not Unicode order) per `specs/001-synthetic-fan-events/research.md` in `scripts/generate_fan_events.py`
- [x] T009 [US2] Implement `sort_key(rec: dict) -> tuple` for global ordering: timestamp, `_event_rank`, fan_id, then `location` for scans or `(item, amount)` for purchases per `specs/001-synthetic-fan-events/contracts/fan-events-ndjson-v1.md` in `scripts/generate_fan_events.py`
- [x] T010 [US2] Instantiate `random.Random(args.seed)` when `--seed` provided, else `random.Random()`; thread this RNG through all sampling in `scripts/generate_fan_events.py`

**Checkpoint**: Sorting and RNG match reproducibility acceptance criteria

---

## Phase 5: User Story 3 — Batch suitable for downstream handoff (Priority: P3)

**Goal**: One JSON object per line, UTF-8 NDJSON, monotonic timestamps in file order, default batch includes both event types when `--events both` and `count >= 2`.

**Independent Test**: Split on `\n`; each line `json.loads`; timestamps non-decreasing; default run contains both `event` values.

### Implementation for User Story 3

- [x] T011 [US3] Implement `generate_batch(rng: random.Random, *, count: int, days: int, events_mode: str, now_utc: datetime.datetime) -> list[dict]` that draws UTC ISO timestamps with `Z` within `[now_utc - days, now_utc]`, synthetic `fan_*` ids, demo vocab for `location`/`item`, cent-safe positive `amount`, and when `events_mode == "both"` and `count >= 2` emits **at least one** `ticket_scan` and **one** `merch_purchase` in `scripts/generate_fan_events.py`
- [x] T012 [US3] Implement `records_to_ndjson(records: list[dict]) -> str`: `validate_record` each, `sorted(..., key=sort_key)`, one `dumps_canonical` per record, join with `\n` using LF only; if `records` is non-empty, append a **final `\n`** after the last line per `specs/001-synthetic-fan-events/contracts/fan-events-ndjson-v1.md` (empty list → return `""`) in `scripts/generate_fan_events.py`
- [x] T013 [US3] Implement `main()` in `scripts/generate_fan_events.py`: parse args, resolve default output path `out/fan_events.ndjson`, `ensure_parent_dir`, `generate_batch` → `records_to_ndjson` → `write_atomic_text`; on any error print to stderr and exit with code `1` without leaving a complete durable file at the target path

**Checkpoint**: End-to-end CLI matches spec FR-001–FR-009 and quickstart

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Docs stay aligned with the script

- [x] T014 [P] Update `specs/001-synthetic-fan-events/quickstart.md` so every command example matches final flag names and defaults in `scripts/generate_fan_events.py`
- [x] T015 [P] Extend `README.md` with a short “Synthetic events” line pointing to `scripts/generate_fan_events.py` and `specs/001-synthetic-fan-events/quickstart.md`

---

## Dependencies & Execution Order

### Phase Dependencies

- **Phase 1** → **Phase 2** → **Phases 3–5** (US1 → US2 → US3) → **Phase 6**
- **US2** depends on **US1** (sorting assumes valid dict shapes)
- **US3** depends on **US1** and **US2** (generation uses builders/RNG/sort/serialize)

### User Story Dependencies

- **US1**: After Phase 2 (T003–T005)
- **US2**: After US1 (T006–T007)
- **US3**: After US2 (T008–T010)

### Within `scripts/generate_fan_events.py`

1. T003–T005 utilities  
2. T006–T007 builders + validation  
3. T008–T010 ordering + RNG  
4. T011–T013 batch + NDJSON + `main()`

---

## Parallel Example

```text
# After Phase 2 completes, docs-only work can proceed in parallel with coding only if you defer doc sync to Phase 6:
T014 quickstart.md  ||  T006–T013 generate_fan_events.py

# Phase 1 parallel:
T001 .gitignore  ||  (prepare T002 in editor — same session usually sequential)
```

---

## Implementation Strategy

### MVP (User Story 1 only)

Not sufficient for feature acceptance — spec requires file output, ordering, and reproducibility. Treat **Phase 5 completion** as MVP for this feature.

### Full feature (recommended)

1. Complete Phases 1–2  
2. US1 → US2 → US3 (T006–T013)  
3. Phase 6 doc alignment  
4. Run quickstart reproducibility check manually

### Suggested commit cadence

Commit after T005, after T007, after T010, after T013, after T015.

---

## Summary

| Metric | Value |
|--------|-------|
| **Total tasks** | 15 |
| **Per story** | US1: 2 · US2: 3 · US3: 3 (plus Setup: 2, Foundation: 3, Polish: 2) |
| **Parallel [P]** | T001, T014, T015 (and Phase 1 vs 6 docs when implementation is stable) |

**Output file**: `specs/001-synthetic-fan-events/tasks.md`
