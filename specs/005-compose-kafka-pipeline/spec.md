# Feature Specification: Local full-stack fan event pipeline (Compose)

**Feature Branch**: `005-compose-kafka-pipeline`  
**Created**: 2026-04-11  
**Status**: Draft  
**Input**: User description: "Full local Docker Compose pipeline: single-node Kafka (KRaft) → NDJSON fan event producer → async ingestion to PostgreSQL → pgAdmin; fix broker advertised listeners for in-network clients; named volumes for Postgres and retained `kafka-data`; generator uses existing `fan_events stream` Kafka mode and documented `FAN_EVENTS_KAFKA_*` settings; new in-repo ingestion service with concurrent/async consumption; SQL init for minimal v1 schema; credentials via env and `.env.example`; acceptance includes end-to-end flow and durability after `compose down`."

**Audience**: Technical contributors running and validating the local integration stack (not business-only readers).

### Stakeholder summary (non-technical)

- The team can run a **complete local practice pipeline** so synthetic fan activity **flows into a queryable history** that **survives normal restarts** when storage is not wiped.
- **Setup is documented** with an example settings file so new contributors are not blocked by missing configuration.
- **Failures are visible** (logs or clear signals) instead of silently dropping fan-event data during local runs.

## Clarifications

### Session 2026-04-11

- Q: For v1, how should ingestion treat the same Kafka offset if seen again (replay, reprocessing)? → A: **Option B — Idempotent by coordinates**: unique `(kafka_topic, kafka_partition, kafka_offset)`; re-deliveries do not insert a second row (document exact insert/`ON CONFLICT` behavior in init SQL and operator docs).
- Q: When a message body is not valid NDJSON/JSON for one persisted object, what should ingestion do? → A: **Option A — Skip and log**: log at least topic, partition, offset, and error class/message; **no** row inserted; **commit** the offset after skip (documented) so the consumer advances past poison messages; optional metrics/counter documented for operators.
- Q: How should the fan-events Kafka topic exist before producer and consumer run? → A: **Option A — Auto-create**: rely on broker **automatic topic creation** on first produce (or equivalent broker default); Compose/docs MUST state any required broker configuration so auto-create is **enabled and predictable** for v1 (partition/replication defaults documented).
- Q: For v1, should PostgreSQL be reachable from the host (published `localhost` port)? → A: **Option A — Yes**: publish a **host-mapped** database port with the **numeric mapping** documented in `.env.example` / Compose variables; documentation MUST warn about **port clashes** with an existing local database and how to change the mapping.
- Q: What is the default documented placement for the `fan_events stream` producer? → A: **Option A — Host primary**: default instructions run the producer **on the host** via **UV** (`uv run` …); `FAN_EVENTS_KAFKA_BOOTSTRAP_SERVERS` uses the **host-reachable** broker address required by **FR-002** (dual listener / advertised metadata); Compose runs broker, database, ingestion, and pgAdmin.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Run the full local pipeline (Priority: P1)

A contributor checks out the repository, supplies credentials and connection settings via documented environment files (no secrets committed), starts the local stack, runs the synthetic fan-event producer **on the host** (default: **UV**) into the message bus using a **host-reachable** Kafka bootstrap address, and confirms that records corresponding to consumed events appear in the relational store.

**Why this priority**: Without this, the feature delivers no integration value.

**Independent Test**: Follow only the documented setup steps and one producer run; verify new rows appear in the store within a bounded time.

**Acceptance Scenarios**:

1. **Given** a clean machine with only the documented prerequisites, **When** the contributor copies the example environment file, fills required values, and starts the stack as documented, **Then** all long-running services reach a healthy/runnable state without manual image patching.
2. **Given** the stack is up and the message bus is ready (topic **may** be absent until first produce per **FR-013**), **When** the contributor runs the existing synthetic stream in message-bus mode **on the host** with `FAN_EVENTS_KAFKA_BOOTSTRAP_SERVERS` set to the **host-reachable** broker endpoint (per **FR-002** / **FR-015**), **Then** messages appear on the configured topic and the ingestion path processes them without requiring a single-threaded blocking consumer as the only implementation pattern.
3. **Given** messages are flowing, **When** the contributor inspects the relational store (including via the bundled browser UI **or** a host client using the published DB port per **FR-014**), **Then** they can retrieve rows that correspond to ingested fan-event payloads for the minimal v1 persistence model.

---

### User Story 2 - Durable fan-event data across restarts (Priority: P2)

