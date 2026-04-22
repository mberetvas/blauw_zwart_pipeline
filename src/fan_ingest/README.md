# fan_ingest

Kafka consumer that ingests synthetic fan events into Postgres. The Compose `ingest` service runs this package, and you can also run it directly on the host when you want to debug ingestion behavior against a local stack.

## Install

```bash
uv sync --extra ingest
uv run fan_ingest --help
```

## Common commands

Run against a local Compose stack from the host:

```bash
uv run fan_ingest \
  --kafka-bootstrap-servers localhost:9092 \
  --kafka-topic fan_events \
  --database-url postgresql://postgres:changeme@localhost:5432/fan_pipeline
```

The Compose service uses the same entrypoint, but its defaults are Compose-oriented (`broker:29092`, topic `fan_events`, consumer group `fan-ingest-local`).

## Flags and environment variables

CLI flags take precedence over environment variables.

| Flag / variable | Default | Notes |
| --- | --- | --- |
| `--kafka-bootstrap-servers` / `KAFKA_BOOTSTRAP_SERVERS` | `broker:29092` | Use `localhost:9092` from the host; use `broker:29092` inside Compose |
| `--kafka-topic` / `KAFKA_TOPIC` | `fan_events` | Kafka topic to subscribe to |
| `--kafka-consumer-group` / `KAFKA_CONSUMER_GROUP` | `fan-ingest-local` | Local consumer group id |
| `--database-url` / `DATABASE_URL` | unset | Required Postgres DSN |

## What it writes

`fan_ingest` persists the raw event stream into Postgres so downstream tools can model or inspect it. The deeper ingestion contract lives in [`specs/005-compose-kafka-pipeline/contracts/ingestion-persistence-v1.md`](../../specs/005-compose-kafka-pipeline/contracts/ingestion-persistence-v1.md).

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
- [`../../specs/005-compose-kafka-pipeline/quickstart.md`](../../specs/005-compose-kafka-pipeline/quickstart.md) - Compose walkthrough
- [`../../specs/005-compose-kafka-pipeline/contracts/ingestion-persistence-v1.md`](../../specs/005-compose-kafka-pipeline/contracts/ingestion-persistence-v1.md) - persistence contract
