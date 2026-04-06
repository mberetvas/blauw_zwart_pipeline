# Feature Specification: Unified orchestrated synthetic event stream

**Feature Branch**: `004-unified-synthetic-stream`  
**Created**: 2026-04-06  
**Status**: Draft  
**Input**: User description: "Specify a new feature: unified orchestrated synthetic event stream for blauw_zwart_fan_sim_pipeline. What: Add a way to emit a single chronological stream of NDJSON lines that combines (a) match-related fan events in the spirit of v2 (calendar-driven ticket_scan and merch_purchase with match_id where applicable) and (b) v3 retail_purchase events, interleaved by synthetic timestamp, simulating a realistic mixed workload. Why: Today generate_events is batch-oriented (v1/v2) and generate_retail can stream v3; there is no first-class way to merge both into one time-ordered stream for demos, load tests, or piping to external tools. User-facing goals: new CLI subcommand under fan_events; configurable sources; stdout or append-to-file NDJSON; optional wall-clock pacing; long-running/bounded runs with max events, max simulated duration, and/or interrupt; no mandatory message-broker dependency. Non-goals: changing canonical v1/v2/v3 contract files unless explicitly needed; adding a broker client to dependencies. Acceptance: merged order matches non-decreasing synthetic timestamps; spot-checks with fixed seeds; tests for merge and CLI smoke."

## Clarifications

### Session 2026-04-06

- Q: What is the canonical subcommand name? → A: **`stream`** (Option A).
- Q: Is v1 rolling mode in scope for match-side events in `stream`? → A: **No** — **`stream` is v2 + calendar only**; v1 rolling is **out of scope** for this feature (Option A).
- Q: How should `fan_id` relate between retail and match-day events? → A: **Unified synthetic fan population** — one coherent universe so identities align across streams where contracts allow (Option B).
- Q: File output: append vs rotation? → A: **Append-only** — no built-in log rotation (Option A).
- Q: When max events and max simulated duration are both omitted, default behavior? → A: **Unbounded** — run until **Ctrl+C**, process exit, or resource failure; **document** risk in help (Option A).

## User Scenarios & Testing *(mandatory)*

### User Story 1 - One mixed, time-ordered stream (Priority: P1)

An operator wants a single continuous stream of synthetic fan events that looks like real mixed activity around matches and in-venue retail: match-related events (ticket scans, merchandise purchases tied to matches where applicable) and standalone retail purchases, all ordered by synthetic time so downstream demos, recordings, and load tests see a believable timeline.

**Why this priority**: This is the core value—without a unified chronological stream, the feature does not address the gap between batch match generation and separate retail streaming.

**Independent Test**: Run the new capability with a known calendar and retail parameters; verify that output is one NDJSON line per event, and that synthetic timestamps never decrease from line to line.

**Acceptance Scenarios**:

1. **Given** configured match-calendar and retail generation inputs, **When** the operator runs the unified stream command, **Then** emitted lines combine both families of events in **non-decreasing synthetic timestamp** order.
2. **Given** the same inputs and randomness seed (where applicable), **When** the operator runs the command twice, **Then** outputs are **byte-identical** (deterministic replay for testing and demos).

---

### User Story 2 - Configurable sources and output (Priority: P2)

An operator wants to reuse existing behaviors: retail side aligned with current v3 retail parameters; match side driven by calendar JSON with v2-style semantics for relevant event types. Output should go to standard output or append to a file, with optional pacing between lines so the stream can mimic real-time or be throttled.

**Why this priority**: Reusing established parameters reduces learning curve and keeps behavior consistent with existing generators.

**Independent Test**: Invoke with only retail parameters vs. only calendar-driven match parameters vs. both; confirm each configuration behaves as documented and that output destination and pacing options work.

**Acceptance Scenarios**:

1. **Given** retail-only configuration, **When** the operator runs the command, **Then** output contains only retail purchase events consistent with the referenced v3 contract semantics (shapes unchanged unless this spec explicitly extends them).
2. **Given** calendar-only configuration, **When** the operator runs the command, **Then** output contains only match-related events consistent with v2-style semantics for the cited event types.
3. **Given** append-to-file mode, **When** the operator runs the command, **Then** new lines are **appended** to the chosen path without corrupting prior content; **no** automatic file rotation is performed by `stream` (see **FR-006**).

---

### User Story 3 - Bounded runs and clean stop (Priority: P3)

An operator wants to limit how long a run lasts (by event count and/or simulated time span) and to stop interactively without corrupting output. Behavior for each stop mode must be documented.

**Why this priority**: Demos and load tests need predictable bounds; long-running processes must exit cleanly.

**Independent Test**: Run with each limit type until stop; send an interactive interrupt once and verify documented shutdown. Confirm limits compose sensibly (e.g., whichever bound is reached first wins).

**Acceptance Scenarios**:

