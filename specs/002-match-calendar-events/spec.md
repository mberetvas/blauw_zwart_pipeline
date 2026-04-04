# Feature Specification: Match-calendar synthetic fan events

**Feature Branch**: `002-match-calendar-events`  
**Created**: 2026-04-04  
**Status**: Draft  
**Input**: User description: "Feature: Match-calendar-driven synthetic fan events for a full season (or any date range). Problem: The current generator (001 / fan-events-ndjson-v1) emits events in a rolling UTC window with a small derived fan pool. It does not model real fixtures, per-match attendance, or grouping events by match — which limits season-level and AI-driven questions. Goal: Generate synthetic NDJSON (or an agreed successor format) where events are driven by a match calendar (e.g. previous season) with per-match attendance. Each match defines who could be present (capped by stadium capacity) and when events may occur (match-day time windows around kickoff). Domain constants: Club Brugge home stadium (Jan Breydel) maximum capacity: 29,062 spectators. Inputs (to be specified in data-model): Calendar file(s): for each match at minimum — stable match_id, kickoff (with timezone rule), attendance (spectators present). Optional: opponent, competition, home/away flag. Configurable rules: how attendance maps to ticket_scan volume (e.g. fraction of attendees with a scan), how merch_purchase counts or probability relates to attendance, and the stadium time window per match (not only 90 minutes of play — include entry/halftime/egress if needed). Outputs: Event stream suitable for downstream tools and AI Q&A, including examples like: Which fan bought the most items; infer or attach location context (today location exists only on ticket_scan — spec must define join strategy or schema extension). Item popularity by location if required (may need optional location on merch or a documented inference rule). Non-goals (unless later specs): Real integrations with ticketing or POS APIs. Perfect statistical realism; plausibility and reproducibility matter more than fitting real distributions. Constraints: Preserve existing quality bar: UTF-8 NDJSON, canonical JSON, global sort order — either extend v1 with optional fields and a new contract version, or add a parallel mode with explicit versioning."

## Problem & goal *(context)*

**Problem**: The existing synthetic source (`001-synthetic-fan-events`, contract `fan-events-ndjson-v1`) emits events in a rolling UTC time window with a small synthetic fan pool. It does not tie events to real fixtures, per-match crowd size, or match-day time structure, which limits season-level analysis and AI-style questions.

**Goal**: Produce a synthetic event stream (NDJSON or a documented successor) where generation is driven by a **match calendar** over a **configurable date range** (e.g. a full season). Each match supplies **who could attend** (bounded by venue rules) and **when** activity may occur (windows around kickoff, including entry, play, breaks, egress as configured). Outputs remain suitable for downstream loading, analytics, and fan Q&A scenarios.

**Non-goals** (unless added by a later feature):

- Live integrations with ticketing, access control, or point-of-sale systems.
- Statistical models fitted to real-world distributions; **plausibility** and **reproducibility** take precedence over realism.

## Clarifications

### Session 2026-04-04

