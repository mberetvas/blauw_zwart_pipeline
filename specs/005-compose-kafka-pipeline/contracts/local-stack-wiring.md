# Local stack wiring (operational contract)

Compose **service names**, **ports**, and **Kafka listener roles** for feature **005-compose-kafka-pipeline**. Implementation MUST match this wiring or update this contract with rationale.

## Services (logical names)

| Service name | Image family | Role |
|--------------|--------------|------|
| `broker` | `apache/kafka` | Single-node KRaft broker + controller |
| `postgres` | `postgres` | Application database |
| `pgadmin` | `dpage/pgadmin4` | Browser UI for Postgres |
| `producer` | Project `Dockerfile.ingest` | Compose-managed `fan_events stream` producer publishing merged v2 + v3 events to Kafka |
| `ingest` | Project `Dockerfile.ingest` | Kafka → Postgres consumer |

*(Exact image tags pinned in `docker-compose.yml` at implementation time.)*

## Ports (host)

| Port | Service | Purpose |
|------|---------|---------|
| **9092** | `broker` | **EXTERNAL** Kafka listener — **host producers** (`fan_events`, tools) |
| **29092** | optional expose | Only if debugging; **INTERNAL** listener typically **not** published to host |
| **5432** (or env) | `postgres` | **FR-014** — host access to DB (configurable to avoid clashes) |
| **5050** (or env) | `pgadmin` | HTTP UI |

## Kafka listeners (normative pattern)

| Listener name | Container port | Advertised to clients |
|---------------|----------------|------------------------|
| `INTERNAL` | 29092 | `broker:29092` — **ingest** and other Compose clients |
| `EXTERNAL` | 9092 | `localhost:9092` — **host** clients |
| `CONTROLLER` | 9093 | `broker:9093` — KRaft quorum (not for clients) |

## Environment variables (illustrative)

Documented fully in **`.env.example`** and **quickstart.md**:

- **Postgres**: `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB`, optional `POSTGRES_PORT` for host mapping.
- **pgAdmin**: `PGADMIN_DEFAULT_EMAIL`, `PGADMIN_DEFAULT_PASSWORD`, config for pre-registered server.
- **Compose producer + ingest**: `KAFKA_BOOTSTRAP_SERVERS=broker:29092` (INTERNAL) and a shared `KAFKA_TOPIC`; producer-specific pacing/seed defaults come from `FAN_EVENTS_STREAM_*`.
- **Optional host producer**: `FAN_EVENTS_KAFKA_BOOTSTRAP_SERVERS=localhost:9092`, `FAN_EVENTS_KAFKA_TOPIC=…`.

## Volumes

- **`kafka-data`** — existing broker data; **retained** per **FR-003**.
- **`postgres-data`** (name illustrative) — named volume for Postgres data durability.
