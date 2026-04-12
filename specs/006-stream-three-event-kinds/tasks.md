---
description: "Task list for 006 continuous stream (master clock + match-day retail)"
---

# Tasks: Continuous unified stream (master clock + match-day retail)

**Input**: `specs/006-stream-three-event-kinds/` — [plan.md](./plan.md), [spec.md](./spec.md), [research.md](./research.md), [data-model.md](./data-model.md), [contracts/](./contracts/), [quickstart.md](./quickstart.md)

**Prerequisites**: `plan.md`, `spec.md`

**Tests**: Constitution **VI** / **IX**: extend **pytest** with TDD where noted; **`uv run pytest`** from repo root; **`uv run ruff check src tests`**. NDJSON: assert **shape**, **ordering** (`merge_key_tuple` / `orchestrated-stream.md`), **encoding**; fixed-seed **golden** or **ratio** tests per [retail-intensity-006.md](./contracts/retail-intensity-006.md).

**Organization**: Phases follow **User Story** priorities from [spec.md](./spec.md) (US1 P1 → US2 P2 → US3 P3), after shared foundation.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: parallel-safe (different files, no unfinished dependency)
- **[USn]**: user story label (US1–US3)

## Phase 1: Setup (baseline)

**Purpose**: Lock contract numbers and failing tests before core refactors.

- [X] T001 [P] Add failing unit tests for **+1 calendar year** shift on `kickoff_local` / `kickoff_utc` with **Feb 29 → Feb 28** clamp in `tests/test_v2_calendar_year_shift_006.py` (targets API to be added in `src/fan_events/v2_calendar.py`)

---

## Phase 2: Foundational (blocking — master clock + season shift + duration anchor)

**Purpose**: **No user story is complete** until calendar-year loop, **`t0`**, and **`--max-duration`** semantics match [cli-stream-006-supplement.md](./contracts/cli-stream-006-supplement.md).

**⚠️ CRITICAL**: Complete T002–T007 before US1–US3 acceptance.

- [X] T002 Implement **calendar-year** shift helper(s) in `src/fan_events/v2_calendar.py` (stdlib-only; update `shift_match_context` or replace timedelta-based shift) so `tests/test_v2_calendar_year_shift_006.py` passes
- [X] T003 Refactor `iter_looped_v2_records` in `src/fan_events/v2_calendar.py` to apply **+k calendar years** per cycle (not `timedelta(days=365)*k`); adjust `match_id` suffix rules if needed for uniqueness; update any callers in `src/fan_events/cli.py`
- [X] T004 Add `compute_stream_t0(retail_epoch_utc, v2_contexts_pass0)` (or equivalent name) in `src/fan_events/orchestrator.py` per [data-model.md](./data-model.md) + supplement; document **earliest v2 instant** rule in docstring
- [X] T005 Extend `write_merged_stream` in `src/fan_events/orchestrator.py` to accept **`t0_anchor: datetime | None`** and use **`(ts - t0_anchor).total_seconds() <= max_duration_seconds`** for post-merge `--max-duration` when `t0_anchor` is set; keep legacy behavior when `None` if other callers require it
- [X] T006 Wire **`t0_anchor=compute_stream_t0(...)`** from `run_stream` and **`_run_stream_kafka`** in `src/fan_events/cli.py` into `write_merged_stream` / Kafka emit path
- [X] T007 Add `tests/test_stream_max_duration_t0_006.py` proving **`--max-duration`** uses **`t0`** (not first-emitted line) on a **merged** fixture with delayed first line vs early `t0`; extend the same file or add `tests/test_stream_max_limits_combo_006.py` proving **first-triggered** stop when **both** **`--max-events`** and **`--max-duration`** are set (align with **FR-009** / **Edge Cases** “first limit wins”)

**Checkpoint**: Calendar-year loop + **`t0`** duration semantics covered by tests.

---

## Phase 3: User Story 1 — Endless coherent mixed stream (Priority: P1) 🎯 MVP

**Goal**: Merged **`stream`** with **`--calendar`** does **not** stop after one pass; **`ticket_scan` + merch + `retail_purchase`** stay **time-ordered**; caps global per clarifications.

**Independent Test**: `uv run python -m fan_events stream --calendar <fixture.json> --seed 1 --max-events N` with **N** large enough to span **≥2** season passes (merged **or** `--no-retail` calendar-only); timestamps strictly forward across pass boundary.

### Tests for User Story 1

