# Local operator stack

## How to run (at a glance)

| | |
| --- | --- |
| **Full stack** | From the **repo root**: `docker compose up -d` — **recommended** for all long-running services (Kafka, Postgres, producers, consumers, scrapers, dbt scheduler, `frontend-app`, …). |
| **Host `uv`** | Use **`uv run fan_events …`** for the **synthetic fan-events CLI** only (optional second producer, local files, tests). Do **not** use `uv run` as the primary way to start ingest, the Flask API, or other Compose services for normal demos. |

`docker compose up -d` is the fastest way to run the whole MVP once. The stack is practical and local-first: Kafka, Postgres, pgAdmin, the fan-event producer/consumer pair, the player-stats scraper/consumer pair, dbt scheduling, and the Flask UI/API.

The full acceptance-style walkthrough still lives in [`specs/005-compose-kafka-pipeline/quickstart.md`](../specs/005-compose-kafka-pipeline/quickstart.md). This README is the shorter operator runbook.

## What starts

| Service | Purpose |
| --- | --- |
| `broker` | Apache Kafka 4.2.0 in KRaft mode |
| `kafka-init` | One-shot topic creation for `fan_events` |
| `kafka-init-scraper` | One-shot topic creation for `player_stats` |
| `postgres` | PostgreSQL 18 |
| `pgadmin` | Browser UI for Postgres |
| `producer` | Runs `fan_events stream` inside Compose |
| `ingest` | Runs `fan_ingest` and writes `raw_data.fan_events_ingested` |
| `proleague-scheduler` | Daily scrape loop that publishes `player_stats` |
| `proleague-ingest` | Consumes `player_stats` and upserts `raw_data.player_stats` |
| `proleague-scraper` | Internal HTTP read layer for player data |
| `dbt-scheduler` | Periodic dbt runner for analytics marts |
| `frontend-app` | Host-facing UI + API over fan and player data |

Persisted state lives in the named volumes `kafka-data`, `postgres-data`, and `frontend-app-config`.

## Fast path

```bash
cp .env.example .env
docker compose up -d
docker compose ps
```

If you want the default Data Q&A provider, run Ollama on the host and pull `gemma4:e2b`.

## Host vs Compose addresses

| Thing | From the host | From another Compose service |
| --- | --- | --- |
| Kafka | `localhost:9092` | `broker:29092` |
| Postgres | `localhost:${POSTGRES_PORT:-5432}` | `postgres:5432` |
| pgAdmin | `http://localhost:${PGADMIN_PORT:-5050}` | not usually consumed internally |
| `frontend-app` | `http://localhost:${LLM_API_PORT:-8080}` | `http://frontend-app:8080` |

## Common operator commands

```bash
docker compose up -d
docker compose logs -f producer
docker compose logs -f ingest
docker compose logs -f proleague-scheduler
docker compose logs -f proleague-ingest
docker compose logs -f dbt-scheduler
docker compose logs -f frontend-app
```

Verify the fan-event side:

```bash
docker compose exec postgres sh -lc \
  'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "SELECT count(*) FROM raw_data.fan_events_ingested;"'
```

Verify the player-stats side:

```bash
docker compose exec postgres sh -lc \
  'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "SELECT player_id, name, scraped_at FROM raw_data.player_stats ORDER BY name LIMIT 5;"'
curl -s http://localhost:8080/api/player-stats/squad
```

Stop the stack:

```bash
docker compose down
```

Stop and wipe persisted data:

```bash
docker compose down -v
```

## Important `.env` knobs

Full defaults and comments live in [`../.env.example`](../.env.example). These are the ones operators usually touch first.

### Core stack

| Variable | Default | Purpose |
| --- | --- | --- |
| `POSTGRES_USER` / `POSTGRES_PASSWORD` / `POSTGRES_DB` | `postgres` / `changeme` / `fan_pipeline` | Postgres init and service credentials |
| `POSTGRES_PORT` | `5432` | Published host port for Postgres |
| `PGADMIN_DEFAULT_EMAIL` / `PGADMIN_DEFAULT_PASSWORD` | `admin@example.com` / `changeme` | pgAdmin login |
| `PGADMIN_PORT` | `5050` | Published host port for pgAdmin |

### Fan-event pipeline

| Variable | Default | Purpose |
| --- | --- | --- |
| `KAFKA_BOOTSTRAP_SERVERS` | `broker:29092` | Compose-side Kafka bootstrap |
| `KAFKA_TOPIC` | `fan_events` | Synthetic fan-event topic |
| `KAFKA_CONSUMER_GROUP` | `fan-ingest-local` | `ingest` consumer group |
| `DATABASE_URL` | `postgresql://postgres:changeme@postgres:5432/fan_pipeline` | Write-access DB URL for ingest services |
| `FAN_EVENTS_STREAM_SEED` | `42` | Compose producer seed |
| `FAN_EVENTS_STREAM_EMIT_WALL_CLOCK_MIN` / `MAX` | `0.1` / `0.5` | Compose producer pacing |