- Q: Should the calendar cover **home-only** (Jan Breydel) or **all fixtures**? → A: **All fixtures (home and away)**. Home matches at Jan Breydel use the **29,062** cap; away matches use **per-row attendance** and venue/location semantics from the calendar (not the home capacity constant).
- Q: **NDJSON contract** — extend v1 with optional fields vs **new v2** with required fields? → A: **New contract v2** for calendar-driven output: **`match_id` required** on calendar-tied events, plus related fields defined in `contracts/`. The **`001` rolling-window generator** remains **fan-events-ndjson-v1**; migration and dual-parser expectations are documented in v2 (v1 pipelines keep consuming v1 files unchanged).
- Q: **Merch + location** — optional **`location`** on `merch_purchase` vs **inference-only** (join to ticket_scan)? → A: **Normative for generator output: optional `location` on `merch_purchase`**, populated when the scenario assigns a venue/stand string for that merch event (same semantics as `ticket_scan.location` for that match/fan context). **Inference-only join is not** the normative path for this feature; consumers MAY still join by `fan_id` + `match_id` for validation. Rows MAY omit `location` when the contract allows (documented).
- Q: **Attendance mapping** — exact formulas and deterministic vs stochastic? → A: **Deterministic from seed**: configurable **`scan_fraction`** in (0,1] applied to attendance to yield **ticket_scan event counts** (rounded by documented rules); **`merch_purchase` counts** derived from attendance via configurable **expected merch events per attendee** (or equivalent) with **deterministic** placement in time—all RNG **seeded** so identical inputs → **FR-008** byte identity.
- Q: **Match-day window** — parameters and global vs per row? → A: **Default window**: **T−120 minutes** through **T+90 minutes** relative to **kickoff** (UTC), unless superseded. **Global defaults** in configuration; **optional per-match overrides** in the calendar (e.g. window start/end offsets) when the data-model defines them; otherwise defaults apply.
- Q: **Fan identity** — numeric pool 1..29062 vs strings; reuse across matches? → A: **`fan_id` remains opaque strings** (as in v1), **not** restricted to the integer range 1..29062. The **29,062** limit applies to **how many distinct fans** may attend a **single home** match at Jan Breydel, not to ID encoding. **The same `fan_id` MAY appear in multiple matches** within one season file when the draw logic selects them again.
- Q: **Empty / bad calendar** — zero attendance, postponed, duplicate `match_id`? → A: **Zero or negative attendance** → **fail** (non-success). **Duplicate `match_id`** in the input calendar → **fail**. **Postponed / unknown kickoff**: a row **without a valid kickoff** → **fail**; **postponed fixtures with a rescheduled kickoff** are normal rows; **postponed-without-kickoff** rows MUST **not** be supplied (data-prep responsibility) — if present without kickoff, **fail** (same as missing kickoff).
- Q: **Output shape** — one NDJSON vs one file per matchday; sorting? → A: **Single NDJSON file** for the selected date range/season segment; **global sort** over **all** lines (v1-style ordering extended in v2). **Deferred** (later feature): **one file per matchday** or split bundles — **out of scope** for `002` to avoid scope creep in plan/tasks.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Calendar-driven match days (Priority: P1)

A demo or analytics owner needs synthetic **ticket_scan** and **merch_purchase** activity that **follows a supplied match calendar** over a chosen period (**home and away** fixtures). For each match, the calendar defines **kickoff time** (with an agreed timezone rule), **how many spectators are present**, and a **stable match identifier**. Generation MUST place events only inside **per-match time windows** derived from kickoff and documented rules (not a single rolling UTC window unrelated to fixtures).

**Why this priority**: Without calendar grounding, the feature does not address season-level or match-level questions; this is the core behavioral change.

**Independent Test**: Given a minimal calendar (one or two matches) and fixed rules, a reviewer can verify that every emitted event’s timestamp falls in the configured window for its match and that the number of distinct “attending” synthetic fans never exceeds the configured attendance and venue caps for that match.

**Acceptance Scenarios**:

1. **Given** a calendar listing at least one match with kickoff, attendance, and timezone rule, **When** generation runs successfully, **Then** every emitted event that is tied to that match MUST carry the same **match identifier** the calendar supplied (or a documented deterministic mapping), and its occurrence time MUST fall within the **match-day window** defined in the contract for this feature.
2. **Given** configurable rules for ticket scan rate and merch activity versus attendance, **When** two runs use the same calendar, rules, seed, and parameters, **Then** the rules MUST be applied consistently so outputs remain comparable (see User Story 2 for byte-level identity).

---

### User Story 2 - Reproducible season files (Priority: P2)

An operator needs **repeatable** outputs for demos, documentation, and automated checks: the same calendar, date filter, configuration, and seed MUST yield the **same file bytes** as in the existing v1 quality bar (global sort, canonical JSON, UTF-8 NDJSON).

**Why this priority**: Trust and CI depend on deterministic synthetic data; this inherits the bar from `001` / FR-005-style guarantees.

**Independent Test**: Run generation twice with identical inputs; compare outputs **byte-for-byte**; they MUST match.

**Acceptance Scenarios**:

1. **Given** a fixed seed and fixed parameters documented for the scenario, **When** generation completes successfully twice, **Then** the output files MUST be **byte-identical** (same rule family as **FR-005** in `001-synthetic-fan-events`).
2. **Given** the published contract for this feature, **When** a validator checks sort order and serialization, **Then** non-empty lines MUST follow the contract’s **global ordering** and **canonical JSON** rules (aligned with v1 unless the new contract explicitly documents a difference).

---

### User Story 3 - Match grouping for season-level questions (Priority: P3)

A data consumer needs to **group events by match** and filter by season or date range so they can answer questions such as “how much activity per fixture?” without inferring matches from timestamps alone.

