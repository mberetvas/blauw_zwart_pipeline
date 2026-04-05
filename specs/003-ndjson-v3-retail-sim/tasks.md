# Tasks: NDJSON v3 retail shop simulation

**Input**: Design documents from `/specs/003-ndjson-v3-retail-sim/`  
**Prerequisites**: [`plan.md`](plan.md), [`spec.md`](spec.md), [`data-model.md`](data-model.md), [`contracts/fan-events-ndjson-v3.md`](contracts/fan-events-ndjson-v3.md), [`research.md`](research.md), [`quickstart.md`](quickstart.md)

**Tests**: TDD where noted; **`uv run pytest`** from repo root; **`ruff check .`** on touched Python. No dbt scope unless a follow-up feature adds models.

**Organization**: Phases follow **contract + domain + `ndjson_io` → generator → CLI → docs → quality gate**. User story labels map to [`spec.md`](spec.md) priorities (P1–P3).

## Format

- **`[P]`** = parallelizable (different files, no incomplete upstream dependency).
- **`[USn]`** = user story from spec.

---

## Phase 1: Setup (branch & doc readiness)

**Purpose**: No code until paths and contracts are aligned with the repo.

- [x] T001 Verify feature artifacts exist and match implementation targets (`specs/003-ndjson-v3-retail-sim/contracts/fan-events-ndjson-v3.md`, [`plan.md`](plan.md) module list).
  - **Goal**: Confirm normative contract path and filenames before editing code.
  - **Files**: Read-only review of `specs/003-ndjson-v3-retail-sim/` tree.
  - **Acceptance**: `contracts/fan-events-ndjson-v3.md` present; plan names `v3_retail.py`, `ndjson_io` extensions, `domain.py` constants.

---

## Phase 2: Foundational (contract examples + domain + NDJSON v3 I/O)

**Purpose**: Shared constants and **`ndjson_io`** primitives **block** generator and CLI work.

- [x] T002 Append **Examples** subsection to `specs/003-ndjson-v3-retail-sim/contracts/fan-events-ndjson-v3.md`: one **valid** `retail_purchase` line (canonical JSON) and **≥3 invalid** cases (extra key, wrong `shop`, missing `amount`) with brief rationale each.
  - **Goal**: Give humans and tests a single source for “good vs bad” lines without reading Python.
  - **Files**: `specs/003-ndjson-v3-retail-sim/contracts/fan-events-ndjson-v3.md`
  - **Acceptance**: Valid example parses as JSON and matches closed schema; invalid examples are explicitly rejected by the rules stated in the same contract.

- [x] T003 Add retail constants and helpers to `src/fan_events/domain.py`: `RETAIL_PURCHASE`, `SHOP_IDS` (ordered tuple), `SHOP_DISPLAY_NAME` mapping, `DEFAULT_SHOP_WEIGHTS` (aligned to `SHOP_IDS`, sum 1.0), `DEFAULT_RETAIL_SIM_EPOCH_UTC`; add `validate_shop_weights(weights: Sequence[float]) -> None` raising `ValueError` on negative / wrong length / zero-sum (per spec: fail on bad explicit input).
  - **Goal**: Named domain constants (constitution XII); single place for shop ids and default mixture.
  - **Files**: `src/fan_events/domain.py`
  - **Acceptance**: Imports succeed; weights `(1/3, 1/3, 1/3)` validate; wrong-length raises; no literals scattered in generator for shop ids.

- [x] T004 Extend `src/fan_events/ndjson_io.py` with `validate_record_v3`, `sort_key_v3`, and `records_to_ndjson_v3` per `contracts/fan-events-ndjson-v3.md` (closed keys, `item` ∈ `ITEMS`, `shop` ∈ `SHOP_IDS`, amount rules mirror v1 merch).
  - **Goal**: Contract enforcement and batch global sort identical to v1/v2 patterns.
  - **Files**: `src/fan_events/ndjson_io.py` (import `RETAIL_PURCHASE`, `ITEMS`, `SHOP_IDS` from `domain` as needed)
  - **Acceptance**: Empty list → `""`; non-empty → sorted lines, trailing `\n`; validation rejects invalid dicts with clear `ValueError`.

- [x] T005 [P] Add `tests/test_ndjson_v3_io.py`: unit tests for `validate_record_v3`, `sort_key_v3`, and `records_to_ndjson_v3` using **hand-built** dicts (no generator yet). **`validate_record_v3` MUST cover every normative rejection path**, including: **extra key**; **wrong `event`** (not `retail_purchase`); **missing required key**; **empty `fan_id`**; **`item`** not in `ITEMS`; **bad `shop`**; **`amount` ≤ 0**; **`timestamp`** without **`Z`** suffix or otherwise invalid vs contract. **`sort_key_v3` / `records_to_ndjson_v3`**: include at least one **tie** case (same `timestamp`, differ on later tuple fields) proving **total** batch order.
  - **Goal**: Lock I/O contract before `v3_retail.py` exists (addresses spec FR-SC-003 / FR-SC-005 and contract §Record shape).
  - **Files**: `tests/test_ndjson_v3_io.py`, `src/fan_events/ndjson_io.py` (fix only if tests expose bugs)
  - **Acceptance**: `uv run pytest tests/test_ndjson_v3_io.py` passes; a reviewer can trace each bullet above to a named test or parametrized case.

