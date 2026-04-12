# Feature Specification: Continuous unified stream with master clock and match-day retail

**Feature Branch**: `006-stream-three-event-kinds`  
**Created**: 2026-04-12  
**Status**: Draft  
**Input**: User description: "Extend fan_events so one CLI path emits a single time-ordered NDJSON stream with all three event kinds: ticket_scan, merch_purchase, retail_purchase, using v2 + v3 field shapes as documented. Continuous calendar seasons, one master synthetic timeline, match-day-weighted retail, same output modes as existing stream. v1 rolling out of scope."

## Clarifications

### Session 2026-04-12

- Q: What exactly ends one synthetic “season” and starts the next cycle (calendar-driven v2), relative to `--from-date` / `--to-date` and the master clock? → A: **Year-shifted replay (Option A)** — One **season pass** emits every match in the template within the configured `--from-date` / `--to-date` window **once** (same semantics as today’s calendar walk). Each subsequent pass replays the **same** matches with scheduled instants shifted by **+1 calendar year** on the master timeline for each lap (**+1y**, then **+2y**, **+3y**, …), preserving fixture spacing from the template, keeping synthetic time strictly forward, and avoiding timestamp collisions across passes.
- Q: How do `--max-events` and `--max-duration` (post-merge on `stream`) interact with repeated year-shifted season passes? → A: **Global cumulative (Option A)** — **`--max-events`** counts **total merged lines** emitted since **process start** (all passes). **`--max-duration`** caps the **cumulative simulated span** from the stream’s agreed **`t0`** anchor on the **master timeline**, using **every** candidate line’s synthetic timestamp (v2 + v3); the run stops **before** emitting a line that would exceed the window. Caps **do not reset** at season boundaries. When **both** caps are set, the **first-triggered** limit wins, per **004** / `cli-stream.md`.
- Q: For default match-day retail weighting, which days count as a “match day” (including away-heavy calendars)? → A: **Home fixtures only (Option B)** — By default, a **match day** is a day with **at least one home** match in the filtered template; **away-only** days use the **non-match-day** baseline. **Away match-day** boost is enabled only when **`--retail-away-match-day-enable`** is set (see **FR-006**).
- Q: How should `retail_purchase` volume relate to match-day tuning (rate vs count)? → A: **Rate-based arrivals (Option A)** — Retail follows the **same conceptual model** as **003** / `generate_retail` (**stochastic**, **rate**-driven arrivals over synthetic time on the **master clock**, e.g. Poisson or documented equivalent). Match-day flags **scale** the applicable **base rate** or **piecewise intensity**; **per-day counts are emergent**, not fixed quotas.
- Q: Where do exact new CLI flag names and defaults live? → A: **Inline in `spec.md` (Option A)** — **Exact** spellings and **defaults** are normative in **FR-006** below; **`specs/006-stream-three-event-kinds/contracts/`** MUST **mirror** the same strings and values (no drift).

## User Scenarios & Testing *(mandatory)*

### User Story 1 - One endless, coherent mixed stream (Priority: P1)

An operator runs the unified `fan_events` stream with a repository calendar (for example `match_day.example.json`) and expects a **single** NDJSON stream that never stops merely because the calendar’s date range or match list was walked once. After one synthetic “season” completes, the next season **reuses the same calendar template** on a **continued synthetic timeline** so ticket scans, merchandise purchases tied to matches, and retail purchases keep appearing in **global time order** until the operator stops the process or an explicit limit is reached.

**Why this priority**: Without continuous seasons and a shared timeline, long-running demos, recordings, and soak tests cannot represent a believable club year after year in one process.

**Independent Test**: Run merged mode with a known calendar, no post-merge caps, interrupt manually after observing at least two full calendar cycles; confirm all three event kinds appear and timestamps remain non-decreasing across the boundary between cycles.

**Acceptance Scenarios**:

