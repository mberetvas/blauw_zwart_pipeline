---
description: "Task list for feature 004 — unified orchestrated NDJSON stream"
---

# Tasks: Unified orchestrated NDJSON stream (`fan_events stream`)

**Input**: Design documents from `specs/004-unified-synthetic-stream/`  
**Prerequisites**: [plan.md](./plan.md), [spec.md](./spec.md), [research.md](./research.md), [data-model.md](./data-model.md), [contracts/](./contracts/)

**Tests**: **Python** changes require **pytest** (TDD preferred per constitution). For NDJSON output, tests assert **contract shape** (`validate_record_v2` / `validate_record_v3`), **merge ordering** per [`contracts/orchestrated-stream.md`](./contracts/orchestrated-stream.md), **UTF-8** line discipline, and **byte-identical** golden runs where `--seed` is fixed. Run `uv run pytest` from the repository root; `uv run ruff check src tests` for lint. **No dbt** work in this feature.

**Organization**: Phases follow user stories (P1 → P3) after shared foundations.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Safe to parallelize (different files, no ordering dependency on incomplete sibling)
- **[USn]**: Maps to [spec.md](./spec.md) user stories (US1 = P1, US2 = P2, US3 = P3)

---

## Phase 1: Setup (readiness)

**Purpose**: Lock normative inputs before code changes.

- [x] T001 Review [spec.md](./spec.md), [plan.md](./plan.md), [contracts/orchestrated-stream.md](./contracts/orchestrated-stream.md), and [contracts/cli-stream.md](./contracts/cli-stream.md) for implementation checklist and flag naming decisions

---

## Phase 2: Foundational (blocking all user stories)

**Purpose**: Merge ordering primitives and **v2 iterator design** so `heapq.merge` can combine with `iter_retail_records` without a full in-memory global sort.

**⚠️** No user-story implementation until merge keys + v2 sorted iterators exist.

- [x] T002 [P] Add failing pytest tests for merge-key ordering (timestamp, `event`, canonical line) in `tests/test_merge_keys.py` per [`contracts/orchestrated-stream.md`](./contracts/orchestrated-stream.md)
- [x] T003 Add `src/fan_events/merge_keys.py` with `parse_timestamp_utc_z`, `merge_key_tuple(record: dict) -> tuple`, and helpers using `src/fan_events/ndjson_io.py` `dumps_canonical` for K3 tie-break; make `tests/test_merge_keys.py` pass; introduce **no** unexplained literals for normative ordering — any orchestration-specific named constant goes in `src/fan_events/domain.py` (FR-SC-006) and is referenced from docstrings or [`contracts/orchestrated-stream.md`](./contracts/orchestrated-stream.md) if user-visible
- [x] T004 [P] Add failing pytest tests for per-match sorted v2 record iteration in `tests/test_v2_calendar_merge.py` (fixtures from existing calendar helpers)
- [x] T005 Refactor `src/fan_events/v2_calendar.py` to extract per-match record construction from `generate_v2_records` into reusable helpers (keep `generate_v2_records` behavior unchanged for existing callers)
- [x] T006 Add `iter_sorted_records_for_match(ctx: MatchContext, rng: random.Random, **kwargs) -> Iterator[dict]` in `src/fan_events/v2_calendar.py` yielding records **sorted** by `merge_key_tuple` within the match window
- [x] T007 Add `iter_v2_records_merged_sorted(contexts: list[MatchContext], rng: random.Random, **kwargs) -> Iterator[dict]` in `src/fan_events/v2_calendar.py` using `heapq.merge` over per-match iterators with key=`merge_key_tuple` from `src/fan_events/merge_keys.py`; document preconditions (each inner iterator non-decreasing by merge key) in docstrings
- [x] T008 [P] Extend `tests/test_v2_calendar_merge.py` to assert global non-decreasing merge keys across a multi-match calendar sample in `tests/test_v2_calendar_merge.py`

**Checkpoint**: Merge keys tested; v2 side is a **lazy** globally ordered iterator suitable for orchestration.

---

## Phase 3: User Story 1 — One mixed, time-ordered stream (Priority: P1) 🎯 MVP

**Goal**: Interleave v2 calendar events with v3 `retail_purchase` in **non-decreasing** synthetic time; **byte-identical** replay for fixed `--seed`.

**Independent test**: `uv run fan_events stream …` with calendar + retail + seed; NDJSON lines have non-decreasing timestamps; repeat run matches bytes.

### Tests for User Story 1

- [x] T009 [P] [US1] Add failing tests for two-stream merge (synthetic v2 + v3 iterators) in `tests/test_orchestrator_merge.py` including tie cases and empty v2 or empty retail branches