### Player-stats pipeline

| Variable | Default | Purpose |
| --- | --- | --- |
| `SCRAPER_KAFKA_TOPIC` | `player_stats` | Player-stats topic |
| `SCRAPER_KAFKA_CONSUMER_GROUP` | `scraper-ingest-local` | `proleague-ingest` consumer group |
| `SCRAPER_INTERVAL_HOURS` | `24` | Scheduler interval |
| `SCRAPER_RUN_ON_STARTUP` | `1` | Immediate run on container start |
| `PROLEAGUE_SQUAD_URL` | Club Brugge squad page | Scrape target override |

### dbt and `frontend-app`

| Variable | Default | Purpose |
| --- | --- | --- |
| `DBT_RUN_INTERVAL_MINUTES` | `5` | Compose dbt scheduler interval |
| `DBT_RUN_SELECTOR` | `+mart_fan_loyalty +mart_player_season_summary` | Compose dbt model selector |
| `LLM_READER_PASSWORD` | `change-this-dev-password` | Dev-only password for the read-only DB role |
| `LLM_READER_DATABASE_URL` | `postgresql://llm_reader:...@postgres:5432/fan_pipeline` | Read-only DSN used by `frontend-app` |
| `OLLAMA_URL` | `http://host.docker.internal:11434` | Default Ollama base URL from the container |
| `OLLAMA_MODEL` | `gemma4:e2b` | Default local model |
| `LLM_PROVIDER` | `ollama` | Server-side default provider |
| `OPENROUTER_API_KEY` / `OPENROUTER_MODEL` | unset / `deepseek/deepseek-v3.2` | Hosted provider settings |
| `LLM_API_PORT` | `8080` | Published host port for `frontend-app` |
| `LOG_LEVEL` | `INFO` | Log verbosity for `frontend-app` (`DEBUG` enables SQL/LLM/tool timing) |

## `just` shortcuts

The repo includes a few stack/operator helpers in [`../justfile`](../justfile):

| Recipe | What it runs |
| --- | --- |
| `just kafka-up` | `docker compose up -d` |
| `just kafka-down` | `docker compose down` |
| `just kafka-create-topic` | Creates a Kafka topic inside the broker container |
| `just kafka-consume` | Runs `scripts/kafka_consume_fan_events.py` |
| `just db-grant-player-stats` | Re-grants `llm_reader` access to `player_stats` on older Postgres volumes |

## Troubleshooting

| Problem | What to check |
| --- | --- |
| Host Kafka clients fail | Use `localhost:9092`, not `broker:29092` |
| Compose services fail to reach Kafka | Use `broker:29092`, not `localhost:9092` |
| Host Postgres clients fail | Use `localhost:<POSTGRES_PORT>` from `.env`, not `postgres:5432` |
| Postgres auth or init looks wrong on first boot | Init SQL in `docker/postgres/init/` only runs when `postgres-data` is empty; if credentials or init SQL changed, recreate the volume |
| Data Q&A provider errors | Ollama may not be running on the host, or OpenRouter keys/model access may be missing |
| `/player-stats` shows no players | Wait for the first scrape cycle, then check `proleague-scheduler` and `proleague-ingest` logs |
| Player data is stale | `docker compose restart proleague-scheduler` forces a fresh scrape |

## Related docs

- [`../README.md`](../README.md) - repo-level overview and docs map
- [`../src/fan_events/README.md`](../src/fan_events/README.md) - synthetic event generator
- [`../src/fan_ingest/README.md`](../src/fan_ingest/README.md) - fan-event ingest consumer
- [`../src/proleague_scraper/README.md`](../src/proleague_scraper/README.md) - player scrape scheduler and internal HTTP layer
- [`../src/proleague_ingest/README.md`](../src/proleague_ingest/README.md) - `player_stats` consumer and table notes
- [`../src/frontend_app/README.md`](../src/frontend_app/README.md) - host-facing UI and API
- [`../dbt/README.md`](../dbt/README.md) - dbt workflow and scheduler notes
- [`../specs/005-compose-kafka-pipeline/quickstart.md`](../specs/005-compose-kafka-pipeline/quickstart.md) - deeper end-to-end quickstart
- [`../specs/005-compose-kafka-pipeline/contracts/local-stack-wiring.md`](../specs/005-compose-kafka-pipeline/contracts/local-stack-wiring.md) - wiring contract