1. **Given** merged stream mode with a valid calendar and retail enabled, **When** the calendar iterator completes one full pass over the configured date range, **Then** the generator **starts the next season pass** by replaying the same template matches with instants shifted **+1 calendar year** on the master timeline (and so on for later passes), without requiring a restart, and emission continues unless `--max-events` / `--max-duration` (post-merge) stops the run or the operator interrupts.
2. **Given** the same inputs, **When** events from v2-style match flows and v3 retail are both emitted, **Then** every line’s synthetic timestamp is produced from **one master synthetic clock** so retail times do not drift independently from match-relative scheduling across repeated seasons.
3. **Given** default match-day retail tuning, **When** the operator compares retail event density on **home match days** versus **days with no home match** (including away-only fixture days) over a long sample, **Then** **home match days** show **materially higher** retail activity (measurable in tests via counts or rates over equivalent simulated spans).

---

### User Story 2 - Explainable match-day retail tuning (Priority: P2)

An operator wants retail traffic to **rise on home match days** by default and optionally **peak near home kickoff**, and needs **CLI flags** with **documented defaults** and **plain-language explanation** in `--help` (for example home match-day multiplier, pre/post kickoff window in minutes, optional **away match-day** boost for away-heavy schedules). **Away-only** fixture days use the **non-match-day** baseline **unless** the operator opts in to away boost.

**Why this priority**: Realistic load shapes depend on stadium traffic patterns; tunability without documentation is not operable.

**Independent Test**: Run with defaults and with an alternate flag set; compare retail counts inside vs outside match windows using fixed seeds and bounded runs.

**Acceptance Scenarios**:

1. **Given** default CLI flags, **When** the stream runs for a bounded simulated period containing **home match days**, **away-only fixture days**, and **days with no fixtures**, **Then** documented default parameters yield higher retail intensity on **home match days** than on **away-only days** and **non-fixture days** (all treated as non-match-day baseline for the default boost).
2. **Given** explicit non-default multipliers and window lengths, **When** the operator passes those flags, **Then** behavior changes in the direction implied by the names (documented), without breaking v2/v3 field shapes.
3. **Given** **`--retail-away-match-day-enable`** and default **`--retail-away-match-day-multiplier`**, **When** the operator enables away boost, **Then** **away-only** fixture days receive elevated retail **rate** per **FR-006**, still deterministically for a fixed seed.

---

### User Story 3 - Same delivery paths as today’s stream (Priority: P3)

An operator expects **stdout**, **append-only file**, optional **wall-clock pacing**, optional **Kafka** when the optional extra is installed, and optional **post-merge** `--max-events` / `--max-duration` limits, consistent with `specs/004-unified-synthetic-stream/contracts/cli-stream.md`. Event **payload schemas** stay as today unless this feature deliberately versions contracts and updates tests.

**Why this priority**: Output and limits must stay familiar so existing playbooks keep working.

**Independent Test**: Exercise each output path and limit type in automated tests where feasible; document any path not implemented in this iteration.

**Acceptance Scenarios**:

1. **Given** no output path flag, **When** the operator runs the command, **Then** NDJSON lines are written to **standard output** as today (UTF-8, LF-terminated).
2. **Given** append file mode, **When** the operator runs the command, **Then** lines are appended without rotation, as today.
3. **Given** Kafka options and the optional dependency installed, **When** the operator enables Kafka, **Then** behavior matches the existing `stream` Kafka contract; if this iteration ships only a subset, the spec and checklist note the gap explicitly.
4. **Given** `--max-events` and/or `--max-duration` and a run that crosses **multiple** year-shifted passes, **When** limits are approached, **Then** termination follows **global cumulative** counting from process start / **`t0`** (no per-pass reset), consistent with **Clarifications (2026-04-12)** and **FR-009**.

---

### Edge Cases