**Why this priority**: Match attribution unlocks season and fixture analytics and supports AI Q&A grounded in fixture identity.

**Independent Test**: From a generated file alone, a reviewer can partition events by **match identifier** and confirm that all events for one match share consistent match metadata and fall within that match’s calendar window.

**Acceptance Scenarios**:

1. **Given** a multi-match calendar, **When** the file is consumed, **Then** each calendar-tied event MUST be attributable to **exactly one** match identifier from the input calendar (or the run MUST fail rather than emit ambiguous rows).
2. **Given** a defined season or from–to date range in configuration, **When** the calendar includes matches outside that range, **Then** those matches MUST be excluded from generation (or the run MUST fail if partial inclusion would mislead); behavior MUST be documented in the contract.

---

### User Story 4 - Merch and “where” for analytics (Priority: P4)

An analyst or assistant needs to rank **fans by merch spending** and, where required, **item popularity by location**. Today, **location** exists on **ticket_scan** only; this feature MUST either **extend the schema** (e.g. optional location on **merch_purchase**) or publish a **deterministic inference rule** (e.g. join merch to ticket_scan by fan and match) so that “by location” questions are answerable without guesswork.

**Why this priority**: Unlocks examples like “top buyer” and “popular items per stand or venue” once match and location semantics are clear.

**Independent Test**: Using only the contract and sample output, a reviewer can answer: (a) total spend per fan, (b) whether merch rows have explicit location or a documented way to derive it for home and away cases.

**Acceptance Scenarios**:

1. **Given** the published contract for this feature, **When** counting total **merch_purchase** amount per **fan_id**, **Then** the contract MUST define whether **amount** semantics match v1 (positive EUR to cent precision) or document any change.
2. **Given** the contract’s normative **`location`** rule on **merch_purchase** (optional field), **When** computing item popularity **by location**, **Then** the rule MUST cover **home** matches at Jan Breydel and **away** matches (see Edge Cases) without ambiguous defaults.

---

### Edge Cases

