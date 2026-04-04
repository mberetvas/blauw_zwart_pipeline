# Feature Specification: Synthetic fan event source

**Feature Branch**: `001-synthetic-fan-events`  
**Created**: 2026-04-04  
**Status**: Draft  
**Input**: User description: "Add a synthetic fan event source: fans generate ticket_scan events (stadium location + time) and merch_purchase events (item + amount + time). Events must be machine-readable for a later pipeline into a warehouse and dbt. Prioritize a small, clear data contract and reproducible demos (same seed → same file)."

## Clarifications

### Session 2026-04-04

- Q: Normative serialization for each output line? → A: **Option A** — JSON Lines (NDJSON): one UTF-8 JSON object per non-empty line; schema per value of the **`event`** property documented in the contract.
- Q: How MUST lines be ordered in the output file? → A: **Option A** — Global sort by event occurrence time ascending; ties broken deterministically (`event` property, then synthetic fan identifier, then further keys per contract).
- Q: If generation would emit an invalid or incomplete record? → A: **Option A** — **Fail fast**: abort with non-success; do not deliver a complete consumable output file (contract may define atomic write: temp then rename only on full success).
- Q: Where MUST successful NDJSON be delivered? → A: **Option A** — **Primary: filesystem file path** (operator-supplied and/or documented default for the demo); not stdout as the normative success channel.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Published contract and valid events (Priority: P1)

A demo owner needs a **small, explicit contract** for synthetic fan activity so that anyone (or a later
pipeline) can tell whether an output file is valid without reverse-engineering code.

**Why this priority**: Without a contract, “machine-readable for warehouse and dbt” is meaningless and
demos are not repeatable across tools.

**Independent Test**: Given the published contract, an independent reviewer can classify any line in a
sample file as valid or invalid for `ticket_scan` and `merch_purchase`, and list missing or malformed
required fields.

**Acceptance Scenarios**:

1. **Given** the contract documentation, **When** a `ticket_scan` record is inspected, **Then** it MUST
   include stadium location, occurrence time, and a stable fan identifier, and MUST have **`event`**
   equal to `ticket_scan`.
2. **Given** the contract documentation, **When** a `merch_purchase` record is inspected, **Then** it
   MUST include item description, purchase amount (strictly positive), occurrence time, and a stable fan
   identifier, and MUST have **`event`** equal to `merch_purchase`.

---

### User Story 2 - Reproducible demo output (Priority: P2)

A demo owner runs the synthetic source twice with the **same seed and parameters** and must obtain the
**same ordered file content** so recordings, docs, and CI checks stay stable.

**Why this priority**: Reproducibility is an explicit product goal for trustworthy demos and automated
checks.

**Independent Test**: Run the generator twice with identical inputs; compare outputs **byte-for-byte**;
they MUST match.

**Acceptance Scenarios**:

1. **Given** a fixed seed and fixed generation parameters and the **same output path**, **When** the
   synthetic source is executed twice successfully, **Then** the files at that path MUST be
   **byte-identical** (FR-005).
2. **Given** two different seeds, **When** outputs are compared, **Then** they MAY differ (no requirement
   of uniqueness across seeds beyond reproducibility for the same seed).

---

### User Story 3 - Batch suitable for downstream handoff (Priority: P3)

A downstream owner receives a file of synthetic events and can **split or load** records without
ambiguity (one record per line, self-contained, no multi-line records).

**Why this priority**: Keeps the handoff to warehouse loading and dbt simple for the demo pipeline.

**Independent Test**: Split the file on line boundaries; every non-empty line MUST stand alone as one
logical event per the contract.

**Acceptance Scenarios**:

1. **Given** a generated demo file, **When** it is split into lines, **Then** each non-empty line MUST
   represent exactly one event and MUST be parseable without reading other lines.
2. **Given** a generated demo file, **When** events are counted by type, **Then** both `ticket_scan` and
   `merch_purchase` MUST appear at least once in the default demo configuration (unless a parameter
   explicitly requests only one type).
3. **Given** a generated demo file, **When** occurrence timestamps are read in file order, **Then** they
   MUST be **monotonically non-decreasing**, and ties MUST follow the contract’s deterministic tie-break
   order (FR-007).

### Edge Cases

- **Ambiguous or invalid amounts**: If a `merch_purchase` would have amount zero, negative, or
  non-numeric, the run MUST **abort** (FR-008); no line violating the contract is written to the
  durable output.
- **Missing required fields**: If any event cannot be fully populated per the contract, the run MUST
  **abort** (FR-008); partial valid-only files are not allowed as successful output.
- **Ordering**: For a given seed, lines MUST appear in **global ascending** order of event occurrence
  time; equal timestamps MUST be ordered by the contract’s tie-break sequence (minimum: **`event`**
  property, then synthetic fan identifier, then any keys needed to break remaining ties).
- **Location and item text**: Stadium location and item MAY contain Unicode inside JSON strings; the
  **file** is always UTF-8 per FR-004.
- **Write failures**: If the output file cannot be written completely (permissions, disk full, etc.),
  the run MUST **abort** with non-success per FR-008; no durable partial file as successful output.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The synthetic source MUST emit `ticket_scan` events that include stadium location,
  occurrence timestamp, and a stable synthetic fan identifier, and MUST set the **`event`** property
  unambiguously in each record.
- **FR-002**: The synthetic source MUST emit `merch_purchase` events that include item description,
  strictly positive purchase amount, occurrence timestamp, and a stable synthetic fan identifier, and MUST
  set the **`event`** property unambiguously in each record.