- **Season vs pass**: A **season pass** is defined per **Clarifications (2026-04-12)** (year-shifted replay); it is **not** tied to a civil calendar year unless the operator’s `--from-date` / `--to-date` window happens to coincide with one.
- **Post-merge limits**: **`--max-events`** and **`--max-duration`** are **global from process start**: they count **all merged lines** and **simulated time from `t0`** across **every year-shifted pass** until the run stops; they **do not** reset when a new pass begins. Stop semantics match **004** / `cli-stream.md` (**first limit wins** when both are set; duration evaluated so the **next** line would exceed the window). Limits apply to the **merged** stream, not to “one calendar lap” only.
- **Season rollover**: Entering the next pass MUST **not** introduce a separate retail timeline; v2 and v3 continue on the **same** master clock. Match kickoffs in pass **k** (for **k ≥ 0**) are the template-derived schedule plus **k** **calendar years** on the master timeline (normative formulas and edge cases for leap-day fixtures belong in contracts).
- **Empty valid calendar in range**: No v2 lines for that span; retail may still emit unless disabled; ordering and master clock remain well-defined.
- **Calendar error**: Invalid path or JSON fails fast with the same class of error as `generate_events --calendar` (non-zero exit, clear message).
- **Tie on timestamp**: Total order follows `contracts/orchestrated-stream.md` (timestamp, then `event`, then stable line encoding).
- **Ctrl+C / interrupt**: Documented flush behavior; no requirement to emit a partial final line (align with 004 unless amended in contracts).
- **Retail-only or calendar-only modes**: Remain valid per `cli-stream.md`; continuous season and match-day weighting apply only where the relevant source is active (e.g. match-day weighting affects retail only when retail is enabled). **Calendar-only** (`--calendar` with **`--no-retail`**) MUST use the **same default season recycling** as merged mode (**FR-004**, **`--no-calendar-loop`** opt-out) so operators do not get a single-pass calendar unless they opt out; **retail-only** (no `--calendar`) has no calendar loop semantics.
- **Default “match day” = home fixture day**: Per **Clarifications (2026-04-12)**, default boosted days are those with **≥1 home** match; **away-only** days follow the **non-match-day** baseline unless **away match-day** boost is enabled. **All-away** calendars therefore have **no** default boosted days until that flag (or future related flags) is used.
- **Retail volume model**: `retail_purchase` emission is **rate-based** on the **master timeline** (see **Clarifications (2026-04-12)**): acceptance tests compare **emergent counts** or **rates** over bounded windows with **fixed seeds**, not fixed per-day **quotas**, unless a future spec adds quota flags.
- **Invalid tuning flags**: Non-positive multipliers or negative minute windows MUST be rejected at CLI parse time with a **clear error** (non-zero exit).

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The product MUST extend the existing **`fan_events stream`** path (or add a clearly documented alias subcommand that delegates to the same implementation) so that **merged** mode emits **all three** event kinds in one stream: **`ticket_scan`**, **`merch_purchase`**, **`retail_purchase`**, each line conforming to the **existing v2 and v3 interchange shapes** documented for those types; **v1 rolling** generation remains **out of scope** for `stream`.
- **FR-002**: Emit order MUST remain **non-decreasing** on the **total order** defined in `specs/004-unified-synthetic-stream/contracts/orchestrated-stream.md` (synthetic UTC instant, then `event`, then stable JSON line encoding).
- **FR-003**: **Master synthetic clock**: All emitted events MUST draw their synthetic timestamps from **one shared advancing timeline** anchored to the stream’s agreed time origin (per existing 004 research/contract interpretation), so v2 match-relative scheduling and v3 retail timestamps **stay coherent** across **repeated** calendar cycles; retail MUST NOT use a separate timeline that resets or drifts relative to match scheduling between seasons.
- **FR-004**: **Continuous calendar seasons**: A **season pass** completes when the calendar-driven iterator has emitted all matches in the template that satisfy the operator’s **`--from-date` / `--to-date`** filter **once** (same semantics as today’s calendar walk). When that pass completes, the implementation MUST **automatically begin the next pass** over the **same calendar template** on the **continued** master timeline by shifting every match’s scheduled instants **forward by one calendar year** relative to the prior pass (first repeat **+1y**, then **+2y**, **+3y**, …), preserving within-season spacing from the template, maintaining **strictly non-decreasing** synthetic times across pass boundaries, and avoiding reuse of identical timestamps across passes. The process MUST **not** terminate solely because one pass exhausted **unless** the operator set a post-merge cap or an error occurred.
- **FR-005**: **Match-day retail weighting**: **`retail_purchase`** MUST be produced by a **rate-based** **stochastic arrival** process on the **master synthetic timeline**, **conceptually aligned** with **003** / `generate_retail` (e.g. **Poisson** or documented equivalent—not **fixed daily event quotas**). **Home match-day** and optional **away match-day** tuning MUST **scale** the applicable **baseline retail rate** `R_base` (from existing retail CLI, e.g. **`--poisson-rate`**, per **004** / **003**); **event counts per day** are **emergent**. When retail is enabled alongside a calendar, **expected** intensity (and, over long bounded samples, **emergent counts**) MUST be **higher on home match days** than on **all other days** (including **away-only** days when away boost is **off**). A **home match day** is any **local calendar day** (per contract timezone rules) with **≥1 home** match in the filtered template. **Normative flag names, defaults, and intensity rules** are **FR-006**; **`--help`** MUST describe them in plain language. The piecewise formula MUST be **deterministic for a fixed seed**; fine-grained math (e.g. overlapping home kickoff windows) is **specified in contracts** but MUST be consistent with **FR-006**.
- **FR-006**: **Normative match-day retail CLI** (`fan_events stream`, merged calendar + retail): The following flags and defaults are **normative**; **`specs/006-stream-three-event-kinds/contracts/`** MUST **mirror** this list **verbatim** (same spellings and default values).
  - **`--retail-home-match-day-multiplier`**: type **`float`**, default **`2.0`**, MUST be **`> 0`**. On any synthetic instant on a **home match day**, outside all **home kickoff windows** (next bullets), retail intensity uses **`R_base ×` this value**.
  - **`--retail-home-kickoff-pre-minutes`**: type **`int`**, default **`90`**, MUST be **`≥ 0`**. For each **home** match, defines a window start at **`kickoff − pre`** on the **master timeline**.
  - **`--retail-home-kickoff-post-minutes`**: type **`int`**, default **`120`**, MUST be **`≥ 0`**. Window end at **`kickoff + post`** for that home match.
  - **`--retail-home-kickoff-extra-multiplier`**: type **`float`**, default **`1.5`**, MUST be **`> 0`**. For synthetic instants inside **any** home match’s **`[kickoff − pre, kickoff + post]`** window, intensity uses **`R_base × retail-home-match-day-multiplier ×` this value** (multiplicative stacking).
  - **`--retail-away-match-day-enable`**: **boolean**, default **`false`**. When **`false`**, **`--retail-away-match-day-multiplier`** is ignored and **away-only** days use **`R_base`** only.
  - **`--retail-away-match-day-multiplier`**: type **`float`**, default **`1.75`**, MUST be **`> 0`**. When **enable** is **`true`**, **away-only fixture days** (≥1 away, **no** home match that local day) use **`R_base ×` this value**. Days with **both** home and away are **home match days**; **away multiplier does not apply**.
