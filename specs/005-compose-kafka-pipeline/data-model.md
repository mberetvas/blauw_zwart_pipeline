# Data model: local ingestion (v1)

Normative column semantics match **`contracts/ingestion-persistence-v1.md`**. Physical types are implementation-defined; recommended PostgreSQL mapping below.

## Table: `fan_events_ingested`

| Column | PostgreSQL type (recommended) | Nullable | Notes |
|--------|---------------------------------|----------|--------|
| `id` | `BIGSERIAL` | no | Surrogate PK. |
| `ingested_at` | `TIMESTAMPTZ` | no | Default `now()` at insert; server UTC. |
| `kafka_topic` | `TEXT` | no | From consumer context. |
| `kafka_partition` | `INT` | no | Non-negative. |
| `kafka_offset` | `BIGINT` | no | Broker offset. |
| `event_type` | `TEXT` | no | From JSON `event` string; if missing use sentinel **`unknown`** (document in SQL comment). |
| `event_time` | `TIMESTAMPTZ` | yes | Parsed UTC instant from payload; see **research R5**. |
| `payload_json` | `JSONB` | no | Canonical choice: store **parsed** JSONB for stable querying; alternative TEXT JSON documented once only. |

## Constraints & indexes

- **UNIQUE** `(kafka_topic, kafka_partition, kafka_offset)` — required by **FR-011**.
- **Index** optional on `(ingested_at)` or `(event_type, ingested_at)` for pgAdmin browsing — nice-to-have, not spec-required.

## Idempotent insert

- `INSERT … ON CONFLICT (kafka_topic, kafka_partition, kafka_offset) DO NOTHING` (or unique index name).
- Consumer **commits** offset **after** insert success or conflict (no new row) — still “processed”.

## Parse failure

- No row; log; **commit** offset — **FR-012**.

## Relationships

- Standalone table for v1; **no FKs** to other entities.