1. **Given** a maximum event count, **When** that many lines have been emitted, **Then** the process exits successfully with a complete final line.
2. **Given** a maximum simulated time window, **When** the next event would fall outside that window, **Then** the process exits without emitting that event.
3. **Given** an interactive interrupt, **When** the operator requests stop, **Then** the process exits promptly with documented semantics (e.g., whether a partial final line can occur—must be stated).

---

### Edge Cases

- **Ties on synthetic timestamp**: Ordering must be **total** and **stable** (documented tie-break rule, e.g., deterministic ordering by source type and stable event id) so merge is reproducible.
- **Empty or invalid calendar**: **Invalid** calendar JSON (parse/validation failure) MUST fail with a **clear error**, consistent with **`generate_events --calendar`** (`CalendarError` / stderr). **Empty** calendar (valid JSON, zero matches in range) MUST yield **no** v2 lines without silent corruption.
- **No retail or no match configuration**: Stream contains only the configured side; documented.
- **Pacing with very fast or zero delay**: Wall-clock pacing interacts with **post-merge** `--max-events` / `--max-duration` (whichever triggers first) and **Ctrl+C**; zero min/max implies no sleep between lines.
- **Large files / long runs**: Output remains line-delimited JSON; **splitting or rotating** files is an **operator concern** (external tools or multiple runs), not `stream` built-ins.
- **No max events / no max simulated duration**: Run is **unbounded** until **interrupt**, normal completion of generated content (if the source model ends), or failure; **help text** MUST warn about long runs and resource use.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The product MUST expose a **new subcommand named `stream`** under the existing fan-events entry point that emits a **single interleaved** stream of NDJSON events from (a) calendar-driven, v2-style match-related events (`ticket_scan`, `merch_purchase` with `match_id` where applicable) and (b) v3 `retail_purchase` events, **merged by synthetic timestamp** per the orchestration contract.
- **FR-002**: The merged stream MUST preserve **non-decreasing** synthetic event timestamps across all emitted lines; ties MUST be resolved by the **total order** defined in `contracts/orchestrated-stream.md` (timestamp, then `event`, then stable line encoding).
- **FR-003**: Event **payload shapes** MUST remain consistent with the **existing normative v2 and v3 contracts** for those event types; this feature MUST NOT change those contracts **except** where an explicit, versioned amendment is approved and documented.
- **FR-004**: Operators MUST be able to configure **retail generation** using the same conceptual parameters as today’s v3 retail generator (parity of meaning; flag names may mirror existing CLI for familiarity).
- **FR-005**: Operators MUST be able to configure **match-related generation** from **calendar JSON** with semantics aligned to existing **v2** match-driven generation for the included event types. **`stream` does not implement v1 “rolling” match generation**; that mode remains outside this feature (see Out of scope).
- **FR-006**: Output MUST support **standard output** and **append-to-file** NDJSON (one JSON object per line, UTF-8, newline-terminated lines). File output is **append-only** to a single path per process; **`stream` MUST NOT** implement automatic **log rotation**, size-based roll, or time-based new files (operators use OS or external tooling if needed).
- **FR-007**: Operators MUST be able to enable **optional wall-clock pacing** between emitted lines, behaviorally aligned with existing streaming retail pacing (conceptual parity: delay between lines for demo/real-time simulation).
- **FR-008**: Runs MUST support **optional bounded termination** via configurable **maximum event count** and/or **maximum simulated time span** (interpreted against synthetic event times). When **both** limits are **absent**, the run is **unbounded** until **interactive interrupt**, generator exhaustion (if applicable), or process failure. When **one or both** limits are set, the combination rule MUST be documented (e.g., stop when the **first** configured limit triggers). **CLI help** MUST **warn** that unbounded runs can consume unbounded time and disk.
- **FR-009**: Interactive **stop** (e.g., keyboard interrupt) MUST be handled with **documented** semantics for buffer flush and whether a partial line can appear.
- **FR-010**: The feature MUST **not** require any external message broker or similar service to function; integration with external tools is **optional** and **out of product scope** for this specification (documentation may illustrate piping only in follow-up material).
- **FR-011**: **Determinism**: For a stated set of inputs (including randomness seed where randomness exists), successful runs MUST produce **byte-identical** output suitable for regression tests, unless explicitly documented exceptions apply.
- **FR-012**: **`fan_id` coherence**: When **both** match-related and retail sources are active, `stream` MUST generate events from a **single unified synthetic fan population** so `fan_id` (and any related identity fields defined in the v2/v3 contracts) **refers consistently** to the same synthetic fans across lines. When only one source is active, that side uses one population for its events (no cross-stream requirement).

### Out of scope (non-goals)

- Changing canonical v1/v2/v3 interchange contract documents **unless** a small explicit amendment is required and versioned; default is **no contract file churn**.
- Adding a broker client or similar **non-stdlib** runtime dependency to project dependencies for this feature.
- Defining new event types beyond combining existing v2 match-style and v3 retail events as described.
- **v1 rolling** (non-calendar) match generation as a source inside **`stream`**; operators use existing **batch** generators for v1-only workflows.
- **Built-in file rotation** or multi-file rollover for NDJSON output (out of scope for `stream`).
- **`--fans-out` companion JSON** for `stream` (optional): **not** in scope for the initial `stream` implementation; use **`generate_events` / `generate_retail`** sidecars if needed until explicitly added.

