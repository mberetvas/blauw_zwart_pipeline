# Tasks: Match-calendar synthetic fan events

**Input**: Design documents from `/specs/002-match-calendar-events/`  
**Prerequisites**: [`plan.md`](plan.md), [`spec.md`](spec.md), [`data-model.md`](data-model.md), [`contracts/fan-events-ndjson-v2.md`](contracts/fan-events-ndjson-v2.md), [`research.md`](research.md), [`quickstart.md`](quickstart.md)

**Tests**: TDD where noted: contract / validation tests land **before** or **with** the implementation they lock. Run **`uv run pytest`** from repo root; **`ruff check .`** on touched Python. No dbt scope in this feature.

**Organization**: Phases follow dependency order: **data model & shared NDJSON → v2 generator core → CLI → docs → golden/repro → lint gate**. User story labels map to [`spec.md`](spec.md) priorities. **001 / v1** behavior is preserved by moving only what is required into **`src/fan_events/`** for shared utilities—no unrelated refactors.

## Format

- `[P]` = parallelizable (different files, no ordering dependency on incomplete sibling).
- `[USn]` = user story from spec (P1–P4).

---

## Phase 1: Setup (package layout)

**Purpose**: Editable `fan_events` package and test discovery.

- [x] T001 Create package skeleton `src/fan_events/__init__.py` (empty or minimal `__all__`).
- [x] T002 Configure `pyproject.toml` so `fan_events` is importable from `src/` (setuptools/hatch `packages` / `package-dir`); confirm `uv run python -c "import fan_events"` works from repo root.
- [x] T003 Add `tests/__init__.py` if needed for imports; ensure pytest collects `tests/test_*.py` from repo root per project convention.

**Checkpoint — package import**: `uv run python -c "import fan_events"` succeeds.

---

## Phase 2: Foundational (domain + NDJSON + v1 extraction)

**Purpose**: Shared constants, canonical JSON, atomic write, v1 rolling path moved out of the script **only as needed** for reuse—behavior unchanged.

- [x] T004 Add `src/fan_events/domain.py` with `JAN_BREYDEL_MAX_CAPACITY = 29062`, and move `LOCATIONS`, `ITEMS`, `TICKET_SCAN` / `MERCH_PURCHASE` string constants from `scripts/generate_fan_events.py` (single source of truth).
- [x] T005 Add `src/fan_events/ndjson_io.py`: `dumps_canonical`, `write_atomic_text`, `sort_key_v1`, `sort_key_v2` per `specs/001-synthetic-fan-events/contracts/fan-events-ndjson-v1.md` and `specs/002-match-calendar-events/contracts/fan-events-ndjson-v2.md`; `records_to_ndjson_v1` using v1 `validate_record` + v1 sort.
- [x] T006 [P] Add `tests/test_ndjson_sort.py`: deterministic ordering for v1 and v2 tuples (timestamp → event → fan_id → match_id for v2 → type-specific ties).
- [x] T007 Move rolling-window logic from `scripts/generate_fan_events.py` into `src/fan_events/v1_batch.py` (`generate_batch`, `make_ticket_scan`, `make_merch_purchase`, v1-only validation, `_utc_ts_string`, `_fan_id`, `FIXED_NOW_UTC` usage)—**no semantic changes**; update `scripts/generate_fan_events.py` to import and call `v1_batch` + `ndjson_io.records_to_ndjson_v1`.
- [x] T008 Add `tests/test_v1_rolling_parity.py`: fixed `--seed`, `--count`, `--days`, `--output` path → output bytes **match pre-refactor behavior** OR golden string checked in test (lock v1 contract).

**Checkpoint — v1 unchanged**: `test_v1_rolling_parity.py` passes; rolling CLI still emits **`fan-events-ndjson-v1`**-compatible output.

---

## Phase 3: User Story 1 (P1) — Calendar load, validation, timezone windows