**Checkpoint — foundation**: Domain + NDJSON v3 helpers tested in isolation.

---

## Phase 3: User Story 1 (P1) — Reproducible retail NDJSON **file** (batch)

**Goal**: Single sorted NDJSON file, byte-identical with fixed `--seed`, empty file = zero bytes.

**Independent test**: Two batch runs with same seed/args → identical file bytes; `records` validate against v3 contract.

### Implementation

- [x] T006 [US1] Add `src/fan_events/v3_retail.py`: build `retail_purchase` dicts via a small `make_retail_purchase(...)` helper; implement **`generate_retail_batch`→`list[dict]`** using `DEFAULT_RETAIL_SIM_EPOCH_UTC`, default **Poisson** inter-arrival (`random.Random.expovariate`), default **equal** shop weights from `domain`, **`ITEMS`** for items, fan pool pattern consistent with `v1_batch.py`. Support stopping by **`max_events`** and, per **FR-009** / contract, optional **maximum simulated duration** (elapsed synthetic time from **epoch** along the generated timeline). When **both** `max_events` and max simulated duration are set, stop when **either** bound is hit first (**whichever comes first**); when only one is set, use that bound.
  - **Goal**: Deterministic batch list suitable for `records_to_ndjson_v3`; aligns with spec **FR-009** (not stub-only duration).
  - **Files**: `src/fan_events/v3_retail.py`, `src/fan_events/domain.py` (only if new helpers needed)
  - **Acceptance**: With fixed `random.Random(seed)`, repeated calls return identical `list[dict]`; timestamps non-decreasing; only `retail_purchase` rows; duration-only and events-only stops behave as documented in module docstring.

- [x] T007 [US1] Wire batch output helper: function that returns **NDJSON string** via `records_to_ndjson_v3` for use by CLI (e.g. `retail_ndjson_text = records_to_ndjson_v3(records)` in `run_v3` or thin wrapper in `v3_retail.py`).
  - **Goal**: Single path for on-disk writing with atomic semantics.
  - **Files**: `src/fan_events/v3_retail.py` and/or `src/fan_events/cli.py` (thin; prefer keeping pure generation in `v3_retail.py`)
  - **Acceptance**: Empty batch → `""` from `records_to_ndjson_v3`; non-empty → ends with single `\n`.

### Tests (User Story 1)

- [x] T008 [US1] Add `tests/test_v3_retail_batch.py`: **byte-identical** file contents for two invocations with same seed + params; **empty** output when `max_events==0` (or equivalent); lines globally sorted by verifying monotonic `sort_key_v3` order after parse **or** compare to deterministic snapshot.
  - **Goal**: FR-SC-002 batch path locked.
  - **Files**: `tests/test_v3_retail_batch.py`, optional `tests/fixtures/retail_v3_golden.ndjson`
  - **Acceptance**: `uv run pytest tests/test_v3_retail_batch.py` passes; optional golden file committed if team wants regression diff.

- [x] T019 [US1] Add **optional** large-batch coverage for **SC-003** (e.g. `@pytest.mark.slow` or separate `tests/test_v3_retail_batch_large.py`): with fixed **seed**, generate **≥ 50,000** lines via `generate_retail_batch` + `records_to_ndjson_v3`, assert **line count**, **global sort order** (parsed `sort_key_v3` non-decreasing), and **valid** `validate_record_v3` per line—**no** performance SLA required (demo / laptop-scale).
  - **Goal**: Map spec SC-003 to an automated or opt-in check; operators can run `pytest -m slow` in CI if desired.
  - **Files**: `tests/test_v3_retail_batch.py` (markers) or `tests/test_v3_retail_batch_large.py`
  - **Acceptance**: Default `uv run pytest` may **exclude** slow tests if marked; documented in `pytest.ini` or task comment; when run, test passes on dev hardware.

**Checkpoint — US1**: Batch retail NDJSON file mode demonstrable without CLI (tests call `v3_retail` + `records_to_ndjson_v3`).

---

## Phase 4: User Story 2 (P2) — Shop mixture + arrival tuning

**Goal**: Explicit shop weights and **fixed** / **weighted** inter-arrival modes where spec requires; invalid weights error.