- **Attendance greater than venue capacity**: For a **home** match at Jan Breydel, if **attendance** exceeds **29,062** (named domain constant: maximum spectators), the run MUST **fail** with non-success; the implementation MUST NOT silently cap unless the contract explicitly allows a **documented clamp mode** (default is fail).
- **Away matches**: Calendar includes **home and away** fixtures. For **away** matches, the contract MUST state what **location** means on **ticket_scan** and how **`merch_purchase.location`** (when present) is populated so “by location” is not interpreted as Jan Breydel incorrectly.
- **Missing or invalid calendar rows**: If a required field is missing (e.g. **match_id**, **kickoff**, **attendance**, or timezone rule), or **kickoff** cannot be interpreted under the documented rule, the run MUST **fail** with non-success; no durable successful file that omits validation.
- **Duplicate match_id**: If the input calendar contains **two rows with the same match_id**, the run MUST **fail** with non-success (load-time validation).
- **Postponed / no kickoff**: Rows **without a valid kickoff** MUST NOT be accepted; the run MUST **fail**. Postponed fixtures **with** a rescheduled kickoff are normal rows; postponed-without-kickoff rows are a **data-prep** error if supplied.
- **Empty date range or zero matches**: If the configured season or date range contains **no** matches after filtering, the output MUST be an **empty** NDJSON file (**zero bytes**, per v1 empty-file rule) on success; this is **normative** for “no matches in range.”
- **Zero or negative attendance**: If attendance is zero or negative, the run MUST **fail** with non-success (per Clarifications).
- **Partial event types**: If the operator requests only **ticket_scan** or only **merch_purchase**, behavior MUST follow the same family as v1 single-type modes, extended for calendar windows.
- **Concurrency / ordering**: Equal timestamps MUST use deterministic **tie-breakers** extending v1’s minimum (`event` enum order, **fan_id**, then contract-defined keys) so global order remains total and reproducible.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The synthetic source MUST accept **match calendar** input covering **all fixtures in scope** (**home and away**), in one or more files or a documented single-file shape. Each row MUST have at minimum: **stable match_id** (unique across the file set), **kickoff** with a **timezone rule**, and **attendance** (spectators present). Optional fields MAY include **opponent**, **competition**, **home vs away**, and **per-match time-window overrides**; exact shapes belong in **data-model** / contract companion docs.
- **FR-002**: Generation MUST be limited to a **configurable date range** (e.g. season bounds) that selects which calendar matches participate; matches outside the range MUST NOT appear in output unless the contract documents an explicit override mode.
- **FR-003**: For each included match, the generator MUST derive **time windows** from **kickoff** and configuration. **Default** (unless per-match overrides exist in the calendar): events fall between **T−120 minutes** and **T+90 minutes** relative to kickoff (interpreted after UTC conversion). Overrides MUST be documented in the data-model. All synthetic event timestamps MUST fall inside those windows, expressed as **UTC with `Z`** in the output file, consistent with **FR-SC-005**.
- **FR-004**: For each match, the generator MUST model **at most** the configured **attendance** count of distinct synthetic fans eligible for that match’s events, and MUST NOT exceed **Jan Breydel maximum capacity 29,062** for **home** matches at that stadium. **Away** matches MUST use caps and semantics documented in the contract (e.g. traveling support ceiling), not the home capacity constant.
- **FR-005**: Configurable rules MUST define how **attendance** maps to **ticket_scan** volume via a **`scan_fraction`** in (0,1] (or equivalent) and how **merch_purchase** counts relate to attendance via **expected merch events per attendee** (or equivalent). Counts and placements MUST be **deterministic given the seed** (no run-to-run randomness when seed and inputs are fixed); rounding rules MUST be documented in the contract.
- **FR-006**: Every emitted event that is tied to a calendar match MUST include a **match identifier** (same as input **match_id** or a documented canonical form) so consumers can group by match without inferring from time alone.
- **FR-007**: The feature MUST preserve the **interchange quality bar** from `001`: **UTF-8 NDJSON**, **one JSON object per non-empty line**, **canonical JSON** serialization rules compatible with byte-identical comparisons, and **global sort order** by occurrence time **across the entire output file** with deterministic tie-breakers (extended contract MUST document full ordering, including any new fields). Output is a **single file** for the selected range; **splitting output into one file per matchday** is **out of scope** (deferred to a later feature).
- **FR-008**: For a fixed **seed**, fixed calendar inputs, fixed date range, and fixed rule parameters, two successful generation runs MUST produce **byte-identical** output files (same reproducibility intent as **FR-005** in `001-synthetic-fan-events`).
- **FR-009**: If the generator cannot produce a complete valid file satisfying this spec and the published contract (including caps, windows, and schema), the run MUST **terminate with non-success** and MUST NOT leave a durable file that could be mistaken for success, consistent with atomic-write semantics from `001` unless the new contract revises them.
- **FR-010**: Calendar-driven output MUST use a **versioned contract (v2)** with **`match_id` and related fields required** where specified; **`fan-events-ndjson-v1`** remains the contract for the **`001` rolling-window generator**. The v2 contract MUST document **migration** from v1 and **backward-compatibility expectations** (v1 tools do not consume v2 files without an updated parser). Silent breaking changes for v1 consumers are not allowed (**FR-SC-004**).
- **FR-011**: **Normative:** **`merch_purchase` MAY include optional `location`** (same type and semantics as v1 **`ticket_scan.location`** when present). The generator SHOULD populate **`location`** when the scenario assigns a venue/stand string for that row. **Inference-only** (merch location derived solely by join to **ticket_scan**) is **not** the required normative path for AI consumers for this feature. The contract MAY still describe an optional consumer-side join for validation.
- **FR-012**: Domain constant **Jan Breydel maximum capacity** MUST be **29,062** spectators, named and documented in the contract or this spec (**FR-SC-006**); code MUST NOT rely on unexplained numeric literals for that cap.

### Key Entities

- **Match (calendar)**: A scheduled fixture with stable **match_id**, **kickoff** and timezone interpretation, **attendance**, and optional competition metadata; may be **home** or **away** relative to the club.
- **Match-day window**: A half-open or closed time interval derived from kickoff and rules, inside which synthetic events for that match may occur (entry through egress as configured).
- **Synthetic fan**: Same concept as `001`: stable **fan_id** as an **opaque string** (not limited to integers 1..29,062); no real identity. The **same fan_id** MAY appear across **multiple matches** in one file. Per **home** match at Jan Breydel, at most **29,062** distinct fans may be in the attending pool; **away** matches follow **per-row attendance** and contract caps.
- **Synthetic events**: **ticket_scan** and **merch_purchase** as in v1, extended with **match** linkage and any v2 fields required by the contract.
- **Event file**: NDJSON (or agreed successor) single file output, globally sorted, UTF-8, suitable for append-only raw landing.

