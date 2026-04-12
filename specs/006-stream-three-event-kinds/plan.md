# Implementation Plan: Continuous unified stream (master clock + match-day retail)

**Branch**: `006-stream-three-event-kinds` | **Date**: 2026-04-12 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/006-stream-three-event-kinds/spec.md` (clarified 2026-04-12).

## Summary

Extend **`fan_events stream`** so merged mode emits **`ticket_scan`**, **`merch_purchase`**, and **`retail_purchase`** in **one** NDJSON stream, **non-decreasing** per [`orchestrated-stream.md`](../004-unified-synthetic-stream/contracts/orchestrated-stream.md). **Calendar-driven v2** cycles **forever** with **+1 calendar year** per season pass. **Retail** uses the **same** advancing synthetic clock with **piecewise Poisson rate** from **FR-006** flags ([`contracts/cli-match-day-flags-006.md`](./contracts/cli-match-day-flags-006.md)). Reuse **`v2_calendar`**, **`v3_retail`**, **`orchestrator`**, **`ndjson_io`**, **`merge_keys`**. Align **`--max-duration`** with **006** **`t0`** semantics; patch **004** docs or cross-link **006** supplements to avoid drift.

## Technical Context

**Language/Version**: Python **3.12+** (`pyproject.toml` `requires-python`)  
**Primary Dependencies**: **stdlib** runtime for generator/CLI; optional **`confluent-kafka`** for Kafka extra (existing **004** pattern)  
**Storage**: NDJSON **stdout**, **append-only file**, or **Kafka** (optional)  
**Testing**: **pytest**, **ruff** (`uv run pytest`, `uv run ruff check src tests`)  
**Target Platform**: Cross-platform (Windows/Linux/macOS) CLI  
**Project Type**: Python package **`fan_events`** under `src/`  
**Performance Goals**: Streaming merge **O(log k)** heap state over **k** v2 partitions + retail; no full materialization of unbounded streams  
**Constraints**: Constitution **VI** stdlib-only core; **byte-identical** output for fixed seed + bounded caps where spec applies  
**Scale/Scope**: Long-running demos; calendars with tens–hundreds of matches per pass; unbounded retail events until caps/interrupt

## Constitution Check

*GATE: Passed — no new non-stdlib runtime deps for core path; dbt/analytics not in scope for this generator feature.*

| Principle | Status |
|-----------|--------|
| **I–III** (marts, raw, dbt tests) | **N/A** for this CLI slice — no new warehouse models; raw remains append-only at ingest story level |
| **IV–V** (demo path, shipped slice) | **Met** — extends existing **event → file/Kafka** demo |
| **VI** (UV, stdlib, TDD) | **Met** — plan uses stdlib; tests via pytest; `uv` for runs |
| **VII–XI** (specs, reproducibility, contracts, UTC `Z`) | **Met** — `spec.md` + `contracts/`; `research.md` addresses anchors; timestamps UTC `Z` |
| **XIII** (OOP vs functions) | **Met** — small **classes** acceptable for **calendar shift + retail intensity schedule**; keep **merge** functional |

**Post-design**: Contracts under `specs/006-stream-three-event-kinds/contracts/` mirror **FR-006**; supplements document **`t0`** and default loop.

## Project Structure

### Documentation (this feature)

```text
specs/006-stream-three-event-kinds/
├── plan.md              # This file
├── research.md          # Phase 0
├── data-model.md        # Phase 1
├── quickstart.md        # Phase 1
├── contracts/           # Phase 1
│   ├── cli-match-day-flags-006.md
│   ├── retail-intensity-006.md
│   ├── cli-stream-006-supplement.md
│   └── orchestrated-stream-006-note.md
└── tasks.md             # Phase 2 — created by /speckit.tasks (NOT in this step)
```

### Source code (expected touchpoints)

```text
src/fan_events/
├── cli.py                 # stream subparser: new flags; default loop; epoch/t0 wiring
├── v2_calendar.py         # calendar-year shift; loop iterator (replace/adjust timedelta loop)
├── v3_retail.py           # time-varying Poisson rate (factor(t)); keep RNG discipline
├── orchestrator.py       # write_merged_stream: max_duration anchor t0
├── merge_keys.py         # unchanged unless tie testing reveals gaps
└── ndjson_io.py          # unchanged (formats)

