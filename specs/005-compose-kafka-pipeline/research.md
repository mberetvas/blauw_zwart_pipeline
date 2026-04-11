# Research: 005-compose-kafka-pipeline

Consolidated decisions for local Compose + Kafka (KRaft) + Postgres + ingestion.

## R1 — Kafka listeners: host + Docker DNS

**Decision**: Use **two PLAINTEXT listeners** on the broker:

- **INTERNAL** (e.g. port **29092**): bind `0.0.0.0:29092`, advertised **`broker:29092`** (Compose service hostname) for **ingestion** and other containers.
- **EXTERNAL** (e.g. port **9092**): bind `0.0.0.0:9092`, advertised **`localhost:9092`** (or `${HOST_DOCKER_INTERNAL}` only if needed on Windows — default **localhost** matches current repo comment) for **host** `fan_events` producer.

Set **`KAFKA_INTER_BROKER_LISTENER_NAME=INTERNAL`** (or the image’s equivalent) so the broker uses INTERNAL for inter-broker/controller traffic on the single node.

**Rationale**: Fixes broken metadata when `KAFKA_ADVERTISED_LISTENERS` is only `localhost:9092` — containers then receive unreachable addresses. Matches **FR-002** / **FR-015**.

**Alternatives considered**:

- **Single listener + only internal DNS**: breaks **FR-015** host producer without extra port forwarding tricks.
- **Host network mode**: non-portable, worse on Docker Desktop; rejected.

## R2 — KRaft controller quorum address

**Decision**: Set **`KAFKA_CONTROLLER_QUORUM_VOTERS`** (or image-specific equivalent) to use the **Compose service resolvable hostname** for the controller endpoint (e.g. `1@broker:9093`), **not** `localhost:9093`, so the broker container can reach the controller listener reliably.

**Rationale**: `localhost:9093` inside the container points at the container itself; KRaft expects a stable voter endpoint. Aligns with apache/kafka Docker examples for multi-listener setups.

**Alternatives**: Single-node embedded quirks — still use explicit `broker:9093` for clarity.

## R3 — Auto topic creation & partitions

**Decision**: Rely on broker **auto-create topic** on first produce (**FR-013**). Document **`KAFKA_NUM_PARTITIONS`** (already `3` in compose) as the default partition count for new topics.

**Rationale**: Matches clarified spec; minimal ops.

**Alternatives**: Init container with `kafka-topics.sh` — extra moving parts; optional later.

## R4 — Ingestion concurrency model

**Decision**: **`confluent_kafka.Consumer`** in a **dedicated thread** (sync poll loop) feeding an **`asyncio.Queue`**; **multiple asyncio tasks** drain the queue and perform **`asyncpg`** inserts with **`ON CONFLICT DO NOTHING`** on `(kafka_topic, kafka_partition, kafka_offset)`. **Commit offsets** on the consumer thread **after** successful insert (or after skip+log for parse failures) per **FR-011** / **FR-012**.

**Rationale**: **`confluent-kafka`** has no official asyncio API; thread + queue achieves **overlapping work** (**SC-004**) without adding **aiokafka** as a second client stack. **asyncpg** is small and fits async inserts.

**Alternatives considered**:

- **aiokafka + asyncpg**: fewer threads, but second Kafka client library and different semantics.
- **Blocking consumer + thread pool only**: harder to show clear asyncio structure; queue+tasks is a simple demo of concurrency.

## R5 — event_time extraction

**Decision**: In v1, implement a **small mapping** from parsed JSON: read top-level **`event`**, then pick timestamp field per known contracts (e.g. synthetic time fields used in v2/v3 NDJSON) with a **safe fallback** to `NULL` if missing; document the exact fields in **`data-model.md`** and code comments.

**Rationale**: **ingestion-persistence-v1** allows nullable `event_time`; full contract parity can grow in v2.

## R6 — pgAdmin server registration

**Decision**: Prefer **environment-driven** registration via **`PGADMIN_CONFIG_*`** / official patterns for `dpage/pgadmin4`, or a **mounted `servers.json`** populated with **Postgres service name** and **internal port 5432** — whichever is smallest and reproducible for the pinned image tag chosen in implementation.

**Rationale**: **FR-009**; avoid manual UI setup each run.

## R7 — Image tags

**Decision**: Pin to **specific image digests or minor tags** in implementation (e.g. `postgres:16-alpine`, `dpage/pgadmin4:8.x`) — exact pins in **`docker-compose.yml`** when implementing; document upgrade path in quickstart.

**Rationale**: Reproducible demos; “latest” acceptable only if project policy allows — prefer pin in implementation PR.