A contributor stops the stack in the normal documented way (without deleting persistent volumes), brings it back up, and still sees previously ingested fan-event data.

**Why this priority**: Validates that local experimentation and demos do not lose history on every shutdown.

**Independent Test**: Ingest a known volume of events, stop the stack preserving the data volume, restart, query counts or sample rows.

**Acceptance Scenarios**:

1. **Given** events were ingested and stored, **When** the contributor stops the stack using the documented command that retains named volumes, **Then** after restart the same persisted allocation still contains those rows (no silent reset of stored history).

---

### User Story 3 - Observable operations and failure behavior (Priority: P3)

A contributor can tell when ingestion is unhealthy (e.g. store unavailable, poison messages) from documented behavior—logs, non-zero exit, or explicit handling—without silent data loss for acknowledged processing paths.

**Why this priority**: Local pipelines that hide errors waste debugging time.

**Independent Test**: Simulate store outage or invalid payload; observe documented error handling path.

**Acceptance Scenarios**:

1. **Given** the relational store is unavailable, **When** ingestion runs, **Then** the service does not claim successful persistence for failed writes; errors are surfaced in a way suitable for local debugging (e.g. logs and/or process exit policy documented alongside the service).
2. **Given** a malformed line on the topic, **When** ingestion encounters it, **Then** it **skips** persistence, emits a **structured log** (including topic, partition, offset, and error detail), **commits** the offset per documented policy so processing continues, and **does not** exit solely for that poison message unless documentation explicitly defines an optional strict mode (v1 default is skip-and-continue).

### Edge Cases