- **FR-007**: **Output encoding**: One JSON object per line, **UTF-8**, **LF** (`\n`) line endings, stable key ordering and encoding rules unchanged unless contracts are versioned.
- **FR-008**: **Output destinations**: MUST support **stdout**, **append-only file**, and **optional Kafka** with the **same** baseline and optional-extra split as feature 004; any **partial** implementation in the first delivery MUST be listed explicitly in this spec’s **Assumptions** and in the feature checklist until closed.
- **FR-009**: **Post-merge limits**: **`--max-events`** and **`--max-duration`** on `stream` MUST keep **004** / `cli-stream.md` semantics on the **merged** output: **`--max-events`** stops after **N** complete merged lines since **process start** (across all season passes). **`--max-duration`** bounds **cumulative simulated time** from the stream **`t0`** anchor on the **master timeline** for **all** event kinds; the implementation MUST stop **before** emitting a line whose synthetic timestamp would exceed the window. Limits MUST **not** reset when a new year-shifted pass begins. When **both** are set, the **first-triggered** limit MUST apply, as in **004**. Help MUST still warn when both are omitted (unbounded resource use).
- **FR-010**: **Determinism**: For **fixed** inputs (calendar, seeds, flags, and **bounded** termination), two successful runs MUST produce **byte-identical** output, consistent with `orchestrated-stream.md`, unless a documented exception applies.
- **FR-011**: **Contract parity**: Normative CLI and merge behavior remain under **`specs/004-unified-synthetic-stream/contracts/`** as amended by **`specs/006-stream-three-event-kinds/contracts/`** for new flags and continuous-stream semantics; **006** contracts MUST reproduce **FR-006** exactly (flags + defaults) and extend with formulas (**overlapping windows**, leap-day **year-shift**, etc.) without contradicting this spec. Implementation MUST match the **cited contract version** after updates.
- **FR-012**: **Non-goals**: Do **not** contradict feature **004** baseline semantics without an explicit spec/contract amendment. Do **not** add v1 rolling to `stream`.