tests/
├── test_stream_*.py       # extend / add merge + loop + retail ratio tests
└── ...
```

**Structure Decision**: Single package **`fan_events`**; feature is a **vertical slice** on existing modules—**no** new top-level package.

## Complexity Tracking

*Empty — no constitution violations requiring justification.*

## Phase 0: Research

**Output**: [research.md](./research.md)

**Resolved decisions** (headlines):

1. **Calendar-year** shift (stdlib leap handling), not fixed **365d** only.
2. **Default** infinite calendar on **`stream --calendar`** with explicit opt-out.
3. **Master clock** + retail **`λ_eff = R_base × F(t)`**.
4. **`t0`** for **`--max-duration`** vs first-emitted line — **spec-aligned fix**.
5. **Belgian / Jan Breydel** citations for **bounded** rationale of default windows (Club Brugge official page).
6. **Test strategy**: fixed-seed ratio tests, loop boundary tests, monotonic merge tests.

## Phase 1: Design & contracts

**Outputs**:

- [data-model.md](./data-model.md) — timeline, entities, classification rules.
- [contracts/cli-match-day-flags-006.md](./contracts/cli-match-day-flags-006.md) — verbatim **FR-006**.
- [contracts/retail-intensity-006.md](./contracts/retail-intensity-006.md) — **`F(t)`**, overlaps, SC-003 threshold placeholder.
- [contracts/cli-stream-006-supplement.md](./contracts/cli-stream-006-supplement.md) — **004** `cli-stream` deltas (**loop default**, **`t0`**).
- [contracts/orchestrated-stream-006-note.md](./contracts/orchestrated-stream-006-note.md) — **K1–K3** unchanged.
- [quickstart.md](./quickstart.md) — operator examples.

**Agent context**: Run `.\.specify\scripts\powershell\update-agent-context.ps1 -AgentType cursor-agent` after committing docs (see command log).

## Phase 2: Implementation task generation (outline only)

**`tasks.md` is NOT produced by `/speckit.plan`.** Run **`/speckit.tasks`** next; suggested task groups:

1. **v2 calendar-year loop**: refactor **`shift_match_context` / `iter_looped_v2_records`**; **`--no-calendar-loop`**; tests for **+1y** and **Feb 29**.
2. **Retail `F(t)`**: extend **`iter_retail_records`** (or wrapper) with **callable factor**; wire **calendar + passes** into classifier; tests for **home > off** with fixed seed.
3. **CLI**: add **FR-006** arguments + validation; update **`--help`** / epilog.
4. **Orchestrator**: fix **`write_merged_stream`** **`t0`** for **`--max-duration`**; add regression tests vs **006** supplement.
5. **Integration**: **`stream`** end-to-end with **`--max-events`** across **≥2** passes; **Kafka** smoke optional.
6. **Docs**: patch **`specs/004-.../contracts/cli-stream.md`** to reference **006** supplement (or inline equivalent).
7. **README** minimal pointer (per spec deliverables).

## Contract impacts (004 vs 006)

| Artifact | Action |
|----------|--------|
| [`cli-stream.md`](../004-unified-synthetic-stream/contracts/cli-stream.md) | **Patch** or add **“See 006 supplement”** for default loop + **`t0`** duration |
| [`orchestrated-stream.md`](../004-unified-synthetic-stream/contracts/orchestrated-stream.md) | **No merge-key change** — [orchestrated-stream-006-note.md](./contracts/orchestrated-stream-006-note.md) |
| **v2 / v3 NDJSON contracts** | **No field shape changes** |

## Test strategy (architecture)

| Concern | Approach |
|---------|----------|
| **Infinite / lapped calendar** | **`--max-events`** bounded runs; assert **monotonic** `kickoff_utc` across cycles; **`match_id`** uniqueness pattern |
| **Timestamps / order** | **`merge_key_tuple`** on capped streams; optional **byte** golden files with **`--seed`** |
| **Retail uplift** | Count **`retail_purchase`** on **home match days** vs **away-only + no-fixture** days over **equal simulated wall time**; assert **ratio ≥ contract threshold** ([retail-intensity-006.md](./contracts/retail-intensity-006.md)) |

## Stop / report

- **Branch**: `006-stream-three-event-kinds`
- **Plan**: `specs/006-stream-three-event-kinds/plan.md`
- **Generated**: `research.md`, `data-model.md`, `quickstart.md`, `contracts/*` (4 files)
- **Not generated**: `tasks.md` (use **`/speckit.tasks`**)
- **Suggested next command**: **`/speckit.tasks`** — *Break the plan into tasks*