- Broker metadata advertises addresses reachable from **other containers** (in-compose consumers/producers) and from the **host** when the documented host workflow is used; contributors understand tradeoffs when mixing host-only bootstrap with in-network bootstrap.
- Empty topic, consumer group offset reset, and replay: v1 is **idempotent by broker coordinates** — a **unique** constraint on `(kafka_topic, kafka_partition, kafka_offset)` and insert behavior that **does not add a second row** on duplicate delivery (e.g. `ON CONFLICT DO NOTHING` or equivalent documented semantics). Offset commits MUST follow a policy consistent with this (typically commit after successful insert so uncommitted messages can retry without duplicate rows).
- Very high producer rate vs. ingestion throughput: backlog grows but the stack remains stable; document expectations for local hardware.
- TLS/SASL not required for v1 local stack; if omitted, document plaintext-local-dev-only caveat.
- **Malformed / unparsable payloads**: v1 default is **skip and log** with **offset commit after skip** (see **FR-012**); no dead-letter topic or table is required for v1.
- **Topic lifecycle**: v1 assumes the fan-events topic is **auto-created** when the producer first publishes (**FR-013**); contributors starting **only** the consumer before any produce should see documented behavior (e.g. idle consumer until topic exists and messages arrive).
- **Host port clash**: Published **Postgres** and **Kafka** host ports may conflict with software already installed on the machine; docs MUST call this out and point to env/Compose variables to change mappings (**FR-014** for Postgres; broker port already conventional).

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The repository MUST provide a **declarative local stack definition** (Compose) that includes: a single-node KRaft message broker, a relational database with a **health check**, a **browser-accessible** administration UI for the database, and a **separate ingestion service** that reads from the topic and writes to the relational store. The synthetic **fan-event stream producer** MUST remain runnable in message-bus mode **on the host** via **UV** as the **default** workflow (**FR-015**); an optional Compose-wrapped producer is **not** required for v1.
- **FR-002**: **Broker listener metadata** MUST be configured so that **in-network clients** (other services on the default Compose network) receive advertised addresses that resolve via **Compose service DNS** (not only `localhost`), **and** so that **host-side** producers (default per **FR-015**) can connect using a **host-reachable** bootstrap address (e.g. published `localhost` port). Operator documentation MUST explain the tradeoff between host bootstrap vs in-network bootstrap and state that the **primary** documented path uses a **host** producer plus **in-network** ingestion (**FR-015**).
- **FR-003**: **Persistent storage**: The relational database MUST use a **named volume** so data survives a normal shutdown that does not remove volumes. The existing broker volume name **`kafka-data`** MUST be retained for broker data continuity.
- **FR-004**: **Secrets and configuration**: Database and UI credentials MUST be supplied via environment variables or Compose variable substitution from a local file that is **not** committed; the repository MUST include an **example env file** listing required variables (placeholder values only).
- **FR-005**: **Producer integration**: The fan-event producer MUST use the existing **`fan_events stream`** message-bus path, optional packaging extras for the message-bus client library as already defined in project packaging, and the existing **`FAN_EVENTS_KAFKA_*`** configuration surface (bootstrap servers, topic, and related options) documented alongside the producer module. Default docs MUST show **host** execution with **UV** and a **host-reachable** `FAN_EVENTS_KAFKA_BOOTSTRAP_SERVERS` value consistent with **FR-002**.
- **FR-006**: **Ingestion service**: A **new**, in-repository ingestion component MUST consume the configured topic using **concurrent or asynchronous processing** (e.g. async runtime with cooperative tasks, worker pool, and/or multiple consumer workers). A design that is **only** a single long-running blocking loop with no concurrency structure is NOT acceptable.
- **FR-007**: **Persistence behavior**: Ingestion MUST insert into the relational store with **explicit error handling** for write failures (row-wise or batched), with behavior documented for partial batch failure if batching is used.
- **FR-008**: **Schema initialization**: A version-controlled SQL **init or migration** path (e.g. under a `docker/postgres/init/` or equivalent convention) MUST create a **minimal v1** relational schema derived from the NDJSON fan-event fields that ingestion persists; field-to-column mapping and known limitations MUST be documented in this feature’s contract supplement.
- **FR-009**: **Database UI**: The administration UI MUST ship with the relational server **pre-registered** for local use (via supported configuration such as environment-driven registration or mounted servers configuration), using the Compose service hostname for connectivity from that UI container.
- **FR-010**: **Documentation**: A contributor MUST be able to complete setup using **only** documented steps (example env, copy/edit, `compose up`, producer command, where to click/query in the UI) without reading source code.
- **FR-011**: **Idempotent persistence (v1)**: The relational schema MUST enforce **uniqueness** of `(kafka_topic, kafka_partition, kafka_offset)`. Ingestion MUST use a **single-row idempotent insert** strategy so that at-least-once redelivery of the same offset **does not** create a duplicate row (exact SQL mechanism documented in init/migration and operator docs). Batched inserts, if used, MUST preserve the same semantics per row (e.g. batch-level conflict handling documented for partial conflicts).
- **FR-012**: **Unparsable messages (v1)**: When a message value cannot be parsed as a single JSON object suitable for persistence (invalid NDJSON/JSON, wrong shape), ingestion MUST **not** insert a row, MUST emit a **log** including at least **topic**, **partition**, **offset**, and error detail, and MUST **commit** the consumer offset for that record after the skip so the pipeline does not stall (document exact ordering: parse failure → log → commit). A **dead-letter topic or table** is **out of scope** for v1 unless a later spec revision adds it.
- **FR-013**: **Topic creation (v1)**: The configured fan-events topic MUST be created **without** a separate init job or manual CLI step in the default workflow: the broker MUST allow **automatic topic creation** on first produce, and documentation MUST state the effective **default partition count and replication** for that auto-created topic (as set by broker/Compose env) so consumer and producer expectations align. If a specific broker property must be set to enable auto-create, it MUST appear in the example Compose/env docs.
- **FR-014**: **PostgreSQL host access (v1)**: The relational database service MUST publish a **host-accessible** TCP port (mapped port configurable via env/Compose, with default documented in `.env.example`) so contributors can connect from **host tools** (e.g. CLI clients, IDEs) in addition to pgAdmin and in-network services. Documentation MUST note **port collision** risk with other local databases and how to pick an alternate host port.
- **FR-015**: **Default producer placement (v1)**: The **primary** documented workflow MUST run **`fan_events stream`** **on the developer machine** using **UV** (`uv run` …), not as a required Compose service. **`FAN_EVENTS_KAFKA_BOOTSTRAP_SERVERS`** in that workflow MUST target the **host-reachable** broker listener from **FR-002**. Secondary documentation MAY describe an all-in-Compose producer for advanced users but MUST NOT replace the UV-on-host default in getting-started steps.

### Key Entities *(include if feature involves data)*

- **Fan event message (on bus)**: One UTF-8 text payload per message, representing one NDJSON line / JSON object as emitted by the unified synthetic stream; governed by existing interchange contracts by `event` type (see linked specs). Key persistence-relevant fields for v1 are documented in `contracts/ingestion-persistence-v1.md`.
- **Persisted fan event row (v1)**: Minimal relational projection of a consumed message for local inspection and downstream experimentation; may omit optional JSON fields until future versions if documented.
- **Consumer position**: Logical offset / group membership for the ingestion consumer; on restart, processing continues from committed offsets. Replayed messages (same offset) are absorbed idempotently per **FR-011** without duplicate rows.

