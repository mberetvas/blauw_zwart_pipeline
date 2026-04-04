# Implementation Plan: [FEATURE]

**Branch**: `[###-feature-name]` | **Date**: [DATE] | **Spec**: [link]
**Input**: Feature specification from `/specs/[###-feature-name]/spec.md`

**Note**: This template is filled in by the `/speckit.plan` command. See `.specify/templates/plan-template.md` for the execution workflow.

## Summary

[Extract from feature spec: primary requirement + technical approach from research]

## Technical Context

<!--
  ACTION REQUIRED: Replace the content in this section with the technical details
  for the project. The structure here is presented in advisory capacity to guide
  the iteration process.
-->

**Language/Version**: [e.g., Python 3.11, Swift 5.9, Rust 1.75 or NEEDS CLARIFICATION]  
**Primary Dependencies**: [e.g., FastAPI, UIKit, LLVM or NEEDS CLARIFICATION]  
**Storage**: [if applicable, e.g., PostgreSQL, CoreData, files or N/A]  
**Testing**: [e.g., pytest, XCTest, cargo test or NEEDS CLARIFICATION]  
**Target Platform**: [e.g., Linux server, iOS 15+, WASM or NEEDS CLARIFICATION]
**Project Type**: [e.g., library/cli/web-service/mobile-app/compiler/desktop-app or NEEDS CLARIFICATION]  
**Performance Goals**: [domain-specific, e.g., 1000 req/s, 10k lines/sec, 60 fps or NEEDS CLARIFICATION]  
**Constraints**: [domain-specific, e.g., <200ms p95, <100MB memory, offline-capable or NEEDS CLARIFICATION]  
**Scale/Scope**: [domain-specific, e.g., 10k users, 1M LOC, 50 screens or NEEDS CLARIFICATION]

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

Per `.specify/memory/constitution.md` (blauw_zwart_fan_sim_pipeline — synthetic fan events, analytics
and AI; demo-quality Fan-360 when warehouse path applies):

- **Analytics source of truth**: Feature identifies dbt mart models (`fct_*`, `dim_*`) for any analytics
  or agent Q&A paths; no plan to embed business logic on raw JSON in app code without a Complexity
  Tracking justification.
- **Raw layer**: Raw events remain append-only/immutable; enrichment and fan-360 logic land in dbt
  downstream, not as mutable raw rewrites.
- **Data quality**: New or changed models include appropriate `not_null` / `unique` tests and at least
  one business-rule test where the domain applies (e.g. amounts, dates, keys).
- **Demonstrable path**: Ingest may stay minimal, but the plan shows a clear **event → raw → marts**
  thread the demo can run.
- **Demo-first**: Plan prioritizes vertical slice, README/architecture diagram, dbt tests in CI, and
  one strong agent Q&A over extra features; trade-offs favor **shipped** over polish and **dbt tests**
  over new features unless explicitly justified in Complexity Tracking.
- **Spec and contracts**: Plan ties implementation to `spec.md` and `contracts/` and names the contract
  version; normative ordering, encoding, and failure behavior match the spec.
- **Reproducibility**: Where the spec requires deterministic output (e.g. fixed seed), the plan states
  how byte-identical runs are preserved and tested.
- **NDJSON / interchange testing**: Plans for synthetic or line-delimited outputs describe pytest checks
  for contract shape, line ordering, and encoding.
- **Schema evolution**: Breaking NDJSON or event schema changes bump contract version (e.g. v2) and
  include migration notes; no silent breaks for v1 consumers.
- **Temporal rules**: UTC with `Z` in interchange formats; calendar-sourced times (e.g. Europe/Brussels
  kickoffs) document conversion to UTC.
- **Simplicity**: Small CLI, clear defaults; domain constants (capacities, venue facts) are named and
  documented, not magic numbers.
- **Python / TDD / UV / generator deps**: Plans that touch Python code name test additions or updates
  (pytest) and prefer red–green–refactor; generator runtime SHOULD stay stdlib-only unless the spec adds
  a justified dependency. Local and CI commands use **UV** (`uv run pytest` from repo root, `uv run
  python …` for scripts). Dependencies are managed with `uv add` / `uv add --dev` / `uv remove` only;
  no `pip install` or bare `python` for project work unless UV is unavailable and explicitly allowed.

## Project Structure

### Documentation (this feature)

```text
specs/[###-feature]/
├── plan.md              # This file (/speckit.plan command output)
├── research.md          # Phase 0 output (/speckit.plan command)
├── data-model.md        # Phase 1 output (/speckit.plan command)
├── quickstart.md        # Phase 1 output (/speckit.plan command)
├── contracts/           # Phase 1 output (/speckit.plan command)
└── tasks.md             # Phase 2 output (/speckit.tasks command - NOT created by /speckit.plan)
```

### Source Code (repository root)
<!--
  ACTION REQUIRED: Replace the placeholder tree below with the concrete layout
  for this feature. Delete unused options and expand the chosen structure with
  real paths (e.g., apps/admin, packages/something). The delivered plan must
  not include Option labels.
-->

```text
# [REMOVE IF UNUSED] Option 1: Single project (DEFAULT)
src/
├── models/
├── services/
├── cli/
└── lib/

tests/
├── contract/
├── integration/
└── unit/

# [REMOVE IF UNUSED] Option 2: Web application (when "frontend" + "backend" detected)
backend/
├── src/
│   ├── models/
│   ├── services/
│   └── api/
└── tests/

frontend/
├── src/
│   ├── components/
│   ├── pages/
│   └── services/
└── tests/

# [REMOVE IF UNUSED] Option 3: Mobile + API (when "iOS/Android" detected)
api/
└── [same as backend above]

ios/ or android/
└── [platform-specific structure: feature modules, UI flows, platform tests]
```

**Structure Decision**: [Document the selected structure and reference the real
directories captured above]

## Complexity Tracking

> **Fill ONLY if Constitution Check has violations that must be justified**

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| [e.g., 4th project] | [current need] | [why 3 projects insufficient] |
| [e.g., Repository pattern] | [specific problem] | [why direct DB access insufficient] |