### Analytics & warehouse

Per project constitution:

- **FR-WH-001**: Downstream analytics for match and season questions SHOULD be expressible against future marts (e.g. facts keyed by **match_id** and time); this spec **provisions** **`fct_ticket_scans`**, **`fct_merch_purchases`**, and a **`dim_match`** (or equivalent) as **provisional** names—exact dbt design is left to `/speckit.plan`.
- **FR-WH-002**: Raw synthetic files remain **append-only** at landing; no in-place mutation of emitted events.
- **FR-WH-003**: When warehouse models consume these events, dbt tests apply at model time; the **contract** MUST make match keys and amounts enforceable for testing.

### Python scripts and packaged code

Per project constitution:

- **FR-PY-001**: New or changed Python behavior MUST be covered by pytest tests; contributors MUST prefer TDD (failing test first, smallest passing change, then refactor).
- **FR-PY-002**: Dependencies and runs MUST go through **UV** (`uv add`, `uv add --dev`, `uv remove`; `uv run pytest`; `uv run python <script>`). Lockfile (`uv.lock`) MUST stay aligned with `pyproject.toml` via UV only.
- **FR-PY-003**: Generator and CLI runtime SHOULD remain stdlib-only unless this spec documents a new runtime dependency with justification; Python MUST meet `requires-python` in `pyproject.toml`.

### Spec, contracts, and synthetic interchange

Per project constitution:

- **FR-SC-001**: Normative behavior MUST live in this `spec.md` and `specs/002-match-calendar-events/contracts/` (plus linked artifacts); implementation MUST match the **contract version** cited for this feature.
- **FR-SC-002**: Deterministic outputs MUST follow **FR-008** (fixed seed, calendar, range, parameters → byte-identical file).
- **FR-SC-003**: Tests MUST validate outputs against the contract: **shape**, **ordering**, and **encoding** (UTF-8, newlines, trailing newline rules aligned with v1 unless v2 documents differences).
- **FR-SC-004**: Incompatible schema changes MUST use a **versioned** contract and **document migration** from **fan-events-ndjson-v1**; v1 pipelines MUST remain supportable or receive an explicit deprecation path.
- **FR-SC-005**: Serialized timestamps MUST use **UTC** with **`Z`**; calendar kickoffs defined in a source timezone (e.g. **Europe/Brussels**) MUST document conversion to UTC for event times.
- **FR-SC-006**: **Jan Breydel capacity 29,062** MUST be named in spec/contract; venue identifiers for home matches SHOULD use a documented constant name (not magic strings only in code).

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: For a published sample calendar and config, **100%** of non-empty lines in a successful output can be classified as valid **ticket_scan** or **merch_purchase** per the feature contract, with **match_id** present where required.
- **SC-002**: **Reproducibility**: two consecutive successful runs with identical inputs yield **byte-identical** files in **100%** of trials (**FR-008**).
- **SC-003**: **Match grouping**: in a multi-match file, an analyst can assign **100%** of match-tied events to the correct fixture using **match_id** without using generator source code.
- **SC-004**: **Merch vs location**: using the contract’s normative rule, a reviewer can justify **item popularity by location** (or document why a row has no location) for both **home** and **away** matches in the sample scenario.
- **SC-005**: **Capacity rule**: in validation tests, **0%** of successful runs accept **home** Jan Breydel attendance **greater than 29,062** without an explicit documented clamp mode.

## Assumptions

- **NDJSON v2** is the interchange for **calendar-driven** output; **v1** files remain valid for **`001`** behavior. **v1** parsers MUST NOT be assumed to read **v2** without change (**FR-010**). A later amendment MAY add **one file per matchday**; **single combined file** is assumed for `002`.
- Currency and **amount** semantics for **merch_purchase** remain **EUR to cent precision** unless the new contract states otherwise.
- **Timezone**: Match kickoffs are provided with enough information to convert to UTC unambiguously (e.g. local time + zone id); ambiguous local times (DST gaps) MUST be resolved by a rule documented in the data-model or contract.
- **Away** attendance caps use a configurable or contract default (e.g. fraction of home capacity or a fixed max away support); exact numbers are planning artifacts, not left implicit in code without documentation.
- Personal data remains synthetic; no real individuals or PII.
- Volume remains **demo-scale** (orders of thousands to low millions of lines per file), not internet-scale batch requirements.
