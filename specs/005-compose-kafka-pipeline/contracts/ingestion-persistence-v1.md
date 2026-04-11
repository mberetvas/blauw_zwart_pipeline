# Ingestion persistence v1 (normative supplement)

Maps **Kafka message payloads** (each body is one **NDJSON line**: UTF-8 JSON object + `\n`) produced by **`fan_events stream`** into a **minimal relational table** for local stack verification.

## Source payloads

- Each message value is interpreted as **text** encoding **one JSON object** per existing unified-stream rules (see `specs/004-unified-synthetic-stream/contracts/orchestrated-stream.md` and per-`event` contracts).
- **Parse failure (v1)**: If the payload is not a single parseable JSON object as required, ingestion **does not** insert a row; it **logs** (topic, partition, offset, error) and **commits** the offset after skip so consumption advances. No dead-letter destination is required for v1 (**FR-012**).

## Table: `fan_events_ingested` (v1)

Logical columns (exact SQL types are implementation-defined but MUST be documented in init SQL):

| Column            | Required | Description |
|-------------------|----------|-------------|
| `id`              | yes      | Surrogate primary key (e.g. bigserial). |
| `ingested_at`     | yes      | UTC timestamp when the row was inserted (server-side). |
| `kafka_topic`     | yes      | Topic name from which the message was read. |
| `kafka_partition` | yes      | Partition number. |
| `kafka_offset`    | yes      | Offset (unique per partition within a topic; duplicate **delivery** of the same offset is idempotently ignored — see Uniqueness). |
| `event_type`      | yes      | JSON string from top-level `event` field when present; else sentinel documented in spec/init. |
| `event_time`      | nullable | Parsed from the synthetic timestamp field appropriate to the event contract, stored as UTC. |
| `payload_json`    | yes      | Full parsed object re-serialized as JSON text, or raw message body if parse deferred—**one** approach MUST be chosen and documented so queries are stable. |

### Uniqueness and idempotency (normative for v1)

- The table MUST have a **unique** constraint on `(kafka_topic, kafka_partition, kafka_offset)`.
- Inserts MUST be **idempotent** for redelivery of the same broker coordinates: on conflict, **no second row** is created (e.g. PostgreSQL `ON CONFLICT DO NOTHING` on that unique key, or equivalent documented behavior).
- Ingestion MUST document **when** offsets are committed relative to successful insert so retries remain safe under at-least-once delivery.

## Versioning

- **v1** is minimal for local visibility (`SELECT *` in UI).
- Adding normalized columns, constraints, or dead-letter handling requires **v2** of this contract and migration notes.
