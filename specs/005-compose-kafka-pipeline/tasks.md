---
description: "Task list for 005-compose-kafka-pipeline (local Compose + Kafka + Postgres + ingest)"
---

# Tasks: Local full-stack fan event pipeline (Compose)

**Input**: Design documents from `D:\Projecten_Thuis\blauw_zwart_fan_sim_pipeline\specs\005-compose-kafka-pipeline\`  
**Prerequisites**: [plan.md](./plan.md), [spec.md](./spec.md), [research.md](./research.md), [data-model.md](./data-model.md), [contracts/](./contracts/), [quickstart.md](./quickstart.md)

**Tests**: **pytest** required for new Python (`FR-PY-001`); run `uv run pytest` from repository root. **No new dbt models** in this feature (see [plan.md](./plan.md) Complexity Tracking). Manage dependencies with **UV** only (`pyproject.toml` + `uv.lock`). Ingestion runtime deps justified in **spec FR-PY-003**.

**Context note** (`spec_kit_chat.md` 64–73): A **Compose-based generator** is **not** part of v1 — **FR-001** / **FR-015** require the **default producer on the host via UV** with **localhost** Kafka bootstrap; optional all-in-Compose producer is **out of scope** unless added later as a non-default appendix.

**Organization**: Phases follow **Setup → Foundational (infra) → User stories (P1–P3) → Polish**. Paths use repo root `D:\Projecten_Thuis\blauw_zwart_fan_sim_pipeline` (use forward slashes in clones).

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no ordering dependency)
- **[Story]**: `[US1]` … maps to `spec.md` user stories

---

## Phase 1: Setup (project / package scaffold)

**Purpose**: UV dependencies and ingest package skeleton before Compose wiring.

- [X] T001 Add optional dependency extra or group for ingestion (`confluent-kafka`, `asyncpg`) via `uv add` in `pyproject.toml` and refresh `uv.lock` at repository root
- [X] T002 [P] Create package scaffold `src/fan_ingest/__init__.py` and empty modules to be filled (`src/fan_ingest/records.py`, `src/fan_ingest/db.py`, `src/fan_ingest/runner.py`, `src/fan_ingest/main.py`) per `specs/005-compose-kafka-pipeline/plan.md`

---

## Phase 2: Foundational (infra — blocks all user stories)

**Purpose**: Broker (dual listeners + quorum), Postgres + init schema, pgAdmin, env template. **No `ingest` service yet** if you prefer strict ordering; otherwise add `ingest` in Phase 3 only after code exists.

**⚠️ CRITICAL**: No user story verification until broker + Postgres + init SQL exist.

- [X] T003 [P] Create `D:\Projecten_Thuis\blauw_zwart_fan_sim_pipeline\.env.example` with placeholders for Postgres, pgAdmin, ingest (`KAFKA_BOOTSTRAP_SERVERS=broker:29092`), host port overrides, and **named** topic / consumer group vars (**FR-SC-006**); add comments that the fan-events topic is **auto-created on first produce** and default partitions follow broker `KAFKA_NUM_PARTITIONS` (**FR-013**)
- [X] T004 [P] Add `D:\Projecten_Thuis\blauw_zwart_fan_sim_pipeline\docker\postgres\init\001_fan_events_ingested.sql` creating `fan_events_ingested` with UNIQUE `(kafka_topic, kafka_partition, kafka_offset)` per `specs/005-compose-kafka-pipeline/data-model.md` and `specs/005-compose-kafka-pipeline/contracts/ingestion-persistence-v1.md`
- [X] T005 Update `D:\Projecten_Thuis\blauw_zwart_fan_sim_pipeline\docker-compose.yml`: KRaft **dual listeners** (INTERNAL advertised `broker:29092`, EXTERNAL `localhost:9092`), `KAFKA_INTER_BROKER_LISTENER_NAME` / security protocol map, `KAFKA_CONTROLLER_QUORUM_VOTERS` using `broker:9093`, retain volume `kafka-data`, add default network, add `postgres` (image, `postgres-data` volume, healthcheck, env from `.env`, **published host port** per **FR-014**), add `pgadmin` (published port, credentials from env, **pre-registered server** to Postgres service hostname:5432); in file header comments (or **FR-013** note), document **automatic topic creation** on first produce and the effective **default partition count** from broker env (e.g. `KAFKA_NUM_PARTITIONS`) so producer/consumer expectations match

**Checkpoint**: `docker compose up -d` yields healthy Postgres and reachable Kafka from host on `localhost:9092` and from containers on `broker:29092`.

---

## Phase 3: User Story 1 — Run the full local pipeline (Priority: P1) 🎯 MVP

**Goal**: Host producer → Kafka → ingest → Postgres rows; contributor can verify via pgAdmin or host SQL client.

**Independent Test**: Follow `specs/005-compose-kafka-pipeline/quickstart.md`: stack up, `uv run fan_events stream --kafka-topic … --kafka-bootstrap-servers localhost:9092`, `SELECT` shows new rows in `fan_events_ingested`.

### Tests for User Story 1

- [X] T006 [P] [US1] Add pytest `D:\Projecten_Thuis\blauw_zwart_fan_sim_pipeline\tests\fan_ingest\test_row_mapping.py` for NDJSON → row fields per **`data-model.md`** / **`contracts/ingestion-persistence-v1.md`** (**FR-SC-003**): `kafka_topic`, `kafka_partition`, `kafka_offset`, `event_type` (sentinel `unknown` when missing), `event_time` (nullable UTC), `payload_json`; use representative JSON lines from existing fan event contracts; omit `id`/`ingested_at` where DB-generated
- [X] T007 [P] [US1] Add pytest `D:\Projecten_Thuis\blauw_zwart_fan_sim_pipeline\tests\fan_ingest\test_idempotency.py` for insert / `ON CONFLICT DO NOTHING` on **exactly** `(kafka_topic, kafka_partition, kafka_offset)` matching `docker/postgres/init/001_fan_events_ingested.sql` (mock or lightweight DB per test strategy) (**FR-011**, **FR-SC-003**)

### Implementation for User Story 1

- [X] T008 [US1] Implement `D:\Projecten_Thuis\blauw_zwart_fan_sim_pipeline\src\fan_ingest\records.py` — parse message bytes to row dict; sentinel `unknown` for missing `event`; **FR-012** parse failure returns no row and signals skip
- [X] T009 [US1] Implement `D:\Projecten_Thuis\blauw_zwart_fan_sim_pipeline\src\fan_ingest\db.py` — asyncpg pool, insert with `ON CONFLICT DO NOTHING` on `(kafka_topic, kafka_partition, kafka_offset)` per **FR-011**
- [X] T010 [US1] Implement `D:\Projecten_Thuis\blauw_zwart_fan_sim_pipeline\src\fan_ingest\runner.py` — encapsulate consumer lifecycle in a **class** (e.g. `IngestRuntime` / `KafkaIngestPipeline`) holding the **dedicated thread** for `confluent_kafka.Consumer`, the **`asyncio` queue**, shutdown state, and coordination with **multiple asyncio worker tasks** that perform overlapping inserts (**SC-004**, **FR-006**, **FR-PY-004**); keep **parse → row dict** as **functions** in `records.py`; commit offsets **after** successful insert or conflict-skip, and **after** parse skip per **FR-012**
- [X] T011 [US1] Implement CLI entry `D:\Projecten_Thuis\blauw_zwart_fan_sim_pipeline\src\fan_ingest\main.py` — env for bootstrap `broker:29092`, topic, group id, `DATABASE_URL` / Postgres settings; graceful shutdown
- [X] T012 [US1] Register console script `fan_ingest` in `D:\Projecten_Thuis\blauw_zwart_fan_sim_pipeline\pyproject.toml` pointing at `fan_ingest.main:main` (or equivalent)
- [X] T013 [US1] Add `D:\Projecten_Thuis\blauw_zwart_fan_sim_pipeline\docker\Dockerfile.ingest` — UV-based image installing project with ingest/kafka extras, `CMD` runs `fan_ingest`
- [X] T014 [US1] Add `ingest` service to `D:\Projecten_Thuis\blauw_zwart_fan_sim_pipeline\docker-compose.yml` — build from `docker/Dockerfile.ingest`, env from `.env`, `depends_on` **postgres** (`condition: service_healthy`) and **broker**, `KAFKA_BOOTSTRAP_SERVERS=broker:29092`
- [X] T015 [US1] **Primary** (**FR-010**): Update `D:\Projecten_Thuis\blauw_zwart_fan_sim_pipeline\specs\005-compose-kafka-pipeline\quickstart.md` with full steps (env copy, `docker compose up`, host `uv sync --extra kafka` + `uv run fan_events stream … --kafka-bootstrap-servers localhost:9092`, pgAdmin URL, **host Postgres** port, **Kafka** host port, **port-clash** note per **FR-014**, verification `SELECT count(*) FROM fan_events_ingested`, and **FR-013** broker auto-create / default partitions); add a **short “Full local pipeline”** subsection to `D:\Projecten_Thuis\blauw_zwart_fan_sim_pipeline\README.md` that **links to** `specs/005-compose-kafka-pipeline/quickstart.md` and lists only **ports + one-line** run hint; add a **brief pointer** in the header comment block of `D:\Projecten_Thuis\blauw_zwart_fan_sim_pipeline\docker-compose.yml` (“see quickstart in specs/005-…/quickstart.md”) so **FR-015** is not duplicated in three full copies

**Checkpoint**: End-to-end demo works without a Compose generator container.

---

## Phase 4: User Story 2 — Durable fan-event data across restarts (Priority: P2)

**Goal**: Postgres data survives `docker compose down` without `-v`.

**Independent Test**: Ingest rows, `docker compose down`, `docker compose up -d`, row count unchanged.

- [X] T016 [US2] Verify and document named volume for Postgres in `D:\Projecten_Thuis\blauw_zwart_fan_sim_pipeline\docker-compose.yml` (no accidental `tmpfs`); extend `D:\Projecten_Thuis\blauw_zwart_fan_sim_pipeline\specs\005-compose-kafka-pipeline\quickstart.md` with explicit **down vs down -v** warning and a **SC-002** checklist step: after ingesting **≥50** events, `docker compose down` (no `-v`), `docker compose up -d`, re-query — row count for those offsets must remain **100%**

---

## Phase 5: User Story 3 — Observable operations and failure behavior (Priority: P3)

**Goal**: Parse and DB failures visible in logs; no silent drops for acknowledged writes.

**Independent Test**: Publish invalid JSON to topic; logs show topic/partition/offset; consumer advances; DB write failure produces error log or documented exit.

### Tests for User Story 3

- [X] T017 [P] [US3] Add pytest `D:\Projecten_Thuis\blauw_zwart_fan_sim_pipeline\tests\fan_ingest\test_parse_errors.py` asserting skip path does not build row and does not call insert (mock consumer callback)

### Implementation for User Story 3

- [X] T018 [US3] Harden logging and failure policy in `D:\Projecten_Thuis\blauw_zwart_fan_sim_pipeline\src\fan_ingest\runner.py` and `D:\Projecten_Thuis\blauw_zwart_fan_sim_pipeline\src\fan_ingest\db.py` — structured fields for topic/partition/offset on parse and write errors; document retry/exit behavior in `D:\Projecten_Thuis\blauw_zwart_fan_sim_pipeline\specs\005-compose-kafka-pipeline\quickstart.md`

---

## Phase 6: Polish & cross-cutting

**Purpose**: Quality gates and manual acceptance.

- [X] T019 [P] Run `uv run pytest` and `ruff check` from `D:\Projecten_Thuis\blauw_zwart_fan_sim_pipeline` and fix failures
- [X] T020 Run manual acceptance (mirror bullets in `D:\Projecten_Thuis\blauw_zwart_fan_sim_pipeline\specs\005-compose-kafka-pipeline\quickstart.md` **Acceptance** section): **(1)** compose up, host producer, rows appear; **(2)** **SC-002** volume-preserving restart (see **T016**); **(3)** **SC-003**: produce **100** valid messages, confirm **zero** silent write failures (scan `docker compose logs ingest` for errors); **(4)** **SC-004**: produce **≥30** messages within **60** seconds, capture logs showing **overlapping** handling (e.g. concurrent insert timestamps or overlapping worker traces per quickstart); **(5)** optional **SC-001**: first-time setup within **30** minutes on a clean machine with prerequisites installed

---

## Dependencies & execution order

### Phase dependencies

- **Phase 1** → **Phase 2** → **Phases 3–5** → **Phase 6**
- **Phase 2** blocks all user stories (no running ingest without broker + DB + schema).

### User story dependencies

- **US1 (P1)**: After Phase 2; no dependency on US2/US3.
- **US2 (P2)**: After US1 pipeline works (needs rows to verify durability); can overlap documentation with US3.
- **US3 (P3)**: After US1 core ingest exists (tests target existing `runner`/`records`).

### Parallel opportunities

- **T001** vs **T002** (different concerns: lockfile vs empty files) — after T001, prefer completing T002 before heavy imports in T008+.
- **Phase 2 only**: **T003** ∥ **T004** (distinct files; both before **T005**).
- **Phase 3 after Phase 2**: **T006** ∥ **T007** (distinct test files).
- **T017** can start once **T008–T010** interfaces exist.
- **T019** runs after code stable (not parallel with unfinished implementation).

---

## Parallel example: User Story 1

```text
# Together after Phase 2:
T006 tests/fan_ingest/test_row_mapping.py
T007 tests/fan_ingest/test_idempotency.py
```

---

## Implementation strategy

### MVP (User Story 1 only)

1. Complete Phase 1–2 (deps, scaffold, `.env.example`, SQL init, Compose broker/postgres/pgadmin).
2. Complete Phase 3 through **T015** — stop and run quickstart end-to-end.
3. Run **T019**–**T020** minimally for MVP quality.

### Incremental delivery

1. Add **US2** (**T016**) — durability docs + verification.
2. Add **US3** (**T017**–**T018**) — parse/error observability.
3. Final **T019**–**T020**.

### Optional (not v1 / not FR-015)

- **Compose `generator` service** (`spec_kit_chat.md`): only if product owner explicitly extends scope; would use `FAN_EVENTS_KAFKA_BOOTSTRAP_SERVERS=broker:29092` and Dockerfile — **do not** implement unless spec is amended.

---

## Notes

- **Internal Kafka bootstrap** for ingest: `broker:29092` — never `localhost:9092` inside containers.
- **Host producer**: `localhost:9092` — requires **EXTERNAL** advertised listener on broker (**research.md**).
- Commit after each task or logical group; stop at checkpoints to validate stories independently.