- **FR-003**: The project MUST publish a **versioned or named data contract** (field names, types,
  required vs optional, units for amount, timestamp semantics such as timezone) short enough to read in
  one sitting.
- **FR-004**: Output MUST be **JSON Lines (NDJSON)**: UTF-8 text; exactly one JSON object per non-empty
  line; each line MUST be self-contained and parseable without other lines. The contract MUST document
  required properties **per value of `event`** (`ticket_scan` vs `merch_purchase`) and MUST define
  **canonical serialization** (stable key order, no insignificant whitespace, numeric/string formatting
  rules) sufficient for **byte-identical** reproducibility in FR-005.
- **FR-005**: For a fixed seed and fixed parameters documented for the demo, two generation runs MUST
  produce outputs that are **byte-identical** files (primary comparison rule), unless the contract
  documents a weaker equivalence rule and the success criteria are updated accordingly.
- **FR-006**: The default demo configuration MUST produce a file that includes **at least one**
  `ticket_scan` and **at least one** `merch_purchase`, unless the user explicitly selects a single-type
  mode documented in the contract.
- **FR-007**: Non-empty lines in the output file MUST be ordered **globally ascending** by each event’s
  occurrence timestamp (same field the contract uses for time semantics). When timestamps are equal, line
  order MUST be deterministic using tie-breakers documented in the contract, **at minimum** (in order):
  **`event`** (enum order as defined in the contract, not raw Unicode sort on the string), then synthetic
  fan identifier, then any additional properties required to establish a **total order** for duplicate
  timestamps.
- **FR-008**: If the generator cannot produce a **complete** output that satisfies **every** normative
  rule in this spec and the contract (including FR-001–FR-009, schema, sorting, and canonical JSON), the
  run MUST **terminate with non-success** and MUST NOT publish a **durable** NDJSON file that consumers
  could treat as successful output. The contract MAY specify **atomic write** behavior (e.g. write to a
  temporary location and replace the final path only after the full batch is validated).
- **FR-009**: On **success**, the full NDJSON payload MUST be written to a **single filesystem file** at
  a path chosen per the published contract: either an **operator-supplied path** and/or a **documented
  default path** for the standard demo. **Stdout is not** the required or normative success delivery
  channel for this feature (a future amendment may add optional stdout). The contract MUST state how the
  path is determined so scripts and CI can rely on it.

### Key Entities

- **Fan (synthetic)**: Logical person generating activity; referenced by a stable identifier in every
  event; no claim of real-world identity.
- **Ticket scan event**: Admits the fan to a venue; ties fan, stadium location, and time.
- **Merch purchase event**: Economic interaction; ties fan, item, positive amount, and time.
- **Event batch (file)**: UTF-8 JSON Lines (NDJSON) file: events **one per line**, **globally sorted** by
  occurrence time (FR-007), for append-only landing in a later pipeline.

### Analytics & warehouse

Per project constitution (this feature is **upstream** of marts; naming supports later planning):

- **FR-WH-001**: Synthetic output is intended for append-only raw landing. Downstream dbt is expected to
  model facts such as **`fct_ticket_scans`** and **`fct_merch_purchases`** (exact names may be refined
  in `/speckit.plan`); this spec does not require those marts to exist yet.
- **FR-WH-002**: The synthetic source MUST NOT mutate or “correct” events after emission in a way that
  breaks append-only semantics; replays use a new generation run or a new file, not in-place edits.
- **FR-WH-003**: When dbt models consume these events, tests (`not_null`, `unique` where appropriate, and
  business rules such as amount > 0) apply in the warehouse layer; this spec requires the **contract**
  to make those rules enforceable (e.g. amounts strictly positive in valid `merch_purchase` records).

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Independent validation: using only the published contract, a reviewer achieves **100%**
  agreement with a reference validator on which lines in a sample file are valid (inter-rater or
  tool-vs-checklist).
- **SC-002**: Reproducibility: **two consecutive runs** with the same seed and parameters yield
  **byte-identical** outputs in **100%** of trials (per FR-005 primary rule).
- **SC-003**: Contract brevity: the normative contract fits in **two pages or fewer** of prose plus field
  tables (excluding optional extended examples).
- **SC-004**: Downstream handoff: a consumer can parse **100%** of non-empty lines in a default demo file
  as exactly one **valid JSON object** per line without manual repair.

## Assumptions

- The JSON **event-type discriminator** is the property name **`event`** (values `ticket_scan` or
  `merch_purchase`); the synonym **event_type** is not used in the wire format.
- Interchange encoding is **UTF-8 JSON Lines (NDJSON)** per FR-004; no CSV, Avro, or Parquet in this
  feature unless a future amendment changes the contract.
- Timestamps are documented with a single convention (e.g. UTC with an ISO 8601-style string) so demos
  do not depend on local timezone.
- Amounts use one currency for the demo (e.g. EUR) and the contract states the unit; multi-currency is
  out of scope unless added later.
- Stadium location is represented as a human-readable string or a short venue code from a bounded demo
  list—exact encoding is left to planning as long as the contract is fixed.
- Volume is demo-scale (thousands of lines, not billions); performance targets are not in scope for this
  feature.
- Personal data is entirely synthetic; no real fan data is processed.
- The demo assumes the process can write to the chosen output path (FR-009); path defaults or flags are
  fixed in planning and documented in the contract or quickstart.
