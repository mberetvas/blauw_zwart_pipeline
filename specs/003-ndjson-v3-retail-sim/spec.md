# Feature Specification: Fan events NDJSON v3 — retail shop simulation (no match context)

**Feature Branch**: `003-ndjson-v3-retail-sim`  
**Created**: 2026-04-05  
**Status**: Draft  
**Input**: User description: "Fan events NDJSON v3 — retail shop simulation (no match context). Problem: v1 rolling and v2 calendar cover stadium/ticket flows and match-tied merch. Need continuous, realistic-feeling retail purchases across three fictional shops: fan shop at Jan Breydel, webshop, shop in Bruges city. Not tied to matches. Specify event model, fields, catalog, time model, output modes (batch vs stream), CLI UX; non-goals: no match_id; default merch-only (no ticket scans)."

## Clarifications

### Session 2026-04-05

- Q: What must be reproducible for **stream** output when `--seed` and parameters are fixed? → A: **Byte-identical stdout** (Option A): with the same `--seed`, same CLI arguments that affect output, and the same environment, two successful runs produce **identical stdout bytes**; each line is canonical JSON per the v3 contract, in a **deterministic emission order** (generation order), which need not match **batch global sort**.
- Q: What should the generator do if the operator does **not** pass explicit shop weights? → A: **Equal default mixture** (Option A): **1/3** weight for each of `jan_breydel_fan_shop`, `webshop`, and `bruges_city_shop`.
- Q: How should **existing v1/v2-only** consumers behave when they encounter `"event":"retail_purchase"`? → A: **Reject / error** (Option A): v1/v2 contracts cover only **`ticket_scan`** and **`merch_purchase`**; **`retail_purchase`** lines are **invalid** for v1/v2 validators. Ingest v3 only via **v3-aware** tooling or a **separate** NDJSON file/stream—no silent skip and no coercing **`retail_purchase`** into **`merch_purchase`**.
- Q: May a `retail_purchase` object contain JSON keys **not** listed in the v3 contract? → A: **Closed schema** (Option A): only **allowed** keys (required plus any optional keys **explicitly** listed for a contract version) may appear; **any other key** ⇒ **invalid** line / validation failure.
- Q: If the operator does **not** pass a simulation **UTC epoch** anchor, what should the generator use? → A: **Fixed default epoch** (Option A): a **single documented constant** in **`fan-events-ndjson-v3.md`**, overridable via CLI; this spec names **`2026-01-01T00:00:00Z`** as that default (**FR-005**).

## User Scenarios & Testing *(mandatory)*

### User Story 1 — Generate a reproducible retail NDJSON file (Priority: P1)

An operator or pipeline owner needs a **single NDJSON file** of synthetic **off-match retail purchases** across three named shops so analysts and demos can show **continuous commerce activity** without fixtures or ticket context. The file MUST be **globally ordered**, **UTF-8**, and **byte-reproducible** when seed and parameters are fixed.

**Why this priority**: Delivers the core interchange artifact for downstream load, QA, and analytics without depending on match calendars or stadium flows.

**Independent Test**: Run generation with fixed `--seed` and parameters twice; compare outputs for **byte identity**; validate every non-empty line against the **v3 contract** (shape, sort order, encoding).

**Acceptance Scenarios**:

1. **Given** fixed seed, shop mixture, arrival model, duration or max-event cap, and output path, **When** the generator completes successfully, **Then** the file contains only **`retail_purchase`** events (no `match_id`, no `ticket_scan` unless an explicit opt-in is added later), with **canonical JSON** and **global sort** per this spec’s ordering rules.
2. **Given** zero events requested or the arrival process yields no purchases in range, **When** generation completes successfully, **Then** the output file is **empty (zero bytes)** on disk, consistent with v1/v2 empty-file rules.

---

### User Story 2 — Tune realism: shops, rates, and arrival process (Priority: P2)