- [X] T008 [P] [US1] Add `tests/test_stream_calendar_loop_006.py`: **≥2** calendar cycles under `--max-events`, assert monotonic **`timestamp`** and expected **`match_id`** cycle suffix pattern from `src/fan_events/v2_calendar.py`; include a **calendar-only** case (`--calendar --no-retail`) with the same **≥2**-pass expectation unless **`--no-calendar-loop`** is set; assert the **merged** sample includes **all three** event kinds (**`ticket_scan`**, **`merch_purchase`**, **`retail_purchase`**) at least once over the run (**FR-001** / **US1**)

### Implementation for User Story 1

- [X] T009 [US1] Default **on** infinite calendar for `fan_events stream` whenever **`--calendar`** is set (**merged** and **calendar-only** / **`--no-retail`**): implement **`--no-calendar-loop`** opt-out in `src/fan_events/cli.py`; reconcile with existing `--calendar-loop` / `--calendar-loop-shift` (alias, deprecate, or document) so behavior matches [spec.md](./spec.md) **FR-004** and [cli-stream-006-supplement.md](./contracts/cli-stream-006-supplement.md) §1
- [X] T010 [US1] Verify merged `run_stream` in `src/fan_events/cli.py` passes **`skip_default_event_cap=True`** (or equivalent) into `iter_retail_records` in `src/fan_events/v3_retail.py` when post-merge caps omitted — unbounded retail side per **004** research / **006** spec
- [X] T011 [US1] Confirm `iter_merged_records` in `src/fan_events/orchestrator.py` + v2/v2 iterators still yield **non-decreasing** `merge_key_tuple` across season boundary; fix ordering if calendar-year shift exposes gaps

**Checkpoint**: US1 demo: long run with **Ctrl+C** or **`--max-events`** only.

---

## Phase 4: User Story 2 — Match-day retail tuning (Priority: P2)

**Goal**: **`F(t)`** piecewise Poisson scaling per [retail-intensity-006.md](./contracts/retail-intensity-006.md) + [cli-match-day-flags-006.md](./contracts/cli-match-day-flags-006.md); **FR-006** flags and **`--help`**.

**Independent Test**: Fixed **`--seed`** + bounded **`--max-events`**: **home match day** `retail_purchase` count (or rate proxy) **>** off-days + away-only (away boost off) by **≥ MIN_HOME_VS_NONHOME_RETAIL_RATIO** from contract.

### Tests for User Story 2

- [X] T012 [P] [US2] Add `tests/test_stream_match_day_retail_006.py`: golden calendar fixture under `tests/fixtures/` or reuse `calendars/` — assert retail ratio **≥** threshold constant documented beside test (align with [retail-intensity-006.md](./contracts/retail-intensity-006.md))
- [X] T013 [P] [US2] Add unit tests for `F(t)` / away-enable / home kickoff window edges in `tests/test_retail_intensity_006.py` against builder implemented in `src/fan_events/v3_retail.py` or `src/fan_events/retail_intensity.py`

### Implementation for User Story 2

- [X] T014 [US2] Register **FR-006** argparse flags (defaults **2.0**, **90**, **120**, **1.5**, away enable **false**, away mult **1.75**) and validation errors in `src/fan_events/cli.py` `parse_args` for subcommand **`stream`**
- [X] T015 [US2] Implement **`RetailIntensitySchedule`** (class) or pure functions in new `src/fan_events/retail_intensity.py` building **`F(t)`** from filtered `MatchContext` list / pass index per [data-model.md](./data-model.md)
- [X] T016 [US2] Extend `iter_retail_records` in `src/fan_events/v3_retail.py` with **`rate_factor_fn: Callable[[datetime], float] | None`** (or equivalent) so inter-arrival uses **`λ_eff = poisson_rate * F(t)`** while preserving RNG **draw order** contract in module docstring
- [X] T017 [US2] In `run_stream` (`src/fan_events/cli.py`), construct schedule from calendar contexts, align **`--epoch`** with master timeline per [research.md](./research.md) §3, pass **`rate_factor_fn`** into retail iterator when merged+calendar
- [X] T018 [US2] Update **`EPILOG_STREAM`** / help strings in `src/fan_events/cli.py` explaining **home vs away-only days**, **kickoff window**, and each **FR-006** flag (plain language, **SC-005**)

**Checkpoint**: US2 verifiable via T012–T013 green.

---

## Phase 5: User Story 3 — Output paths parity (Priority: P3)

**Goal**: **stdout**, **append file**, **Kafka** behave as **004**; any gap **explicitly documented**.

**Independent Test**: Same **`--max-events`** run to **`-o` file** vs **stdout** capture — identical bytes (given same sink flush semantics); Kafka path uses same merged iterator + caps when dependency present.

### Tests for User Story 3