### Implementation for User Story 1

- [x] T010 [US1] Create `src/fan_events/orchestrator.py` with `merged_record_iter(*, retail_iter, v2_iter, key=merge_key_tuple)` wrapping `heapq.merge` from stdlib
- [x] T011 [US1] Wire `iter_retail_records` in `src/fan_events/orchestrator.py` with `skip_default_event_cap=True` when spec-unbounded default applies (no post-merge `--max-events` / `--max-duration`); align kwargs with `src/fan_events/v3_retail.py` semantics documented in [research.md](./research.md)
- [x] T012 [US1] Implement unified `fan_pool` / shared `fan_id` namespace when both sources enabled (FR-012): coordinate `src/fan_events/v2_calendar.py` pool construction and `src/fan_events/v3_retail.py` `fan_pool` / draws in `src/fan_events/orchestrator.py`
- [x] T013 [US1] Add golden / byte-identical test for fixed seed merged output in `tests/test_orchestrator_merge.py` (capture stdout or in-memory sink)

**Checkpoint**: Core merge path works without full CLI (import tests pass).

---

## Phase 4: User Story 2 — Configurable sources and output (Priority: P2)

**Goal**: Reuse calendar/v2 and retail parameters; **stdout** or **append-only** file; optional **wall-clock pacing** between emitted lines.

**Independent test**: Retail-only, calendar-only, and combined runs; append mode does not truncate; pacing sleeps only between **merged** lines.

### Tests for User Story 2

- [x] T014 [P] [US2] Add tests for NDJSON line formatting (v2 vs v3 validators) and sink selection in `tests/test_orchestrator_merge.py` or `tests/test_cli_stream.py`

### Implementation for User Story 2

- [x] T015 [US2] Implement `StreamOrchestrator` (or equivalent class) in `src/fan_events/orchestrator.py`: iterate merged records, emit canonical lines via `dumps_canonical` + `validate_record_v2` / `validate_record_v3` from `src/fan_events/ndjson_io.py` (reuse `format_line_v3` pattern for v3)
- [x] T016 [US2] Add stdout write path in `src/fan_events/orchestrator.py` (`sys.stdout.write` + `flush` per complete line)
- [x] T017 [US2] Add append-only file sink (open with `encoding="utf-8"`, append mode, newline `\n`) in `src/fan_events/orchestrator.py`; do **not** use `write_atomic_text` for streaming append
- [x] T018 [US2] Add optional wall-clock pacing between **emitted** lines in `src/fan_events/orchestrator.py` mirroring pacing RNG pattern from `run_v3` in `src/fan_events/cli.py`
- [x] T019 [US2] Add `SUBCOMMAND_STREAM = "stream"` and `stream` subparser in `src/fan_events/cli.py` implementing the **Sources** matrix and validation rules in [contracts/cli-stream.md](./contracts/cli-stream.md) (merged / calendar-only / retail-only); add `--no-retail`; reject **v1 rolling** flags and error on `--no-retail` without `--calendar`
- [x] T020 [US2] Reuse `_retail_generator_kwargs` and calendar/v2 argument groups in `src/fan_events/cli.py`; on `stream` **do not** register `generate_retail`’s short **`-n` / `-d`** for post-merge limits — use **`--max-events` / `--max-duration`** long names for **post-merge** caps only, per [contracts/cli-stream.md](./contracts/cli-stream.md) § Post-merge limits; add distinct **`--retail-max-events` / `--retail-max-duration`** (or equivalent) if retail-internal caps are exposed alongside post-merge caps
- [x] T021 [US2] Implement `run_stream(args: argparse.Namespace) -> None` in `src/fan_events/cli.py` calling into `src/fan_events/orchestrator.py` and dispatch `args.command == SUBCOMMAND_STREAM` in `main()`
- [x] T022 [P] [US2] Add argparse smoke tests for `stream` in `tests/test_cli_stream.py` (parse-only and minimal mocked run)
- [x] T033 [P] [US2] Add test in `tests/test_cli_stream.py` that `fan_events stream --calendar` with a **nonexistent** or **invalid** calendar path exits non-zero and reports error to stderr consistent with `generate_events --calendar` (`CalendarError` semantics)

**Checkpoint**: Operators can run `uv run fan_events stream …` with output destination and pacing.

---

## Phase 5: User Story 3 — Bounded runs and clean stop (Priority: P3)

**Goal**: Optional `--max-events` and `--max-duration` on the **merged** stream; **Ctrl+C** exits without torn lines; help warns on unbounded use.

**Independent test**: Limits stop at first binding rule; interrupt produces only complete lines.