### Key Entities

- **Synthetic event line**: One JSON object per NDJSON line, carrying a synthetic timestamp field consistent with existing contracts for its event type.
- **Match calendar input**: Structured schedule used to place and relate match events (as in existing v2 flows).
- **Merge cursor**: Conceptual ordering over pending events from two sources using synthetic time plus tie-break rules.
- **Unified fan population**: The set of synthetic fans from which both match-related and retail events draw `fan_id` when both sources are enabled, so cross-stream identity is **coherent**, not independent by default.

### Python scripts and packaged code *(mandatory when feature touches generators, CLIs, or modules under `src/`, `scripts/`, or equivalent)*

Per project constitution:

- **FR-PY-001**: New or changed Python behavior MUST be covered by **automated tests**; contributors MUST prefer **test-first** development for new behavior.
- **FR-PY-002**: Dependencies and runs MUST follow the project’s **UV** workflow; lockfile stays aligned with manifest policy.
- **FR-PY-003**: Generator, CLI, and feature **runtime** code MUST remain **stdlib-only** unless this specification documents a **justified** non-stdlib dependency per constitution **VI**; this feature does **not** introduce a broker client.
- **FR-PY-004**: Structure (functions vs. objects) MUST follow constitution **XIII**: use **classes** when coordinating multiple sources, merge state, and test seams; use **functions** for straightforward transforms.

### Spec, contracts, and synthetic interchange *(mandatory when feature defines NDJSON, events, or machine-readable handoff files)*

Per project constitution:

- **FR-SC-001**: Normative orchestration behavior (ordering, tie-breaks, determinism inputs) lives in this `spec.md` and `specs/004-unified-synthetic-stream/contracts/orchestrated-stream.md`; event field semantics for v2/v2-style and v3 types remain governed by their existing contracts.
- **FR-SC-002**: Deterministic runs MUST document required inputs (e.g., seed, calendar snapshot, parameter bundle) under which two successful runs are **byte-identical**.
- **FR-SC-003**: Tests MUST validate **shape** (per existing contracts), **merge ordering**, and **encoding** (UTF-8, one JSON per line).
- **FR-SC-004**: Any incompatible change to interchange semantics MUST be **versioned**; existing v1/v2/v3 consumers MUST not be silently broken while supported.
- **FR-SC-005**: Serialized timestamps in emitted events MUST follow existing contract rules (UTC with `Z` where those contracts require it); calendar timezone handling MUST match established v2 documentation.
- **FR-SC-006**: Any new domain constants introduced solely for orchestration MUST be **named and documented** in this spec or the orchestration contract.
- **FR-SC-007**: A **mixed** NDJSON file (v2-style lines and v3 `retail_purchase` lines) MUST treat each line as conforming to the **existing v2 or v3 contract** for that line’s `event`; there is **no** new standalone “v4” payload schema—normative merge and ordering rules are in `contracts/orchestrated-stream.md` and existing interchange docs.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: For representative fixed inputs (including seed), **every** repeat run produces **identical output** to a **reference** run (exact match), demonstrating reproducibility for demos and regression checks.
- **SC-002**: For every emitted stream in automated checks, **100%** of consecutive line pairs satisfy **non-decreasing synthetic timestamp** after applying the documented tie-break when timestamps are equal.
- **SC-003**: Operators can complete a **documented end-to-end demo path** (configure sources, emit at least hundreds of interleaved lines, stop via a **configured bound** or **interactive interrupt** when running without limits) in a **single session** without auxiliary services.
- **SC-004**: **Primary user story (P1)** validation passes independently: merged stream exists, ordering rule holds, and determinism holds under fixed inputs.

## Assumptions

- **Subcommand name**: The new subcommand is **`stream`** (no other name is required for this feature).
- **Operators** are the same audience as existing CLI users (engineers, demo owners); no separate end-user GUI is in scope.
- **Realistic mixed workload** means statistically plausible interleaving driven by existing generators’ time models, not a new domain-specific simulation engine beyond merging.
- **Fan identity**: With **both** sources, **`fan_id` is drawn from one unified synthetic population** (see **FR-012**); single-source runs do not need cross-stream coordination.
- **Follow-up documentation** (e.g., piping to external CLI tools) is **not** part of this specification’s mandatory deliverables; a short example may be added later without blocking this feature.
- **Append-to-file** opens the target path in append mode and writes **complete lines**; torn-line avoidance and flush semantics on interrupt are defined in the technical plan (**FR-009**).
- **Default run length**: With **no** max event count and **no** max simulated duration, the run is **unbounded** by default (**FR-008**); operators rely on **Ctrl+C** or external process control to stop.