- [X] T019 [P] [US3] Extend or add `tests/test_stream_output_paths_006.py`: stdout vs append file byte match for fixed **seed** + **caps** via `src/fan_events/cli.py` `run_stream` path (subprocess or in-process as existing tests do)

### Implementation for User Story 3

- [X] T020 [US3] Audit `_run_stream_kafka` in `src/fan_events/cli.py` vs `write_merged_stream` in `src/fan_events/orchestrator.py` — ensure **`t0_anchor`**, **`max_events`**, **`max_duration_seconds`** parity; fix mismatches
- [X] T021 [US3] If Kafka cannot meet parity in this PR, add explicit **scope gap** bullet under **Assumptions** in `specs/006-stream-three-event-kinds/spec.md` and one line in `README.md`

**Checkpoint**: US3 documented + T019 green.

---

## Phase 6: Polish & cross-cutting

**Purpose**: Merge invariant, **ruff**, **004/006** doc cross-links, **README**, **PR outline**.

- [X] T022 [P] Add `tests/test_stream_merge_order_006.py`: scan **≥1000** consecutive lines from merged iterator (`src/fan_events/orchestrator.py` + fixtures) asserting `merge_key_tuple(rec[i]) <= merge_key_tuple(rec[i+1])` per `specs/004-unified-synthetic-stream/contracts/orchestrated-stream.md` (**SC-002**)
- [X] T023 Run **`uv run ruff check src tests`** and fix all issues in touched paths (`src/fan_events/*.py`, new tests)
- [X] T024 [P] Patch `specs/004-unified-synthetic-stream/contracts/cli-stream.md` to reference `specs/006-stream-three-event-kinds/contracts/cli-stream-006-supplement.md` (default loop + `t0` duration)
- [X] T025 [P] Update root `README.md` **`fan_events stream`** subsection with link to `specs/006-stream-three-event-kinds/quickstart.md` and one sentence on **master clock** + **match-day retail**
- [X] T026 [P] Create `specs/006-stream-three-event-kinds/pr-outline.md` with **PR title**, **summary bullets** (master clock model, calendar-year loop, FR-006 flags, `t0` + `--max-duration`, test coverage), and **reviewer checklist**
- [X] T027 [P] Optional **FR-010** golden: commit a small **fixed-seed** NDJSON fixture under `tests/fixtures/` and assert **byte-identical** stdout vs `-o` file (or document skip in **pr-outline.md** if deferred)

---

## Dependencies & execution order

### Phase dependencies

| Phase | Depends on | Blocks |
|-------|------------|--------|
| **1** Setup | — | — |
| **2** Foundational | T001 | US1–US3 |
| **3** US1 | T002–T007 | MVP demo |
| **4** US2 | T002–T007 | Full spec FR-005/006 |
| **5** US3 | T002–T007 (T020 ideally after T005–T006) | Operator parity story |
| **6** Polish | desired stories done | Merge |

### User story dependencies

- **US1**: Needs **calendar-year loop** (T002–T003), **`t0` duration** (T004–T007), retail unbounded default (T010).
- **US2**: Needs **US1** retail iterator still merged (or parallel after T016 if schedule stub returns `F=1` initially); practically **T016–T017** after **T002–T007**.
- **US3**: Needs **T005–T006** before **T020** for Kafka/`t0` parity.

### Parallel examples

```text
# After T002 done:
T008 [US1] calendar loop tests  ||  T012 [US2] retail ratio test file scaffold

# After T015 done:
T013 [US2] F(t) unit tests  ||  T018 [US2] help text updates (same file cli.py — serialize if conflict)

# Polish:
T024 004 cli-stream patch  ||  T025 README  ||  T026 pr-outline  ||  T027 golden (optional)
```

---

## Implementation strategy

### MVP (US1 only)

1. T001 → T007 (foundation)
2. T008–T011 (US1)
3. **STOP**: demo infinite stream + caps

### Full feature

1. Foundation T001–T007
2. US1 T008–T011
3. US2 T012–T018
4. US3 T019–T021
5. Polish T022–T027

---

## Task summary

| Phase | Task IDs | Count |
|-------|----------|-------|
| Setup | T001 | 1 |
| Foundational | T002–T007 | 6 |
| US1 | T008–T011 | 4 |
| US2 | T012–T018 | 7 |
| US3 | T019–T021 | 3 |
| Polish | T022–T027 | 6 |
| **Total** | **T001–T027** | **27** |

**Parallel tasks**: T001, T008, T012, T013, T019, T022, T024, T025, T026, T027 (subject to file conflicts — **cli.py** tasks T009–T018 should be serialized or merged in one branch).

**MVP scope**: **T001–T011** + **T023** (ruff on touched code).