### Tests for User Story 3

- [x] T023 [P] [US3] Add failing tests for post-merge `--max-events` and `--max-duration` in `tests/test_orchestrator_merge.py`; include at least one case combining **wall-clock pacing** with a **max-events** cap (and optional min=max=0 pacing) per [spec.md](./spec.md) edge cases

### Implementation for User Story 3

- [x] T024 [US3] Implement merged-stream caps in `src/fan_events/orchestrator.py` (emit count; simulated duration from agreed `t0` per [research.md](./research.md)); stop before first violating record
- [x] T025 [US3] Document unbounded-default and resource warning strings on `stream` parser in `src/fan_events/cli.py` (`help=` / epilog per FR-008)
- [x] T026 [US3] Ensure `KeyboardInterrupt` path flushes only complete lines in `src/fan_events/orchestrator.py` / `src/fan_events/cli.py`; document “no partial line” in `--help` text
- [x] T027 [P] [US3] Add integration-style test with subprocess or `main([...])` for interrupt/caps in `tests/test_cli_stream.py` (scope minimal; mark `@pytest.mark.slow` if needed)

**Checkpoint**: Bounded and interrupt semantics match [spec.md](./spec.md) FR-008/FR-009.

---

## Phase 6: Polish & cross-cutting

**Purpose**: Documentation, examples, quality gates.

- [x] T028 [P] Add `fan_events stream` row to CLI overview table and short subsection (stdout, append, kcat pipe) in `README.md`
- [x] T029 [P] Update `specs/004-unified-synthetic-stream/quickstart.md` to match final flag names and copy-paste examples
- [x] T030 [P] Add `EPILOG_STREAM` examples in `src/fan_events/cli.py` mirroring [quickstart.md](./quickstart.md)
- [x] T031 Run `uv run ruff check src tests` from repo root and fix any issues in `src/fan_events/*.py` and `tests/*.py`
- [x] T032 Run full `uv run pytest` from repo root; ensure green
- [ ] T034 [P] If any normative orchestration constant remains after **T003** (e.g. default pacing bounds), add a named symbol in `src/fan_events/domain.py` and a one-line reference under **Constants** in [`contracts/orchestrated-stream.md`](./contracts/orchestrated-stream.md) (FR-SC-006); skip if no new constants are needed

---

## Dependencies & execution order

### Phase dependencies

| Phase | Depends on |
|-------|------------|
| Phase 1 | — |
| Phase 2 | Phase 1 |
| Phase 3 (US1) | Phase 2 |
| Phase 4 (US2) | Phase 3 (orchestrator skeleton + merge) |
| Phase 5 (US3) | Phase 4 (CLI + orchestrator IO path) |
| Phase 6 | Phases 3–5 for feature-complete docs |

### User story dependencies

- **US1**: After Phase 2 only.
- **US2**: Requires US1 merge + `orchestrator.py` skeleton (T010–T013).
- **US3**: Requires US2 CLI + sinks (T015–T021).
- **T033** (invalid calendar): Requires **T019–T021** (`stream` parser accepts `--calendar`).

### Parallel opportunities

| Tasks | Notes |
|-------|--------|
| T002, T004 | Different test files; both are red tests before impl |
| T008, T009 | After T007/T010 respectively; both test files |
| T014, T022 | Tests in parallel once dependencies met |
| T023, T027 | Different test scopes |
| T028, T029, T030 | Doc/epilog edits in parallel (avoid conflicting edits to same paragraph) |
| T033 | After T019–T021 (CLI parses calendar path) |
| T034 | After T003–T007; optional if no constants needed |

### MVP scope (ship early)

1. Complete **Phase 1–2** (merge keys + v2 iterators).  
2. Complete **Phase 3 (US1)** — `orchestrator` + tests; optional thin CLI stub to prove end-to-end.  
3. **Stop and validate** independently before Phase 4.

---

## Implementation strategy

1. **Red–green** on `tests/test_merge_keys.py` and `tests/test_v2_calendar_merge.py` before orchestrator wiring.  
2. **Incremental PRs**: (A) merge_keys + v2 iterators; (B) orchestrator merge + US1 tests; (C) CLI + sinks + pacing; (D) limits + interrupt; (E) README + polish.  
3. Keep **existing** `generate_events` / `generate_retail` behavior stable; add new code paths behind `stream`.

---

## Notes

- **File paths** use repository root: `src/fan_events/`, `tests/`.  
- Do not add runtime dependencies beyond **stdlib** + existing **`tzdata`** in `pyproject.toml`.  
- **Batch** atomic writes (`write_atomic_text`) remain for `generate_events` / `generate_retail` file modes only.
