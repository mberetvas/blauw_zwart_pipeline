# Implementation Plan: Local full-stack fan event pipeline (Compose)

**Branch**: `005-compose-kafka-pipeline` | **Date**: 2026-04-11 | **Spec**: [spec.md](./spec.md)  
**Input**: Feature specification `specs/005-compose-kafka-pipeline/spec.md` and implementation notes from `spec_kit_chat.md` (lines 33–48).

**Alignment note**: `spec_kit_chat.md` suggests a **Compose-based generator service** with in-network Kafka DNS. The **normative spec** (**FR-001**, **FR-015**) requires the **default** path to run **`fan_events stream` on the host via UV** with a **host-reachable** Kafka bootstrap. Implementation MUST follow the spec: **no required generator container** in v1; optional “all-in-Compose” producer may be documented as **secondary** only (quickstart appendix), not the getting-started path.

## Summary

Deliver a **Docker Compose** stack: **KRaft Kafka** (fixed **dual listeners** so **ingestion/pgAdmin** use **service DNS** and **host producers** use **localhost**), **PostgreSQL** (named volume, healthcheck, **published host port** per **FR-014**), **pgAdmin** (pre-registered server), and a **new Python ingestion service** (async/concurrent consumption, **asyncpg** or **psycopg** async, **idempotent inserts** per **FR-011**, **skip+log+commit** on parse errors per **FR-012**). **SQL init** creates `fan_events_ingested` per **`contracts/ingestion-persistence-v1.md`**. **`.env.example`** documents all required env vars (no secrets in git). **Host producer**: `uv sync --extra kafka` then `uv run fan_events stream --kafka-topic … --kafka-bootstrap-servers localhost:9092` (or env `FAN_EVENTS_KAFKA_*`), matching **FR-005** / **FR-015**.

## Technical Context

**Language/Version**: Python **3.12+** (`pyproject.toml` `requires-python`).  
**Primary Dependencies**: Existing **`confluent-kafka`** (optional extra `kafka`) for producer; ingestion adds **`confluent-kafka`** (consumer) + **`asyncpg`** (or **psycopg[binary,pool]** with async API) — chosen stack documented in `research.md`. **tzdata** remains for generator; ingestion uses UTC timestamps in DB.  
**Storage**: **PostgreSQL** (official image), named volume **`postgres-data`** (or equivalent), init SQL under **`docker/postgres/init/`**.  
**Testing**: **pytest** (`uv run pytest`); unit tests for JSON→row mapping, conflict handling, parse-failure paths; optional containerized integration marked `slow` if needed.  
**Target Platform**: Local **Docker Compose** on Windows/macOS/Linux; host tools connect to **localhost** ports.  
**Project Type**: Existing **CLI/library** repo (`src/fan_events/`) + **new ingest package** + **Compose** + **Dockerfile(s)**.  
**Performance Goals**: Demo/local only; meet **SC-004** via **documented overlapping work** (e.g. consumer thread + multiple asyncio insert tasks, or multi-partition consumption), not production throughput SLOs.  
**Constraints**: **Stdlib-only** for generator core (unchanged); **non-stdlib** allowed for Kafka/DB clients per **spec FR-PY-003** / constitution **VI**. **UV-only** dependency edits. **Minimal diff** to existing `docker-compose.yml` comment style; retain volume **`kafka-data`**.  
**Scale/Scope**: Single broker, single Postgres instance, plaintext, local secrets via `.env`.

## Constitution Check

*GATE: Passed before Phase 0; re-checked after Phase 1.*

