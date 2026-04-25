# fan_ingest

Kafka consumer that ingests synthetic fan events into Postgres.

## High-level flow

```mermaid
flowchart LR
    producer["fan_events producer<br/><i>NDJSON over Kafka</i>"]
    subgraph kafka ["Kafka"]
        topic[("fan_events topic")]
    end
    subgraph svc ["fan_ingest"]
        consumer["Consumer<br/><i>group: fan-ingest-local</i>"]
        runtime["Async runtime<br/><i>parse + insert</i>"]
    end
    subgraph pg ["Postgres"]
        table[("raw_data.fan_events_ingested")]
    end

    producer -- "publish" --> topic
    topic -- "poll" --> consumer
    consumer --> runtime
    runtime -- "INSERT (idempotent on Kafka coord)" --> table
```

## How to run (at a glance)

| | |
| --- | --- |
| **Recommended** | Start the stack from the repo root: **`docker compose up -d`** — the **`ingest`** service runs this package inside Compose. See [`../../docker/README.md`](../../docker/README.md). |
| **Host `uv` (optional)** | **`uv run fan_ingest …`** only for **debugging** or advanced setups against a stack that is already up — not the primary way to run the MVP. |

## Install (host debugging only)

```bash
uv sync --extra ingest
uv run fan_ingest --help
```

## Optional: run on the host against a local stack

The Compose **`ingest`** service uses Compose-oriented defaults (`broker:29092`, topic `fan_events`, consumer group `fan-ingest-local`). From your machine, point at the **external** Kafka listener and published Postgres port:

```bash
uv run fan_ingest \
  --kafka-bootstrap-servers localhost:9092 \
  --kafka-topic fan_events \
  --database-url postgresql://postgres:changeme@localhost:5432/fan_pipeline
```

## Flags and environment variables

CLI flags take precedence over environment variables.

| Flag / variable | Default | Notes |
| --- | --- | --- |
| `--kafka-bootstrap-servers` / `KAFKA_BOOTSTRAP_SERVERS` | `broker:29092` | Use `localhost:9092` from the host; use `broker:29092` inside Compose |
| `--kafka-topic` / `KAFKA_TOPIC` | `fan_events` | Kafka topic to subscribe to |
| `--kafka-consumer-group` / `KAFKA_CONSUMER_GROUP` | `fan-ingest-local` | Local consumer group id |
| `--database-url` / `DATABASE_URL` | unset | Required Postgres DSN |

## What it writes

Rows land in **`raw_data.fan_events_ingested`** (created on startup if missing — same DDL as `docker/postgres/init/001_fan_events_ingested.sql`). Inserts are idempotent: a unique constraint on the Kafka coordinate (topic, partition, offset) means re-consumed messages are silently skipped.

## Troubleshooting

| Problem | What to check |
| --- | --- |
| The process exits immediately | `DATABASE_URL` is required; pass `--database-url` or export it first |
| Host ingest cannot connect to Kafka | Use `localhost:9092`, not `broker:29092` |
| Compose ingest cannot connect to Kafka | Use `broker:29092`, not `localhost:9092` |
| Host ingest cannot connect to Postgres | Use `localhost:<POSTGRES_PORT>` from `.env`, not `postgres:5432` |

## Related docs

- [`../../README.md`](../../README.md) - repo-level overview
- [`../fan_events/README.md`](../fan_events/README.md) - producer-side docs for the `fan_events` topic
- [`../../docker/README.md`](../../docker/README.md) - full stack, logs, and operator commands