### Python scripts and packaged code *(mandatory when feature touches generators, CLIs, or modules under `src/`, `scripts/`, or equivalent)*

Per project constitution:

- **FR-PY-001**: New or changed Python behavior MUST be covered by pytest tests; contributors MUST prefer TDD (failing test first, smallest passing change, then refactor).
- **FR-PY-002**: Dependencies and runs MUST go through **UV** (`uv add`, `uv add --dev`, `uv remove`; `uv run pytest`; `uv run python <script>`). Lockfile (`uv.lock`) MUST stay aligned with `pyproject.toml` via UV only.
- **FR-PY-003**: Non-standard-library runtime dependencies for the **producer message-bus client** and **ingestion service** (message-bus client, relational driver, async stack as chosen) are **explicitly in scope** for this feature. Justification (constitution VI): a standard-library-only path would require reimplementing wire protocols and client semantics, which is **significantly more complex, error-prone, and opaque** than using maintained clients. Generator **core** stream logic remains governed by existing specs; only the existing optional message-bus integration path is exercised here.
- **FR-PY-004**: Ingestion SHOULD use **classes** for consumer/session lifecycle and **functions** for pure transforms (parse → row mapping) to keep tests and boundaries clear, unless a slimmer structure is justified in the plan.

### Spec, contracts, and synthetic interchange *(mandatory when feature defines NDJSON, events, or machine-readable handoff files)*

Per project constitution:

- **FR-SC-001**: Normative persistence mapping for v1 MUST live in this `spec.md` and `specs/005-compose-kafka-pipeline/contracts/ingestion-persistence-v1.md`; implementation MUST match the cited contract version.
- **FR-SC-002**: Determinism of **merged NDJSON stream output** remains as defined in **spec 004** and its contracts when producer inputs (including seed) are fixed; this feature does **not** require byte-identical **row insertion order** in the relational store if async ingestion makes ordering non-deterministic, unless explicitly added in a future version.
- **FR-SC-003**: Tests MUST validate ingestion against the persistence contract (required columns, types, and nullability for v1) and representative sample lines from existing interchange contracts.
- **FR-SC-004**: Any change that breaks v1 persistence mapping MUST bump the contract version and document migration.
- **FR-SC-005**: Event timestamps in stored rows MUST preserve **UTC with `Z`** semantics as in source NDJSON where a timestamp field is persisted.
- **FR-SC-006**: Constants such as topic name defaults (if any in docs) MUST be named in documentation, not only as unexplained literals.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A contributor with repository access completes **documented** first-time setup (example env + start command + one producer invocation) in **30 minutes or less** assuming a typical broadband connection and preinstalled prerequisites, and observes at least **one** persisted row per **10** producer-emitted messages in a default demo configuration (or 100% if fewer than 10 are emitted).
- **SC-002**: After ingesting at least **50** events, stopping the stack with the documented **volume-preserving** shutdown, and starting again, **100%** of those **50** rows remain queryable (same count by primary key or surrogate key query documented in acceptance notes).
- **SC-003**: In a controlled run of **100** messages, ingestion processes them to successful persistence with **zero unlogged silent write failures** (any write failure MUST appear in service logs or documented health signal).
- **SC-004**: While producing at least **30** messages within **60** seconds, ingestion exhibits **overlapping work** (e.g. log lines or documented metrics showing more than one in-flight handling window), demonstrating that consumption is not strictly serialized one-message-at-a-time end-to-end; reproduction steps MUST be documented for maintainers.

## Assumptions

- **Local-only security**: Plaintext broker and database ports on localhost are acceptable for v1; production hardening is out of scope.
- **Single broker, single database instance**: No multi-AZ or clustered deployment requirements.
- **At-least-once delivery** from the bus is acceptable; v1 **does not** allow duplicate rows for the same `(topic, partition, offset)` — idempotency is **required** per **FR-011**.
- **Official maintained images** are used for broker, database, and database UI as named in the feature request, pinned or tagged per project policy in the implementation plan.
- **Python runtime** for producer and ingestion aligns with `requires-python` in `pyproject.toml` (3.12+).
- **Default operator workflow**: Producer on **host** via **UV**; long-running services in **Compose** (**FR-015**).

## Related contracts

- NDJSON event shapes and merge ordering: `specs/004-unified-synthetic-stream/contracts/orchestrated-stream.md` and type-specific contracts in specs 001–003.
- Persistence projection (v1): `specs/005-compose-kafka-pipeline/contracts/ingestion-persistence-v1.md`.
