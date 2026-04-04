<!--
Sync Impact Report
Version: (template placeholders) → 1.0.0
Principles: Replaced all template placeholders with five named principles (no renames).
Added sections: Project scope & non-goals; Quality gates & workflow expectations.
Removed sections: None (template comments removed; structure preserved).
Templates: .specify/templates/plan-template.md ✅ | spec-template.md ✅ | tasks-template.md ✅
Commands: .specify/templates/commands/*.md — path not present in repo; .cursor/commands/*.md — no CLAUDE-only refs; no change required.
Deferred: None.
-->

# Blue-Black Fan-360 Constitution

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

## Project scope & non-goals

This project is a **demo-quality** end-to-end fan event pipeline (Blue-Black Fan-360), not a production
data platform. It does not imply production SLOs, security certification, or full operational tooling
unless explicitly scoped in a feature spec. Plans and specs MUST state demo vs hardening scope so
reviewers can apply the correct bar.

## Quality gates & workflow expectations

- Implementation plans MUST complete the Constitution Check gates before Phase 0 research and re-check
  after Phase 1 design.
- Features that touch analytics or fan-360 MUST name the dbt models (`fct_*` / `dim_*`) or additions
  required; raw-only shortcuts require an explicit, justified exception in the plan’s Complexity
  Tracking table.
- CI MUST run `dbt test` (or the project’s equivalent documented command) on the main integration
  path; merging changes that break agreed tests is a constitution violation unless the amendment
  process updates the bar.

## Governance

- This constitution supersedes conflicting ad hoc practices for this repository. Where ambiguity
  remains, resolve in favor of modelled analytics in dbt and demo-first scope.
- **Amendments**: Propose changes via PR that updates `.specify/memory/constitution.md`, bumps
  **Version** per semantic versioning below, sets **Last Amended** to the merge date, and lists
  principle or section changes in the Sync Impact Report comment at the top of the file.
- **Versioning**: MAJOR — removal or incompatible redefinition of principles; MINOR — new principle or
  materially expanded governance/section; PATCH — wording, typos, clarifications without normative
  change.
- **Compliance**: Reviewers MUST verify plans and specs reference warehouse models for analytics,
  preserve raw immutability, include or extend dbt tests for changed models, and respect demo-first
  trade-offs. Use `.specify/memory/constitution.md` as the authoritative checklist.

**Version**: 1.0.0 | **Ratified**: 2026-04-04 | **Last Amended**: 2026-04-04