### Key Entities

- **Master synthetic timeline**: Single monotonic synthetic-time basis shared by v2 scheduling and v3 retail for the lifetime of the process (across seasons).
- **Calendar template**: The same structured schedule input (matches with `match_id`, local kickoff, timezone, attendance, home/away, venue, etc.) reused each lap; each lap applies an additional **+1 calendar year** offset on the master timeline to the template-derived instants.
- **Season pass**: One full traversal of all matches from the template that fall in the configured **`--from-date` / `--to-date`** window; pass index **k = 0, 1, 2, …** places match instants at **template time + k calendar years** on the master timeline. Retail and merge use the **same** master clock across passes (no independent reset per pass).
- **Retail arrival intensity**: **Rate** or **piecewise intensity** function on the **master timeline**, driven by the same **family** of arrival semantics as **003**; **home** / **away** match-day rules **scale** this intensity (not fixed per-day counts).
- **Match-day retail profile**: The combination of default and CLI-tunable factors that elevate **retail arrival intensity** on **home match days** (and optionally **away** fixture days when away boost is enabled), including windows around **home** kickoff when configured.
- **Merged NDJSON line**: One v2- or v3-contract-valid JSON object per line, as in feature 004.

### Python scripts and packaged code *(mandatory when feature touches generators, CLIs, or modules under `src/`, `scripts/`, or equivalent)*

Per project constitution:

- **FR-PY-001**: New or changed Python behavior MUST be covered by **pytest**; contributors MUST prefer **test-first** development.
- **FR-PY-002**: Dependencies and runs MUST follow the project’s **UV** workflow; lockfile stays aligned with manifest policy.
- **FR-PY-003**: Generator and CLI **runtime** code MUST remain **stdlib-only** except where an existing optional extra (e.g. Kafka) applies per constitution **VI**; no new mandatory non-stdlib dependency for core streaming.
- **FR-PY-004**: Structure MUST follow constitution **XIII**: use **classes** where coordinated state (master clock, seasonal calendar, merge) benefits; **functions** for straightforward transforms.

### Spec, contracts, and synthetic interchange *(mandatory when feature defines NDJSON, events, or machine-readable handoff files)*

Per project constitution:

- **FR-SC-001**: Normative behavior for **new** flags and **continuous / master-clock** rules MUST be recorded in this `spec.md` and **`specs/006-stream-three-event-kinds/contracts/`**, with links to **004** contracts for unchanged merge and CLI baselines.
- **FR-SC-002**: **Deterministic replay** applies to **bounded** runs with fixed seed as in **FR-010**; unbounded manual-stop runs are validated by partial prefixes with caps in tests.
- **FR-SC-003**: Tests MUST assert **shape**, **global time order**, **encoding**, and **home match-day vs non-home-match-day retail** behavior per contracts (plus **away match-day** behavior when that optional flag is enabled), using **emergent counts** or **rates** consistent with the **rate-based** model in **FR-005** and **Clarifications (2026-04-12)**.
- **FR-SC-004**: Any incompatible NDJSON or field change MUST be **versioned** with migration notes; default is **no** breaking shape changes.
- **FR-SC-005**: Timestamps remain **UTC with `Z`** per existing interchange rules; calendar local times document source timezone and conversion as today.
- **FR-SC-006**: Normative tuning defaults and flag spellings MUST appear in **FR-006** and be **mirrored** in **`specs/006-stream-three-event-kinds/contracts/`**, not only as unexplained literals in code.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: With a standard example calendar and merged mode, an operator can run the stream **indefinitely** until **manual interrupt**, with **no automatic stop** solely because one **year-shifted** calendar pass finished, except when an explicit **post-merge** event or duration cap is set—and those caps, when present, are **cumulative from process start / `t0`** across **all** passes until the run stops.
- **SC-002**: Over any observed window of **at least 1000** emitted merged lines (or the project’s chosen regression fixture length), **100%** of consecutive line pairs have **non-decreasing** synthetic timestamps per the contract sort key.
- **SC-003**: Under **default** parameters (including **FR-006** defaults, with **`--retail-away-match-day-enable` false**), a **repeatable bounded scenario** shows **emergent** `retail_purchase` activity on **home match days** exceeding activity on **days without a home match** (including **away-only** fixture days) by a **clear margin** (e.g. count or rate over equal simulated spans); the **minimum ratio** (or equivalent test statistic) is **fixed in the feature contract** and verified by an automated acceptance check so the outcome is objective, not subjective.
- **SC-004**: All **automated tests and static analysis** required by the project pass on the branch before merge.
- **SC-005**: **Operator clarity**: `--help` documents **FR-006** flags so a non-developer operator can predict **directional** effects (e.g. raising **`--retail-home-match-day-multiplier`**, widening **`--retail-home-kickoff-pre-minutes` / `--retail-home-kickoff-post-minutes`**, turning on **`--retail-away-match-day-enable`**) without reading source code.

## Assumptions

- **A-001**: Baseline behavior, flag names for existing **004** `stream` features, and merge ordering remain as in **004** unless amended here; **new** match-day flags are **additive** and normatively listed under **FR-006** in this document.
- **A-002**: Example calendars in the repo (e.g. `match_day.example.json`) are representative test inputs; field names align with **002** calendar conventions.
- **A-003**: **Kafka** parity is **expected** to match **004**; if any Kafka path lags, the first PR **documents** the gap and tracks follow-up in the checklist until closed.
- **A-004**: **README** and minimal **spec cross-links** are updated so contributors find the master-clock model and match-day parameters; the PR description summarizes the same for reviewers.
- **A-005**: “Materially higher” retail on **home match days** vs **non-home-match days** is validated quantitatively in tests (**SC-003**); exact economic realism is not required.
- **A-006**: **`retail_purchase`** volume uses **003**-aligned **rate-based** arrivals; there are **no** normative fixed **per-day event quotas** in this feature unless added in a later spec revision.

## Dependencies

- **`specs/004-unified-synthetic-stream/`** (normative `stream` behavior, `cli-stream.md`, `orchestrated-stream.md`).
- **`specs/002-match-calendar-events/`** (calendar semantics and v2-style match events).
- **`specs/003-ndjson-v3-retail-sim/`** (`retail_purchase` semantics).

## Deliverables

- Implementation in `src/` (and tests) extending `fan_events stream` per this spec.
- **pytest** coverage for continuous seasons, master-clock coherence, match-day retail weighting, ordering, and CLI smoke.
- **Contracts** under `specs/006-stream-three-event-kinds/contracts/` amending or extending 004 docs as needed, including a **verbatim mirror** of **FR-006** plus formula details (overlapping windows, leap days, etc.).
- **Minimal** README / spec pointer updates.
- **PR note** explaining the **master-clock model** and **match-day retail parameters**.