An operator needs to **weight** how often each shop appears and to choose how **inter-arrival times** are drawn (e.g. Poisson-like, fixed rate, or weighted gaps) so the stream **feels** like ongoing retail—not match spikes—while timestamps stay **monotonic** and **UTC**.

**Why this priority**: Distinguishes “continuous retail” from calendar merch without changing v1/v2 contracts.

**Independent Test**: With the same seed, change only shop weights or arrival parameters and observe **deterministic** changes in shop mix and timing; document that **synthetic timeline** rules apply (see Requirements).

**Acceptance Scenarios**:

1. **Given** configurable shop mixture (three shops) summing to 100% (or documented normalization), **When** generation runs, **Then** each emitted line includes a **shop identifier** from the normative set and **item** drawn from the shared catalog (see Key Entities).
2. **Given** a selected arrival process (e.g. Poisson / fixed rate / weighted inter-arrival), **When** generation runs, **Then** assigned **timestamps** advance **monotonically** in UTC and remain on a **synthetic timeline** anchored to a configurable **epoch** (default chosen for reproducibility in the contract).

---

### User Story 3 — Stream retail lines for live demos or pipes (Priority: P3)

A presenter or integrator needs **line-at-a-time** output to **stdout** for piping or slow “ticker” demos, understanding **ordering guarantees** that differ from batch mode.

**Why this priority**: Enables live demos and Unix-style composition without requiring a full file first.

**Independent Test**: Stream N lines and verify **non-decreasing timestamps**; with **`--seed`**, verify **byte-identical stdout** across two runs; verify documented **tie** behavior when multiple events share a timestamp.

**Acceptance Scenarios**:

1. **Given** stream mode, **When** events are emitted, **Then** each line is one JSON object; **timestamps are non-decreasing**; **global lexicographic sort across the entire run is not required** in stream mode—consumers MUST NOT assume full v3 file sort order until they buffer and sort or use batch mode.
2. **Given** optional **max events** or **simulated duration** cap, **When** the cap is reached, **Then** the process exits successfully after the last emitted line.

---

### Edge Cases