**Purpose**: Parse `specs/002-match-calendar-events/data-model.md` JSON; fail fast on invalid rows; compute kickoff UTC and default **T−120 / T+90** windows.

- [x] T009 [P] [US1] Add `tests/test_calendar_validation.py` (TDD): duplicate `match_id`, `attendance <= 0`, home `attendance > 29062` at Jan Breydel, missing required keys → raise or exit path with stable error **before** full generator exists.
- [x] T010 [US1] Implement `load_calendar` / `parse_calendar_document` reading UTF-8 JSON from path in `src/fan_events/v2_calendar.py` (or `src/fan_events/calendar_load.py` if preferred—keep under `src/fan_events/`).
- [x] T011 [US1] Implement `validate_match_row` / document-level checks against `data-model.md` + `JAN_BREYDEL_MAX_CAPACITY` for home matches.
- [x] T012 [US1] Implement `kickoff_to_utc` using `zoneinfo.ZoneInfo` per [`research.md`](research.md); ambiguous/missing local times → fail with clear error.
- [x] T013 [US1] Implement `match_window_utc(kickoff_utc, start_offset_min=120, end_offset_min=90, overrides=...)` per row optional fields.

**Checkpoint CP1 — calendar with 3 matches**: After **T024** adds `specs/002-match-calendar-events/fixtures/calendar_three_matches.json`, tests load it, apply date filter, and assert **expected match count** and ordered iteration (kickoff UTC, then `match_id`). *If implementing tests before T024, inline minimal JSON in the test file temporarily, then switch to the shared fixture in T024.*

---

## Phase 4: User Story 1 (P1) — Per-match generation + v2 NDJSON assembly

**Purpose**: Deterministic attendee draw, `scan_fraction` / merch counts, timestamps inside windows, `match_id` on all records; optional `location` on `merch_purchase` when applicable.

- [x] T014 [US1] Add `tests/test_v2_records_shape.py` (TDD): expected keys for `ticket_scan` / `merch_purchase` per `specs/002-match-calendar-events/contracts/fan-events-ndjson-v2.md` (include `match_id`; optional `location` on merch).
- [x] T015 [US1] Implement deterministic match iteration order and RNG consumption order in `src/fan_events/v2_calendar.py` (single `random.Random(seed)` for calendar mode).
- [x] T016 [US1] Implement `build_events_for_match(...)` producing v2 dicts: `ticket_scan`/`merch_purchase` with UTC `Z` timestamps in window, `location` from `venue_label` / stand lists in `domain.py`, optional merch `location`.
- [x] T017 [US1] Implement `generate_calendar_records(...)` → list of dicts, then `records_to_ndjson_v2` in `src/fan_events/ndjson_io.py` (validate v2 shape, global sort, trailing newline / empty file = zero bytes).

---

## Phase 5: User Story 2 (P2) — Seeded byte-identical output

**Purpose**: Same inputs → same file bytes (`spec.md` FR-008).

- [x] T018 [US2] Add `tests/test_v2_reproducibility.py`: two in-memory or tmpdir runs with same `--seed`, same calendar fixture `specs/002-match-calendar-events/fixtures/calendar_example.json`, same date range → **byte-identical** file contents.

**Checkpoint CP2 — seeded output byte-identical**: `test_v2_reproducibility.py` passes.

---

## Phase 6: User Story 3 (P3) — Match grouping

**Purpose**: Every event carries correct `match_id` for season-level partitioning.

- [x] T019 [US3] Add `tests/test_v2_match_grouping.py`: for multi-match output, `match_id` values are exactly the fixture’s ids; no orphan events.

---

## Phase 7: User Story 4 (P4) — Merch `location` semantics

**Purpose**: Optional `location` on `merch_purchase` populated per contract when generator assigns venue context.

- [x] T020 [US4] Extend `tests/test_v2_records_shape.py` (or `tests/test_v2_merch_location.py`) asserting home vs away `location` strings align with `venue_label` / contract rules.

