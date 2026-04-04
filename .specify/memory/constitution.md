<!--
Sync Impact Report
Version: 1.1.0 → 1.2.0
Principles: VI expanded (stdlib-only generator guidance + UV/TDD unchanged). Added VII Spec-first;
  VIII Byte-identical reproducibility; IX Contract-backed testing; X Versioned contracts;
  XI Temporal semantics (UTC); XII Simplicity and named domain constants.
Renamed doc title: Blue-Black Fan-360 → blauw_zwart_fan_sim_pipeline (scope ties Fan-360 + synthetic source).
Added sections: None (new rules are numbered principles under Core Principles).
Removed sections: None.
Templates: .specify/templates/plan-template.md ✅ | spec-template.md ✅ | tasks-template.md ✅
Commands: .specify/templates/commands/*.md — path not present in repo; .cursor/commands/*.md — no change required.
Runtime: README.md ✅ (governance summary aligned with new principles).
Deferred: None.
-->

# blauw_zwart_fan_sim_pipeline Constitution

Synthetic fan event data for analytics and AI, delivered as a demo-quality pipeline (Blue-Black Fan-360)
where a warehouse and dbt path apply.

## Core Principles

### I. Modelled analytics as source of truth

- The source of truth for analytics is warehouse models built with dbt (facts and dimensions).
- Agents and application code MUST read from modelled tables (`fct_*`, `dim_*`) for analytics and fan-360
  questions; they MUST NOT reimplement business logic by parsing raw JSON or ad hoc extracts in
  application code.
- **Rationale**: One governed layer prevents divergent definitions and keeps answers aligned with the
  warehouse.

### II. Immutable raw layer

- Raw events are append-only and immutable after landing.
- Enrichment, fan-360 logic, and derived attributes MUST live in dbt (staging/intermediate/marts),
  downstream of raw.
- **Rationale**: Reproducibility and auditability; transformations stay versioned and testable in dbt.

### III. Mandatory data quality (dbt)

- Models MUST use dbt tests appropriate to the grain: `not_null` and `unique` where business keys or
  uniqueness apply.
- At least one business-rule test MUST exist where relevant (e.g. purchase amount > 0, valid date
  ranges, referential expectations between facts and dimensions).
- **Rationale**: Demo credibility requires failing fast on broken assumptions, not silent bad data.

### IV. Demonstrable event path

- The “streaming” or ingest layer MAY be minimal (script, file drop, or lightweight Kafka) as long as
  the story **event → raw landing → marts** is clear and demoable end-to-end.
- **Rationale**: This repository optimizes for a teachable vertical slice, not production-grade ingest.

### V. Demo-first delivery and trade-offs

- Prioritize, in order: a working vertical slice; a README with an architecture diagram; passing dbt
  tests in CI; one compelling agent Q&A over breadth of features.
- When choosing between a more polished deliverable and a shipped slice, choose **shipped**.
- When choosing between a new feature and a dbt test, choose the **dbt test**.
- **Rationale**: The project is demo-quality, not a production platform; depth and correctness in the
  warehouse beat feature sprawl.

### VI. Python platform, UV toolchain, and generator dependencies

- Python work MUST target `requires-python` in `pyproject.toml` (currently >=3.12). Runtime packages
  belong in `[project] dependencies`; dev-only tools (e.g. pytest) MUST be added with `uv add --dev`.
- **Generator scripts** (e.g. synthetic event producers): runtime logic SHOULD use only the Python
  standard library unless a feature specification explicitly adds a runtime dependency with written
  justification; additions MUST land in `[project] dependencies` and the spec, not ad hoc installs.
- When adding or changing Python behavior, contributors MUST prefer **test-driven development**:
  write or extend a **failing** pytest test that encodes the desired behavior, implement the smallest
  change that makes it pass, then refactor if needed.
- Dependency and environment operations MUST use **UV**: `uv add` / `uv remove` (and `uv add --dev`
  for dev tools); run the suite with `uv run pytest` from the repository root (paths MUST match the
  project layout, e.g. `tests/`); run scripts with `uv run python <path/to/script.py> …` (or
  `uv run <tool>` when configured as a project script). Contributors MUST NOT use `pip install` or
  bare `python` for project work unless UV is unavailable and the user explicitly allows it.
- Any dependency change MUST be reflected in `pyproject.toml` **and** `uv.lock` via UV only.
- **Rationale**: Lockfile-backed reproducibility, minimal runtime footprint for generators, and tests as
  the contract for Python code.

### VII. Spec-first normative behavior

- Normative behavior for features MUST be stated in `specs/<feature>/spec.md` and
  `specs/<feature>/contracts/` (and related spec artifacts the feature defines). Implementation MUST
  match the **contract version** and requirements cited in that feature’s spec (including ordering,
  encoding, and failure semantics).
- **Rationale**: Code alone is not the specification; contracts keep analytics, AI, and pipeline
  consumers aligned.

### VIII. Byte-identical reproducibility

- Where a feature spec defines deterministic generation (e.g. fixed seed and parameters), two
  successful runs with identical inputs MUST produce **byte-identical** outputs, including file
  ordering and encoding, as stated in the spec (preserving FR-005-style guarantees where they apply).
- **Rationale**: Stable demos, docs, and automated checks depend on bitwise-stable artifacts.

### IX. Contract-backed testing

- Logic MUST be verified with **pytest**. For NDJSON (or similar line-delimited) outputs, tests MUST
  validate records against the published contract: **shape** (required fields and types), **ordering**
  rules, and **encoding** (e.g. UTF-8, newline discipline) as specified.
- **Rationale**: Prevents drift between code, documentation, and downstream loaders.

### X. Versioned contracts and backward compatibility

- If the NDJSON (or event) schema changes incompatibly, contributors MUST **version** the contract
  (e.g. `v2`, new contract file or section) and **document migration** for consumers. They MUST NOT
  silently break v1 consumers when v1 remains supported.
- **Rationale**: Analytics and AI clients rely on stable, explicit contracts.

### XI. Temporal semantics

- Event timestamps in interchange formats MUST use **UTC** with a **`Z`** suffix in serialized form
  unless the contract explicitly defines another normative representation.
- Match kickoffs and other calendar-sourced times MUST document timezone handling (e.g. source
  **Europe/Brussels** converted to UTC in generated data) in the spec or contract.
- **Rationale**: Avoids ambiguous local-time bugs in global analytics.

### XII. Simplicity and named domain constants

- Prefer **small CLI surfaces** and **clear defaults** over sprawling options.
- Stadium and domain facts (e.g. Jan Breydel capacity **29,062**) MUST appear as **named, documented**
  constants (or configuration with defaults), not as unexplained literals scattered through code.
- **Rationale**: Readable demos and safer refactors.

## Project scope & non-goals

This project is **blauw_zwart_fan_sim_pipeline**: synthetic fan event data for analytics and AI, within
a **demo-quality** end-to-end fan pipeline (Blue-Black Fan-360), not a production data platform. It does
not imply production SLOs, security certification, or full operational tooling unless explicitly scoped
in a feature spec. Plans and specs MUST state demo vs hardening scope so reviewers apply the correct
bar.

## Quality gates & workflow expectations

- Implementation plans MUST complete the Constitution Check gates before Phase 0 research and re-check
  after Phase 1 design.
- Features that touch analytics or fan-360 MUST name the dbt models (`fct_*` / `dim_*`) or additions
  required; raw-only shortcuts require an explicit, justified exception in the plan’s Complexity
  Tracking table.
- Features with **synthetic or raw interchange** MUST reference `spec.md` and `contracts/`, cite the
  contract version, and describe how pytest enforces shape, ordering, and encoding. Breaking schema
  changes require a versioned contract and migration notes.
- CI MUST run `dbt test` (or the project’s equivalent documented command) on the main integration
  path once that path exists; merging changes that break agreed tests is a constitution violation
  unless the amendment process updates the bar.
- Features that add or change **Python** behavior MUST include new or updated **pytest** coverage;
  verification before merge MUST include **`uv run pytest`** passing at repository root unless
  Complexity Tracking documents a justified exception.
- Python dependency changes MUST land only through UV so `pyproject.toml` and `uv.lock` stay in sync.

## Governance

- This constitution supersedes conflicting ad hoc practices for this repository. Where ambiguity
  remains, resolve in favor of modelled analytics in dbt, spec-published contracts for synthetic data,
  and demo-first scope.
- **Amendments**: Propose changes via PR that updates `.specify/memory/constitution.md`, bumps
  **Version** per semantic versioning below, sets **Last Amended** to the merge date, and lists
  principle or section changes in the Sync Impact Report comment at the top of the file.
- **Versioning**: MAJOR — removal or incompatible redefinition of principles; MINOR — new principle or
  materially expanded governance/section; PATCH — wording, typos, clarifications without normative
  change.
- **Compliance**: Reviewers MUST verify plans and specs reference warehouse models for analytics,
  preserve raw immutability, include or extend dbt tests for changed models, respect demo-first
  trade-offs, align code with cited spec and contract versions, enforce reproducibility and NDJSON
  testing where applicable, and—for Python changes—enforce TDD-oriented pytest coverage and UV-based
  workflows. Use `.specify/memory/constitution.md` as the authoritative checklist.

**Version**: 1.2.0 | **Ratified**: 2026-04-04 | **Last Amended**: 2026-04-04