**Independent test**: Changing only weights or arrival parameters changes output deterministically; bad weights raise.

### Implementation

- [x] T009 [US2] Extend `src/fan_events/v3_retail.py`: parse **explicit** weight triple (CLI-driven) through `validate_shop_weights`; implement **fixed** interval and **weighted** gap schedule per [`research.md`](research.md); keep **Poisson** as default path; document RNG draw order in module docstring for reproducibility debugging.
  - **Goal**: US2 acceptance scenarios for mixture and arrival variety.
  - **Files**: `src/fan_events/v3_retail.py`
  - **Acceptance**: Same seed + same params → same records; invalid weights → `ValueError` before generation.

### Tests (User Story 2)

- [x] T010 [P] [US2] Add `tests/test_v3_retail_arrival_weights.py`: assert different output when weights differ with same seed; assert invalid weights raise; fixed-rate spacing produces expected min gap between timestamps (within floating tolerance documented in test).
  - **Goal**: Prevent silent normalization of bad weights; lock arrival modes.
  - **Files**: `tests/test_v3_retail_arrival_weights.py`
  - **Acceptance**: `uv run pytest tests/test_v3_retail_arrival_weights.py` passes.

**Checkpoint — US2**: Operator-tunable realism without breaking US1 tests.

---

## Phase 5: User Story 3 (P3) — Stream mode (stdout, generation order)

**Goal**: Line-at-a-time **stdout**, non-decreasing timestamps, **byte-identical** stdout when `--seed` fixed; **zero events → zero stdout bytes**.

**Independent test**: Stream twice with same seed → identical bytes; length &gt; 0 ends with newline; zero events no bytes.

### Implementation

- [x] T011 [US3] Implement stream emission in `src/fan_events/v3_retail.py` (or `cli.py` if thin): iterate generation order, **`validate_record_v3`** + **`dumps_canonical` + `"\n"`** per line; **no** global sort; share serialization with batch via `dumps_canonical` from `ndjson_io`.
  - **Goal**: FR-008 stream semantics; stream bytes match “would concatenate same lines in order.”
  - **Files**: `src/fan_events/v3_retail.py`, possibly `src/fan_events/ndjson_io.py` (add `format_line_v3` if deduping)
  - **Acceptance**: Zero records → no writes; N&gt;0 → POSIX line stream with trailing `\n` on last line only.

### Tests (User Story 3)

- [x] T012 [P] [US3] Add `tests/test_v3_retail_stream.py`: duplicate stdout bytes with same seed; assert `timestamp` non-decreasing when parsing lines; zero-event stream empty.
  - **Goal**: Byte identity for stream per clarifications.
  - **Files**: `tests/test_v3_retail_stream.py`
  - **Acceptance**: `uv run pytest tests/test_v3_retail_stream.py` passes.

**Checkpoint — US3**: Stream and batch both covered by tests.

---

## Phase 6: CLI — `generate_retail` + mutual exclusion

**Purpose**: Operator-facing entrypoint matching `generate_events` patterns (`src/fan_events/cli.py`).

- [x] T013 Extend `src/fan_events/cli.py`: add subparser **`generate_retail`** with **`--seed`**, **`--output`** (file mode), **`--stream`** (or mutually exclusive stdout), **`--max-events`**, **`--max-duration`** (or equivalent name for **maximum simulated duration** in seconds—aligned with **T006**), optional **epoch** override, **shop weight** triple, **arrival mode** + **rate** params per plan; implement **`run_v3`** calling `v3_retail` + `write_atomic_text` or stdout; **`parse_args`**: **reject** combining `generate_retail` with `generate_events` rolling (`-n`/`--days`) or calendar (`--calendar`, `--from-date`, …) using the same style as existing calendar vs rolling checks (`_tokens_for_flag_checks` / `parser.error`). Document **whichever-first** when both `--max-events` and duration cap are set.
  - **Goal**: Clear mode separation mirroring v1 vs v2; **FR-009** satisfied (seed, arrival, max events **and/or** simulated duration, weights, epoch, file vs stream, output).
  - **Files**: `src/fan_events/cli.py`, `src/fan_events/__main__.py` (only if dispatch needs export)
  - **Acceptance**: `uv run python -m fan_events generate_retail --help` lists duration and max-events; invalid combinations exit **2** with message to stderr; success writes file or stdout only.

- [x] T014 [P] Add `tests/test_cli_retail.py`: subprocess or in-process `main([...])` for **mutual exclusion** errors; smoke test **file** and **stream** with tmp path / `capsys` for stdout.
  - **Goal**: CLI smoke + error messages consistent with existing `fan_events` style.
  - **Files**: `tests/test_cli_retail.py`
  - **Acceptance**: `uv run pytest tests/test_cli_retail.py` passes; v1/v2 tests still pass.

---