- **Zero events (stream)**: Successful run with **zero** emitted events MUST write **zero bytes** to stdout (aligned with v1/v2 **empty file** semantics: no trailing newline when there are no lines).
- **Tied timestamps**: Multiple events may share the same UTC timestamp; batch mode MUST apply deterministic **tie-breakers** (see ordering); stream mode MUST still emit a **non-decreasing** sequence and document behavior for ties (e.g. deterministic order from seed, not necessarily full sort tuple until batch).
- **Shop weights omitted**: If the operator does **not** supply shop weights, the generator MUST use the **default equal mixture** (**1/3** per shop)—see **FR-009**.
- **Shop weights malformed (when supplied)**: If the operator supplies weights that are **invalid** (e.g. negative, wrong count, non-numeric), the generator MUST **fail with non-zero exit** and a clear error—no silent normalization of bad explicit input.
- **Very large outputs**: Memory strategy (buffer-all vs stream) is an implementation detail; batch mode MUST still produce **globally sorted** output as specified.
- **Currency**: Amounts remain **EUR to cent precision**; optional **`currency`** field is **omitted by default**; if ever added, default EUR aligns with v1/v2.
- **Mixed v1/v2 and v3 in one file**: Out of scope for this feature’s **generator output** (v3 runs emit **`retail_purchase`** only). If an operator manually concatenates files, **v1/v2-only** loaders MUST still **reject** **`retail_purchase`** lines per **FR-SC-004** unless the loader is upgraded.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The feature MUST introduce **NDJSON v3** for **match-independent retail** simulation, normatively documented in **`specs/003-ndjson-v3-retail-sim/contracts/fan-events-ndjson-v3.md`** (companion to this spec).
- **FR-002 (Event model — decision)**: Records MUST use a **new event type** **`retail_purchase`** (Option B). **Rationale**: Preserves **v1 and v2 `merch_purchase` record shapes** and semantics (including match-tied use cases) for existing **dbt facts** and parsers; off-match retail is a **distinct business event** (channel/shop-driven), so a separate discriminator avoids silently overloading `merch_purchase` with required shop fields that v1/v2 consumers do not expect.
- **FR-003**: Each **`retail_purchase`** MUST include at minimum: **`event`** (`retail_purchase`), **`fan_id`** (non-empty string), **`item`** (non-empty), **`amount`** (positive EUR, **cent precision**, same numeric rules as v1/v2 merch), **`timestamp`** (UTC, ISO-8601, **`Z`**), and **`shop`** (non-empty string, **one of** the three normative identifiers under Key Entities). For **v3.0**, these are the **only** permitted keys on the object (**closed schema**—see **FR-012**). Future optional fields (e.g. **`currency`**, **`sku`**) require a **contract revision** that lists them explicitly.
- **FR-012 (Closed schema)**: **`retail_purchase`** objects MUST **not** contain **additional** JSON keys beyond those **enumerated** for that **contract version** in **`fan-events-ndjson-v3.md`**. **Any extra key** ⇒ **invalid** record; normative validators and tests MUST **fail** the line. The generator MUST **not** emit spurious keys.
- **FR-004**: The **product catalog** for **`item`** values MUST **reuse the existing `ITEMS` list** in `src/fan_events/domain.py` (same strings as v1/v2 merch catalog) unless a later spec explicitly forks a retail-only list.
- **FR-005 (Time model)**: Timestamps MUST be **strictly monotonic non-decreasing** (ties allowed). The simulation MUST use a **synthetic timeline**: inter-arrival times are drawn from the configured **arrival process** relative to a configurable **UTC epoch**. When the operator does **not** supply an epoch, the generator MUST use the default **`2026-01-01T00:00:00Z`** as the **simulation start** (first event time follows the arrival model from this anchor—exact offset rules in the contract). The CLI MUST allow **overriding** this default. **Wall-clock time** MUST NOT define event times in normative output; optional **wall-clock pacing** (delay between printed lines in stream mode for human demos) MAY exist but MUST NOT change the **UTC timestamp values** on records.
- **FR-006**: The generator MUST support **configurable arrival processes** including at least: **Poisson / exponential inter-arrival**, **fixed rate** (deterministic spacing), and **weighted inter-arrival** (documented in the contract). Same inputs + seed MUST yield the **same** event sequence and times in batch mode.
- **FR-007 (Batch/file mode)**: When writing a **file**, the generator MUST apply **global sort** before write, using a **total ordering** documented in the v3 contract, aligned with v1/v2 spirit: primary **`timestamp`**, then **`event`** (for v3 retail-only files this is trivial), then **`fan_id`**, then **`shop`** identifier, then **`item`**, then **`amount`** (adjust only if the contract lists a finer tie-break for byte stability). Empty successful run ⇒ **zero-byte file** (same family as v1/v2).
- **FR-008 (Stream mode)**: Stream mode MUST write **one JSON object per line** to **stdout**, each record line ending with **LF** (`\n`); when there is at least one line, the stream MUST end with a **single** trailing newline after the last line (POSIX text stream), consistent with v1/v2 **file** line rules. When there are **zero** lines, stdout MUST contain **zero bytes**. **Global lexicographic sort across the full run is NOT guaranteed** (emission order is **deterministic generation order**, which need not match batch **global sort**). **Guaranteed**: **non-decreasing `timestamp`** sequence along the emitted order. When **`--seed`** is set and all other parameters affecting output are fixed, **stdout MUST be byte-identical** across successful runs (see **FR-SC-002**). Consumers needing **global sort** MUST use batch mode or sort client-side.
- **FR-009 (CLI — high level)**: The CLI MUST expose **retail v3** via a **dedicated subcommand or clearly scoped flags** (exact names in `quickstart`/contract) including: **`--seed`**, parameters for **arrival model** and **rate**, **optional max events** and/or **simulated duration**, **optional shop mixture/weights** for the three shops, **optional simulation epoch** (UTC) overriding the default **`2026-01-01T00:00:00Z`**, **mode selection** (file vs stream), and **output path** for file mode. When shop weights are **omitted**, the generator MUST apply the **default equal mixture**: **1/3** probability mass each for **`jan_breydel_fan_shop`**, **`webshop`**, and **`bruges_city_shop`** (document exact representation—e.g. three equal weights—in the contract).
- **FR-010**: Outputs MUST use **canonical JSON** rules consistent with v1/v2 (`sort_keys`, compact separators, UTF-8, `ensure_ascii=False`) unless v3 contract documents a single deliberate delta.
- **FR-011 (Non-goals)**: **`match_id`** MUST NOT appear on v3 records. **`ticket_scan`** events MUST NOT be emitted in the default **merch-only retail** configuration; if a future option adds ticket scans, it MUST be **explicitly opted in** and documented outside this feature’s default scope.

