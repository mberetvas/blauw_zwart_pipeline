# Implementation Plan: Synthetic fan event source

**Branch**: `001-synthetic-fan-events` | **Date**: 2026-04-04 | **Spec**: [spec.md](./spec.md)  
**Input**: Feature specification from `/specs/001-synthetic-fan-events/spec.md`  
**Plan input**: Single Python script under `scripts/`, stdlib only, `argparse` CLI; NDJSON fields as specified; ~90-day window; configurable count, output path, optional seed.

## Summary

Deliver a **demo-grade synthetic fan event generator** that writes **UTF-8 NDJSON** to a **filesystem path**
with **byte-identical reproducibility** when `--seed` is fixed, **global time ordering**, **fail-fast**
behavior, and **atomic replace** of the output file. The normative **data contract** lives under
`specs/001-synthetic-fan-events/contracts/` and is referenced from **quickstart**. This slice is **raw
landing only**; **dbt marts** (`fct_ticket_scans`, `fct_merch_purchases`) are **planned consumers** in a
later milestone (no dbt project in repo yet).

## Technical Context

**Language/Version**: Python 3.12+ (matches `pyproject.toml` `requires-python`)  
**Primary Dependencies**: **None** beyond the Python standard library for the generator script  
**Storage**: Local NDJSON file (default `out/fan_events.ndjson` relative to current working directory)  
**Testing**: Manual / scripted smoke: run CLI twice with same `--seed`, `fc` / `cmp` / PowerShell
`Compare-Object` for byte identity; optional small `unittest` module in repo later (not required for
this plan’s artifacts)  
**Target Platform**: Windows, Linux, macOS (path handling via `pathlib`)  
**Project Type**: CLI utility script (repository `scripts/` layout)  
**Performance Goals**: Demo-scale (thousands of lines); single-pass in-memory sort acceptable  
**Constraints**: Stdlib only; no third-party packages in the generator; `argparse` CLI; FR-008 atomic write
**Scale/Scope**: Single file per run; configurable event count (default large enough to include both
event types per FR-006)

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Gate | Status | Notes |
|------|--------|--------|
| Analytics / `fct_*` `dim_*` named for downstream | **Pass** | Spec FR-WH-001: consumers **`fct_ticket_scans`**, **`fct_merch_purchases`**; this delivery is **raw NDJSON** only, no mart logic in Python. |
| Raw append-only / no enrichment in generator | **Pass** | Script emits immutable facts-as-JSON lines; no updates to prior files. |
| dbt tests (`not_null`, `unique`, business rules) | **Deferred** | No dbt project in repository yet; **follow-up** adds staging/marts + tests + CI. This slice does not block on dbt. |
| Demonstrable **event → raw → marts** | **Partial → Pass for slice** | **event → raw file** implemented here; **marts** documented as next step in plan summary and contract. |
| Demo-first | **Pass** | Minimal vertical slice: one script + contract + quickstart. |

**Post–Phase 1 re-check**: Unchanged; dbt/CI remains explicitly **out of scope** for this feature’s
implementation deliverable, with named target facts for the next increment.

## Project Structure

### Documentation (this feature)

```text
specs/001-synthetic-fan-events/
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/
│   └── fan-events-ndjson-v1.md
└── tasks.md              # Phase 2: /speckit.tasks (not created here)
```

### Source Code (repository root)

```text
scripts/
└── generate_fan_events.py    # Single module: CLI + generation + canonical JSON + atomic write

out/                          # Default output directory (created on demand; gitignored in implement)
    fan_events.ndjson         # Default filename when --output not passed
```

**Structure Decision**: One stdlib-only script under `scripts/` per user direction; no `src/` package
dependency required for the generator (keeps demo friction low). The existing `src/blauw_zwart_*`
package remains unrelated unless later wired as a thin wrapper.

## Complexity Tracking

> Constitution **CI runs `dbt test`**: not applicable until a dbt project exists. This row documents the
> intentional gap for this slice.

| Item | Why needed | Simpler alternative rejected because |
|------|------------|-------------------------------------|
| No dbt in this PR | Spec allows marts in a later phase; repo has no warehouse/dbt yet | Skipping the generator would remove the demonstrable **event** side of the pipeline |

## Constitution follow-up (repo-wide)

`.specify/memory/constitution.md` requires **CI** to run **`dbt test`** (or an equivalent documented
command) on the **main integration path**. That obligation is **not met** until the repository adds a
dbt project plus a CI workflow. This feature’s deliverable is intentionally **raw-only**; treat
**dbt + CI** as the **next milestone** before claiming full constitution compliance for the end-to-end
pipeline. Until then, reviewers should rely on this section and **Complexity Tracking** above as the
recorded deferral.

## Phase 0 · Research

Consolidated in [research.md](./research.md) (decisions only; no open NEEDS CLARIFICATION).

## Phase 1 · Design artifacts

- [data-model.md](./data-model.md) — logical entities and validation rules  
- [contracts/fan-events-ndjson-v1.md](./contracts/fan-events-ndjson-v1.md) — normative NDJSON contract  
- [quickstart.md](./quickstart.md) — run and verify reproducibility  

Agent context updated via `.specify/scripts/powershell/update-agent-context.ps1 -AgentType cursor-agent`.