---

## Phase 8: CLI — calendar mode + mutual exclusion

**Purpose**: Single entrypoint `scripts/generate_fan_events.py`; v2 path only when `--calendar` is set.

- [x] T021 Extend `scripts/generate_fan_events.py` argparse: `--calendar`, `--from-date`, `--to-date` (ISO dates); **mutually exclusive** group with `--days` and `--count`; optional `--events` behavior documented (mirror v1 or error if unsupported—pick one and test).
- [x] T022 [US1] Wire calendar path: load → filter → `generate_calendar_records` → `write_atomic_text` to `--output`; exit code **1** on validation errors with message to stderr.
- [x] T023 [P] Add `tests/test_cli_calendar.py`: subprocess or `runpy` invoking script with invalid flag combinations → non-zero exit.

---

## Phase 9: Fixtures & documentation

**Purpose**: Executable quickstart and CP1 fixture.

- [x] T024 [P] Add `specs/002-match-calendar-events/fixtures/calendar_three_matches.json` (three distinct `match_id`, valid kickoffs/attendance) for CP1 tests.
- [x] T025 Update `specs/002-match-calendar-events/quickstart.md` so CLI examples match implemented flags and paths (`uv run python scripts/generate_fan_events.py ...`).
- [x] T026 [P] Update root `README.md` with a single sentence + link to `specs/002-match-calendar-events/quickstart.md` for calendar/season generation (minimal change).

---

## Phase 10: Polish & quality gates

**Purpose**: Lint and full test suite green on dev laptop.

- [x] T027 Run `ruff check .` from repo root; fix any issues in `src/fan_events/`, `scripts/generate_fan_events.py`, `tests/`.
- [x] T028 Run `uv run pytest` from repo root; fix failures until green.

**Checkpoint CP3 — ruff + pytest green**: both commands exit **0**.

---

## Dependencies & execution order

| Phase | Depends on | Blocks |
|-------|------------|--------|
| 1 Setup | — | 2 |
| 2 Foundational | 1 | 3–4, 8 (CLI needs ndjson + v1 stable) |
| 3 US1 load | 2 | 4 |
| 4 US1 generate | 3 | 5, 6, 7 |
| 5 US2 | 4 | — |
| 6 US3 | 4 | — |
| 7 US4 | 4 | — |
| 8 CLI | 4 | 9 |
| 9 Docs/fixtures | 3 (fixture for CP1), 8 | 10 |
| 10 Polish | all code tasks | release |

**Parallel opportunities**: T006 parallel to T007 only if sort tests don’t import v1_batch—**serial** T005 before T006/T007. T009 parallel to nothing before T010. T023 parallel to T024–T026 after T022.

---

## Implementation strategy

1. **MVP**: Complete Phases **1–4** + **8** (minimal CLI) + **CP2** test to ship calendar NDJSON.
2. **Incremental**: Add US3–US4 tests (Phases 6–7), then docs (Phase 9), then Phase 10.
3. **Stop early**: After CP3, merge; defer streaming writer / per-matchday files per spec non-goals.

---

## Summary

| Metric | Value |
|--------|--------|
| Total tasks | T001–T028 (28) |
| US1 (P1) | T009–T017, T022, T024 (calendar + generate + CLI wire + fixture) |
| US2 (P2) | T018 |
| US3 (P3) | T019 |
| US4 (P4) | T020 |
| Parallel tasks | T006, T009, T023, T024, T026 (where [P]) |

**Independent test criteria**

- **US1**: Invalid calendar fails; valid calendar produces in-window timestamps and expected event shapes.
- **US2**: Duplicate runs → identical bytes.
- **US3**: `match_id` partition matches fixture.
- **US4**: Merch `location` rules hold for home/away samples.

**Suggested MVP scope**: Phases 1–4 + 8 (CLI) + Phase 10 subset on touched files; add Phases 5–7 + 9 as hardening.