### Key Entities

- **`retail_purchase` event**: A single off-match retail line with shop context; no match linkage. **Normative keys (v3.0)**—each line’s JSON object contains **exactly** these properties and **no others**: `event`, `fan_id`, `item`, `amount`, `timestamp`, `shop` (all required for v3.0).
- **Shop**: Required field **`shop`** with value **one of** these **stable string identifiers** (use consistently in raw NDJSON); **display labels** in this list are **non-normative** (for humans and `dim_shop`); interchange uses **`shop`** values only:
  - `jan_breydel_fan_shop` — Jan Breydel fan shop (in-stadium retail)
  - `webshop` — Webshop
  - `bruges_city_shop` — Bruges city shop
- **Default shop mixture**: When weights are not configured, each shop’s selection weight is **1/3**.
- **Simulation epoch (default)**: **`2026-01-01T00:00:00Z`** — UTC anchor for the synthetic timeline when the CLI does not override it (**FR-005**).
- **Fan**: Same conceptual **`fan_id`** space as existing generators (non-empty string); selection rules defined in contract (e.g. pool size, reuse).
- **Catalog item**: String from shared **`ITEMS`** in `domain.py`.

### Analytics & warehouse *(mandatory when feature touches analytics, fan-360, or agent Q&A)*

Per project constitution:

- **FR-WH-001**: Downstream analytics SHOULD map this stream to a new or extended fact, provisionally **`fct_retail_purchases`**, with a **`dim_shop`** (or equivalent) keyed by the normative shop identifier; existing **`fct_merch_purchases`** for v1/v2 remains for **match-tied merch** unless the dbt project explicitly unions models with clear grain documentation.
- **FR-WH-002**: Raw NDJSON handling remains **append-only/immutable**; shop display names and geo enrichment belong in **dbt**, not required in raw lines.
- **FR-WH-003**: Model changes SHOULD ship with **dbt tests** (`not_null`, `unique` where applicable, business rules)—owned by the dbt workstream when marts are added.

### Python scripts and packaged code *(mandatory when feature touches generators, CLIs, or modules under `src/`, `scripts/`, or equivalent)*

Per project constitution:

- **FR-PY-001**: New or changed Python behavior MUST be covered by **pytest**; prefer **TDD**.
- **FR-PY-002**: Dependencies and runs MUST go through **UV**; lockfile aligned with `pyproject.toml`.
- **FR-PY-003**: Generator runtime SHOULD remain **stdlib-only** unless this spec is amended with a justified dependency.

### Spec, contracts, and synthetic interchange *(mandatory when feature defines NDJSON, events, or machine-readable handoff files)*

Per project constitution:

- **FR-SC-001**: Normative behavior MUST live in this **`spec.md`** and **`specs/003-ndjson-v3-retail-sim/contracts/`**; implementation MUST match the cited **contract version**.
- **FR-SC-002**: With **`--seed`** set and every other input that affects output held fixed, **batch/file mode** MUST produce **byte-identical** output **files** across two successful runs on the same environment; **stream mode** MUST produce **byte-identical** **stdout** across two successful runs under the same conditions (same quality bar as v1/v2 for deterministic configs). Omitting **`--seed`** MAY yield non-deterministic output; if so, behavior MUST be stated in the contract.
- **FR-SC-003**: Tests MUST validate **shape**, **ordering** (batch global sort; stream non-decreasing time), **encoding**, and—where **`--seed`** is used—**byte identity** for both file and stream outputs per contract.
- **FR-SC-004**: This feature adds **v3**; it MUST NOT silently change v1/v2 line meanings. **v1 and v2** interchange contracts allow only **`event`** values **`ticket_scan`** and **`merch_purchase`**. Lines with **`event":"retail_purchase"`** MUST be treated as **invalid input** by **v1/v2-only** validators and loaders (reject / fail validation—no silent drop, no silent coercion to **`merch_purchase`**). **v3** data MUST be consumed with **v3-aware** parsers or a **dedicated** v3 ingest path; migration and consumer expectations MUST be documented in **`fan-events-ndjson-v3.md`**.
- **FR-SC-005**: Timestamps MUST be **UTC** with **`Z`** suffix.
- **FR-SC-006**: **Shop identifiers**, **Jan Breydel** naming, and the **default retail simulation epoch** (**`2026-01-01T00:00:00Z`**) MUST be **named and documented** in spec/contract, not only ad hoc literals in code.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: For a published **golden configuration** (seed, epoch, arrival parameters, shop weights, event cap), **100%** of non-empty lines in batch output validate as **`retail_purchase`** per the v3 contract with **correct global order**.
- **SC-002**: For stream mode, **100%** of emitted lines have **`timestamp` ≥ previous line’s `timestamp`** on the same run (non-decreasing), verified over an agreed test length (e.g. ≥ 1,000 lines); for a fixed golden **`--seed`** and parameters, **two successful runs produce identical stdout bytes**.
- **SC-003**: **Operators** can generate a **batch file** suitable for load testing (e.g. ≥ 50,000 lines) without manual post-sort, with **documented** failure behavior on invalid configuration (non-zero exit, no partial durable file).
- **SC-004**: **Analyst-facing documentation** (feature quickstart or README pointer) explains **synthetic vs wall-clock**, **batch vs stream ordering**, and **why `retail_purchase` is separate from `merch_purchase`**, in language understandable to non-developer stakeholders.

## Assumptions

- **A-001**: “Realistic-feeling” is achieved through **shop mixture**, **catalog diversity**, and **stochastic inter-arrival**—not through real POS integration.
- **A-002**: Three shops are **fictional labels** aligned with the Club Brugge setting but **no** real store systems are implied.
- **A-003**: **Default product scope** is **retail purchases only** (no ticket scans); extending to tickets requires a **separate** explicit decision and contract bump.
- **A-004**: EUR **cent precision** and positive amounts match v1 **`merch_purchase`** conventions unless the v3 contract documents an exception.
- **A-005**: If shop weights are omitted, operators get the **equal 1/3 default** per **FR-009**.
- **A-006**: If no simulation epoch is passed, timestamps are anchored from **`2026-01-01T00:00:00Z`** per **FR-005** (not wall-clock).

## Dependencies

- Existing **`ITEMS`** catalog in `src/fan_events/domain.py`.
- Established **NDJSON** quality bar from **001**/**002** (UTF-8, canonical JSON, empty file rule) for batch outputs.

## Out of Scope

- Match calendars, **`match_id`**, kickoff windows, attendance caps, or stadium entry (**ticket_scan**) in the default configuration.
- Replacing or mutating **v1** rolling or **v2** calendar generators; v3 is an **additional** simulation mode.
- dbt model implementation details beyond provisional mart names (handled in planning/build).