## Phase 7: Documentation & quality gates

**Purpose**: Quickstart truth + repo convention + lint/test sweep.

- [x] T015 [P] Update `specs/003-ndjson-v3-retail-sim/quickstart.md` so examples match **implemented** flag names and `uv run python -m fan_events generate_retail …`; remove “after implementation” placeholder language where obsolete.
  - **Goal**: Executable quickstart for reviewers.
  - **Files**: `specs/003-ndjson-v3-retail-sim/quickstart.md`
  - **Acceptance**: Every documented command matches `cli.py` behavior.

- [x] T016 [P] Update root `README.md` with one short subsection or bullet linking to `specs/003-ndjson-v3-retail-sim/quickstart.md` for v3 retail (minimal diff; mirror 002 pattern if present).
  - **Goal**: Discoverability from repo landing page.
  - **Files**: `README.md`
  - **Acceptance**: Link resolves; describes v3 retail in one sentence.

- [x] T017 Run `ruff check .` from repo root on `src/fan_events/`, `tests/`; fix issues introduced by this feature.
  - **Goal**: Lint clean on touched code.
  - **Files**: Touched Python files
  - **Acceptance**: `ruff check .` exits 0.

- [x] T018 Run `uv run pytest` from repo root; fix failures until full suite green.
  - **Goal**: Constitution pytest gate.
  - **Files**: All tests
  - **Acceptance**: All tests pass.

---

## Dependencies & execution order

### Phase dependencies

| Phase | Depends on |
|-------|------------|
| Phase 1 (T001) | — |
| Phase 2 (T002–T005) | T001 optional; T003 depends on T002 domain constants; T005 depends on T003 |
| Phase 3 US1 (T006–T008, T019) | T002–T005 complete |
| Phase 4 US2 (T009–T010) | T006–T007 complete (T019 optional after T008) |
| Phase 5 US3 (T011–T012) | T006–T007 complete (stream reuses generation core) |
| Phase 6 (T013–T014) | T006–T012 (CLI needs batch + stream paths) |
| Phase 7 (T015–T018) | Feature code complete |

### User story dependencies

| Story | Depends on |
|-------|------------|
| **US1** | Foundational Phase 2 |
| **US2** | US1 batch generator skeleton (T006–T007) |
| **US3** | Generation core (T006–T007); can parallelize tests with US2 after T007 |

### Parallel opportunities

- **T005** `[P]` after **T003–T004** land (tests can precede full generator if using hand-built dicts—already true for T004).
- **T010** `[P]` and **T012** `[P]` after shared core (**T007**) stable.
- **T014** `[P]` after **T013** CLI exists.
- **T015** `[P]` and **T016** `[P]` in parallel during doc polish.
- **T017** and **T018** sequential (lint then full pytest).

### Parallel example (after Phase 2)

```text
# After T003–T004 land, run in parallel:
- T005 [P]  tests/test_ndjson_v3_io.py  (I/O tests)
# T006–T007 must stay sequential (generator before batch wire).

# After T007 lands, run in parallel:
- T010 [P] [US2]  tests/test_v3_retail_arrival_weights.py
- T012 [P] [US3]  tests/test_v3_retail_stream.py   (if stream impl T011 is done)

# After T013 lands:
- T014 [P]  tests/test_cli_retail.py
- T015 [P]  quickstart.md
- T016 [P]  README.md
```

---

## Implementation strategy

### MVP (User Story 1 only)

1. Complete Phase 2 (T001–T005).
2. Complete Phase 3 (T006–T008) — batch file + tests; add **T019** when ready for SC-003 load check (optional).
3. Stop and demo **`records_to_ndjson_v3`** + **`v3_retail`** without full CLI if needed internally.

### Incremental delivery

1. Add US2 (T009–T010) — weights + arrival modes.
2. Add US3 (T011–T012) — stream.
3. Add CLI (T013–T014) — operator-ready.
4. Docs + gates (T015–T018).

---

## Notes

- **PR granularity**: Each task should be one PR or one commit series with a green pytest subset before merge.
- **Golden fixtures**: Optional `tests/fixtures/retail_v3_golden.ndjson` only if team wants file diff in CI (**T008**).
- **Kafka**: No code tasks; partitioning notes already in [`plan.md`](plan.md).

---

## Task summary

| Metric | Value |
|--------|-------|
| **Total tasks** | **19** (T001–T019) |
| **US1** | T006–T008, T019 (4) |
| **US2** | T009–T010 (2) |
| **US3** | T011–T012 (2) |
| **Foundational** | T001–T005 (5) |
| **CLI** | T013–T014 (2) |
| **Polish** | T015–T018 (4) |

**Suggested MVP scope**: Phase 2 + Phase 3 (T001–T008) — reproducible batch NDJSON without full CLI polish.