| Principle | Status / notes |
|-----------|----------------|
| **Analytics source of truth (I)** | **N/A for this feature**: no new fan-360 or app reads from marts; local **`fan_events_ingested`** is a **demo raw landing** table, not a replacement for `fct_*`/`dim_*`. No embedding of business analytics in ingest code beyond JSON→columns. |
| **Immutable raw (II)** | Rows are **append-only inserts**; no in-place mutation of landed payloads. |
| **dbt data quality (III)** | **No new dbt models** in this feature; see **Complexity Tracking**. |
| **Demonstrable path (IV)** | **event → Kafka → ingest → Postgres** is the vertical slice; warehouse path remains separate. |
| **Demo-first (V)** | Ship working Compose + ingest + docs/quickstart over polish. |
| **Spec & contracts (VII)** | Implementation tied to **spec.md**, **`ingestion-persistence-v1.md`**, **`local-stack-wiring.md`** (new). |
| **Reproducibility (VIII)** | Stream NDJSON determinism unchanged (spec 004); DB row order non-deterministic per **FR-SC-002** — acceptable. |
| **Contract-backed tests (IX)** | Pytest for persistence shape, idempotency, parse skip, sample NDJSON lines. |
| **Versioned contracts (X)** | **ingestion-persistence-v1** fixed for v1; v2 if schema breaks. |
| **Temporal (XI)** | `event_time` / payload timestamps stored as UTC; document parsing from v2/v3 event fields. |
| **Simplicity (XII)** | Named env vars and constants in docs; avoid magic strings in Compose without comments. |
| **Python / UV / VI** | New deps via **`uv add`** into optional **`ingest`** extra (or dedicated group); justify in spec (already **FR-PY-003**). |
| **OOP vs functions (XIII)** | **Classes** for consumer/runtime lifecycle; **functions** for parse/map row (per **FR-PY-004**). |

## Project Structure

### Documentation (this feature)

```text
specs/005-compose-kafka-pipeline/
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/
│   ├── ingestion-persistence-v1.md
│   └── local-stack-wiring.md
└── tasks.md              # /speckit.tasks (not created here)
```

### Source Code (repository root)

```text
src/
├── fan_events/           # existing CLI, stream, kafka_sink
└── fan_ingest/           # NEW: asyncio ingest service (package + __main__ or cli entry)

docker/
├── postgres/
│   └── init/
│       └── 001_fan_events_ingested.sql
└── Dockerfile.ingest     # NEW (path may vary; single focused Dockerfile)

tests/
├── fan_ingest/           # NEW: unit tests for mapping, idempotency helpers
└── ...

docker-compose.yml        # EXTENDED: postgres, pgadmin, ingest, broker listeners
.env.example              # NEW at repo root
```

**Structure Decision**: Add **`src/fan_ingest/`** as a small installable package (same setuptools `where = ["src"]`) with a **`fan_ingest`** console script or `python -m fan_ingest`; Docker image runs that module. Keeps ingestion separate from **`fan_events`** generator concerns.

## Complexity Tracking

| Item | Why Needed | Simpler Alternative Rejected Because |
|------|------------|-------------------------------------|
| **No new dbt marts in this PR** | Constitution **III** normally requires tests for new models; this feature **does not add** warehouse models — only a **local** Postgres table for pipeline demo. | Adding dbt for a disposable local table is out of spec scope. |
| **confluent-kafka + async DB driver** | Spec **FR-PY-003** / wire protocols. | Raw sockets or stdlib-only Kafka/Postgres protocols are impractical and brittle. |

## Phase 0 & 1 outputs

| Phase | Artifact | Purpose |
|-------|----------|---------|
| 0 | [research.md](./research.md) | Kafka dual listeners, controller quorum, consumer/async strategy |
| 1 | [data-model.md](./data-model.md) | `fan_events_ingested` fields, constraints, indexes |
| 1 | [contracts/local-stack-wiring.md](./contracts/local-stack-wiring.md) | Compose service names, ports, listener map |
| 1 | [quickstart.md](./quickstart.md) | Copy env, `compose up`, producer command, verification |
| 1 | Agent context | `.cursor/rules/specify-rules.mdc` updated via script |

**Phase 2** (`tasks.md`) is **out of scope** for this command — use **`/speckit.tasks`**.
