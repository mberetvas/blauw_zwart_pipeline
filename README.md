![Blauw zwart - Mock-up data creator](banner.jpg)

# Blauw zwart - Mock-up data creator

Synthetic fan-event pipeline for Club Brugge KV simulations. The package name in `pyproject.toml` is **`blauw-zwart-fan-sim-pipeline`** and the repository ships three Python packages under `src\`: **`fan_events`** (event generation CLI), **`fan_ingest`** (Kafka to Postgres ingest CLI), and **`llm_api`** (Flask Text-to-SQL API used by Docker Compose).

## Table of contents

- [Overview](#overview)
- [Prerequisites](#prerequisites)
- [Install](#install)
- [Quick start](#quick-start)
- [CLIs](#clis)
- [Compose pipeline](#compose-pipeline)
- [API](#api)
- [dbt and analytics](#dbt-and-analytics)
- [Development and test](#development-and-test)
- [Troubleshooting](#troubleshooting)
- [Specs and links](#specs-and-links)

## Overview

| Surface | What it does | How you run it |
|---------|---------------|----------------|
| `fan_events` | Generates synthetic NDJSON fan events | `uv run fan_events ...` |
| `fan_ingest` | Consumes Kafka messages and writes to Postgres | `uv run fan_ingest ...` or the Compose `ingest` service |
| `llm_api` | Serves the browser UI and Text-to-SQL API over Flask | Compose `llm-api` service or `uv run python -m llm_api.app` |
| `dbt\` | Builds analytics models such as `mart_fan_loyalty` | `uv run dbt ...` or the Compose `dbt-scheduler` service |
| `docker-compose.yml` | Starts the local operator stack | `docker compose up -d` |
| `justfile` | Convenience wrappers for common local tasks | `just <recipe>` |

For how those services connect and how events move through Kafka and Postgres into dbt and **`llm-api`**, see the diagrams under [Compose pipeline](#compose-pipeline).

`fan_events` exposes three subcommands:

| Subcommand | Purpose | Primary deeper doc |
|------------|---------|--------------------|
| `generate_events` | v1 rolling-window events, or v2 calendar-driven match events | [`specs/002-match-calendar-events/quickstart.md`](specs/002-match-calendar-events/quickstart.md) |
| `generate_retail` | v3 retail-only NDJSON | [`specs/003-ndjson-v3-retail-sim/quickstart.md`](specs/003-ndjson-v3-retail-sim/quickstart.md) |
| `stream` | Unified v2/v3 stream to stdout, file, or Kafka | [`specs/004-unified-synthetic-stream/quickstart.md`](specs/004-unified-synthetic-stream/quickstart.md) |

## Prerequisites

| Requirement | Notes |
|-------------|-------|
| Python 3.12+ | Required by `pyproject.toml` (`requires-python = ">=3.12"`) |
| [uv](https://docs.astral.sh/uv/) | Recommended for installs, running CLIs, dbt, tests, and lint |
| Docker + Docker Compose | Required for the local stack in `docker-compose.yml` |
| [just](https://just.systems/) | Optional convenience task runner |
| [Ollama](https://ollama.com/) | Required only when you want the default local LLM provider for `llm-api` |

## Install

From a clean clone, work from the repository root (the directory containing `pyproject.toml`).

```bash
uv sync
uv run fan_events --help
```

The project metadata currently defines these install knobs:

| Need | Command | Why |
|------|---------|-----|
| Base project | `uv sync` | Installs the package and the default repo development environment |
| Kafka output from `fan_events stream` | `uv sync --extra kafka` | Adds `confluent-kafka` |
| Host-side `fan_ingest` | `uv sync --extra ingest` | Adds `asyncpg` and `confluent-kafka` |
| Host-side `llm_api` work | `uv sync --extra api` | Adds `flask`, `psycopg2-binary`, `requests`, `pyyaml` |
| dbt tooling | `uv sync --group dbt` | Adds `dbt-core` and `dbt-postgres` |
| Everything for local host development | `uv sync --all-extras --group dbt` | Pulls all extras plus dbt |

Named dependency groups in `pyproject.toml` are **`dev`** and **`dbt`**. Optional extras are **`kafka`**, **`ingest`**, and **`api`**. Console scripts are **`fan_events`** and **`fan_ingest`**.

## Quick start

### 1. Sanity-check the main CLI

```bash
uv sync
uv run fan_events --help
uv run fan_events stream --calendar match_day.example.json -s 42 --retail-max-events 50 --max-events 20
```

That last command emits a small merged stream to stdout and does **not** need the Kafka extra.

### 2. Bring up the local stack

**Unix-like shells**

```bash
cp .env.example .env
docker compose up -d
docker compose ps
```

**Windows PowerShell**

```powershell
Copy-Item .env.example .env
docker compose up -d
docker compose ps
```

The default `.env.example` values expose:

| Host port | Service | Compose-side address |
|-----------|---------|----------------------|
| `9092` | Kafka broker | `broker:29092` |
| `5432` | Postgres | `postgres:5432` |
| `5050` | pgAdmin | `pgadmin:80` |
| `8080` | Flask LLM API | `llm-api:8080` |

For the full Compose walkthrough, use [`specs/005-compose-kafka-pipeline/quickstart.md`](specs/005-compose-kafka-pipeline/quickstart.md).

## CLIs

### `fan_events`

Run subcommand help directly:

```bash
uv run fan_events generate_events --help
uv run fan_events generate_retail --help
uv run fan_events stream --help
```

Use cases and copy-pasteable examples:

| Goal | Command | Notes |
|------|---------|-------|
| v1 rolling-window file | `uv run fan_events generate_events -s 1 -n 200 -d 90 -o out/fan_events.ndjson` | No calendar, no `match_id` |
| v2 calendar file | `uv run fan_events generate_events --calendar match_day.example.json -s 42 -o out/v2.ndjson` | Every line includes `match_id` |
| v3 retail batch | `uv run fan_events generate_retail -s 42 -o out/retail.ndjson` | Retail-only NDJSON |
| v3 retail stream to stdout | `uv run fan_events generate_retail --stream -s 42 --max-events 100` | Immediate stdout stream |
| Unified stream to a file | `uv run fan_events stream --calendar match_day.example.json -s 42 -o out/mixed.ndjson --retail-max-events 500 --max-events 200` | Appends to the output file |
| Unified stream to Kafka | `uv run fan_events stream --calendar match_day.example.json -s 42 --kafka-topic fan_events --kafka-bootstrap-servers localhost:9092 --max-events 200` | Requires `uv sync --extra kafka` |

Important behavior to remember:

| Topic | Current behavior |
|-------|------------------|
| `stream` default loop | With `--calendar`, the season loops by default; use `--no-calendar-loop` for a single pass |
| Output targets | `stream` writes to stdout when `-o/--output` is omitted; `--kafka-topic` is mutually exclusive with `-o/--output` |
| Host vs Compose Kafka | Host commands use `localhost:9092`; Compose services use `broker:29092` |
| Match-day retail tuning | The `stream` subcommand supports home/away match-day retail modifiers; see the 006 contracts linked below |

### `fan_ingest`

`fan_ingest` is the Kafka consumer used by the Compose `ingest` service and is also available on the host when the **`ingest`** extra is installed.

```bash
uv sync --extra ingest
uv run fan_ingest --help
```

Host-side example against the Compose stack:

```bash
uv run fan_ingest --kafka-bootstrap-servers localhost:9092 --kafka-topic fan_events --database-url postgresql://postgres:changeme@localhost:5432/fan_pipeline
```

Defaults are Compose-oriented: `broker:29092`, topic `fan_events`, consumer group `fan-ingest-local`, and `DATABASE_URL` from the environment.

## Compose pipeline

The Compose file runs Kafka (KRaft), Postgres, synthetic **`fan_events stream`** publishing, **`fan_ingest`**, periodic dbt, pgAdmin, and the Flask **`llm-api`**. The diagrams below show topology and data flow; the tables that follow list each service, defaults, and operator commands.

**Diagram A — Compose service map:** services, persisted volumes, startup dependencies (`service_healthy` / `kafka-init` completion), and the ingest topic between **`producer`**, **`broker`**, and **`ingest`**.

```mermaid
flowchart TB
  subgraph vols["Named volumes"]
    V_KAFKA["kafka-data"]
    V_PG["postgres-data"]
    V_LLM["llm-api-config"]
  end

  broker["broker — Kafka 4.x KRaft<br/>Compose clients: broker:29092<br/>Host clients: localhost:9092"]
  kafka_init["kafka-init — one-shot<br/>creates KAFKA_TOPIC default fan_events"]
  producer["producer — fan_events stream"]
  ingest["ingest — fan_ingest"]
  postgres["postgres — Postgres 18<br/>init: docker/postgres/init/"]
  dbt_sched["dbt-scheduler"]
  pgadmin["pgadmin"]
  llm_api["llm-api — Flask UI + API"]

  broker --- V_KAFKA
  postgres --- V_PG
  llm_api --- V_LLM

  kafka_init -->|"depends_on: broker healthy"| broker
  producer -->|"depends_on: broker healthy"| broker
  producer -->|"depends_on: postgres healthy"| postgres
  producer -->|"depends_on: kafka-init done"| kafka_init
  ingest -->|"depends_on: broker healthy"| broker
  ingest -->|"depends_on: postgres healthy"| postgres
  ingest -->|"depends_on: kafka-init done"| kafka_init

  dbt_sched -->|"depends_on: postgres healthy"| postgres
  pgadmin -->|"depends_on: postgres healthy"| postgres
  llm_api -->|"depends_on: postgres healthy"| postgres

  producer -->|"produce KAFKA_TOPIC default fan_events"| broker
  broker -->|"consume same topic"| ingest
```

**Diagram B — End-to-end data flow:** synthetic NDJSON from the container **`producer`** (or optionally from the host) through Kafka and **`fan_ingest`** into Postgres, dbt marts refreshed by **`dbt-scheduler`**, and read-only queries from **`llm-api`**. **Ollama** runs on the host and is reached from the container via `host.docker.internal` (see [API](#api)).

```mermaid
flowchart LR
  subgraph host_ext["Host (outside Compose)"]
    host_producer["Optional: fan_events stream<br/>localhost:9092"]
    ollama["Ollama<br/>host.docker.internal"]
  end

  subgraph stack["Docker Compose"]
    producer["producer<br/>fan_events stream"]
    broker["broker<br/>topic fan_events"]
    ingest["fan_ingest"]
    pg[("Postgres 18")]
    dbt["dbt-scheduler<br/>DBT_RUN_SELECTOR default +mart_fan_loyalty"]
    llm["llm-api<br/>LLM_READER_DATABASE_URL"]
  end

  producer -->|"NDJSON produce"| broker
  host_producer -.->|"optional produce"| broker
  broker -->|"consume"| ingest
  ingest -->|"write ingested / raw layer"| pg
  dbt -->|"build / refresh marts"| pg
  llm -->|"read-only SELECT / WITH"| pg
  ollama -.->|"LLM HTTP when provider is Ollama"| llm
```

| Service name | Purpose |
|--------------|---------|
| `broker` | Apache Kafka 4.2.0 in KRaft mode |
| `kafka-init` | Creates the ingest topic before consumers subscribe |
| `postgres` | PostgreSQL 18 |
| `dbt-scheduler` | Periodic dbt runner for marts |
| `pgadmin` | Browser UI for Postgres |
| `ingest` | Runs `fan_ingest` inside Docker |
| `producer` | Runs `fan_events stream` inside Docker |
| `llm-api` | Flask API and browser UI |

The Compose defaults in `.env.example` line up like this:

| Setting | Default |
|---------|---------|
| `KAFKA_BOOTSTRAP_SERVERS` | `broker:29092` |
| `KAFKA_TOPIC` | `fan_events` |
| `KAFKA_CONSUMER_GROUP` | `fan-ingest-local` |
| `DATABASE_URL` | `postgresql://postgres:changeme@postgres:5432/fan_pipeline` |
| `LLM_READER_PASSWORD` | `change-this-dev-password` |
| `LLM_READER_DATABASE_URL` | `postgresql://llm_reader:change-this-dev-password@postgres:5432/fan_pipeline` |
| `DBT_RUN_SELECTOR` | `+mart_fan_loyalty` |

Useful operator commands:

```bash
docker compose up -d
docker compose logs -f producer
docker compose logs -f ingest
docker compose exec postgres sh -lc 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "SELECT count(*) FROM fan_events_ingested;"'
```

If you use `just`, these recipes are already wired:

| Recipe | What it runs |
|--------|---------------|
| `just help` | `uv run fan_events --help` |
| `just stream` | Unified stdout stream with the repo calendar |
| `just stream-calendar` | Calendar-only stdout stream |
| `just stream-loop` | Continuous calendar loop to stdout |
| `just stream-loop-merged` | Continuous merged loop to stdout |
| `just stream-retail` | Retail-only stdout stream |
| `just kafka-up` | `docker compose up -d` for the full stack |
| `just kafka-down` | `docker compose down` |
| `just kafka-create-topic` | Creates the Kafka topic inside the broker container |
| `just stream-kafka` | Host-side Kafka publishing via `fan_events stream` |
| `just kafka-consume` | Runs `scripts\kafka_consume_fan_events.py` |
| `just generate-events` | v1 rolling batch |
| `just generate-calendar` | v2 calendar batch |
| `just generate-retail` | v3 retail batch |

## API

The Compose **`llm-api`** service runs `python -m llm_api.app` from `src\llm_api\`. It serves both the browser UI and the JSON API.

Current provider support:

| Provider | How it is configured |
|----------|----------------------|
| Ollama | Default provider via `OLLAMA_URL`, `OLLAMA_MODEL`, and `OLLAMA_TIMEOUT` |
| OpenRouter | Optional provider via `OPENROUTER_API_KEY`, `OPENROUTER_BASE_URL`, `OPENROUTER_MODEL`, and `OPENROUTER_TIMEOUT` |

Runtime config is persisted through `LLM_CONFIG_PATH` in Compose (`/data/llm_config.json` on the named volume).

**Schema context for Text-to-SQL.** The API merges dbt YAML column documentation (staging, intermediate, marts) into the SQL-generation prompt. The Docker image sets `DBT_MODELS_DIR` to a baked copy of `dbt\models\staging`, `intermediate`, and `marts`. On the host, set `DBT_MODELS_DIR` to `.\dbt\models` (or use comma-separated `SCHEMA_FILES`, or a single `SCHEMA_FILE`). Optional: `DBT_RELATION_SCHEMA` (default `dbt_dev`, matching `llm_reader` search_path), `SCHEMA_CONTEXT_MAX_CHARS`, and `SCHEMA_CONTEXT_OVERFLOW` (`error` or `truncate`). See `.env.example`.

### Run it in Compose

1. Copy `.env.example` to `.env`.
2. Change `LLM_READER_PASSWORD` in `.env` if you do not want the documented dev-only default.
3. Start the stack with `docker compose up -d`.
4. If you use Ollama, pull the default model on the host: `ollama pull gemma4:e2b`.
5. Wait for `dbt-scheduler` to materialize the marts: `docker compose logs -f dbt-scheduler`.

Then open the UI at <http://localhost:8080> or call the API directly:

```bash
curl -s -X POST http://localhost:8080/api/ask -H "Content-Type: application/json" -d "{\"question\":\"Who are the top 5 fans by total spend?\"}"
```

### Run it on the host

```bash
uv sync --extra api
uv run python -m llm_api.app
```

### Routes

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/` | Main chat UI |
| `GET` | `/leaderboard` | Leaderboard page |
| `GET` | `/player-stats` | Player stats page |
| `GET` | `/settings` | Settings page |
| `GET` | `/health` | Health check |
| `GET` | `/api/leaderboard?window=all` | Live all-time fan leaderboard from `mart_fan_loyalty` |
| `GET` | `/api/llm-config` | Read public runtime config |
| `PUT` | `/api/llm-config` | Persist runtime config changes |
| `POST` | `/api/ask` | Question to SQL to answer flow |

The API executes read-only `SELECT` / `WITH ... SELECT` queries only, wraps results in an outer `LIMIT 50`, and sets `statement_timeout` to 10 seconds on each DB session.

The chat UI also sends a small slice of recent successful turns with each new `/api/ask` request so follow-up questions like “these fans”, “them”, or “that match” stay scoped to the previous result set instead of silently broadening back to the full table.

`GET /api/leaderboard` uses the same read-only Postgres DSN (`LLM_READER_DATABASE_URL`, falling back to `DATABASE_URL`) as the Text-to-SQL API. In v1 it supports `window=all` only and ranks fans from `dbt_dev.mart_fan_loyalty` with:

```text
points = ROUND(
    CASE WHEN matches_attended > 0 THEN 1000 ELSE 0 END
    + 150 * matches_attended
    + total_spend
    + 5 * merch_purchase_count
    + 5 * retail_purchase_count
)::bigint
```

Tie-breakers are `points DESC`, `matches_attended DESC`, `total_spend DESC`, and `fan_id ASC`. Referral/community-engagement metrics are not tracked yet, so the leaderboard returns `null` for those values instead of inventing them.

## dbt and analytics

The repository includes a dbt project in `dbt\` and a scheduled Compose runner in the `dbt-scheduler` service.

Host-side setup:

```bash
uv sync --group dbt
uv run --env-file .env dbt debug --project-dir . --profiles-dir dbt
uv run --env-file .env dbt run --project-dir . --profiles-dir dbt --select +mart_fan_loyalty
```

Windows note: follow the guidance in `.env.example` and prefer **`uv run dbt ...`** over a bare `dbt ...` command if your global `dbt` points at dbt Fusion.

Relevant analytics assets:

| Asset | Path |
|-------|------|
| dbt project config | `dbt_project.yml` |
| Host profiles | `dbt\profiles.yml` and `dbt\profiles.yml.example` |
| Loyalty mart SQL | `dbt\models\marts\mart_fan_loyalty.sql` |
| dbt schema docs (marts + upstream YAML) | `dbt\models\marts\schema.yml` and `dbt\models\**\*_schema.yaml` (used by `llm_api` / `DBT_MODELS_DIR`) |

## Development and test

From the repository root:

```bash
uv run pytest
uv run ruff check .
```

Helpful smoke checks while editing docs or workflows:

```bash
uv run fan_events --help
uv run fan_ingest --help
```

## Troubleshooting

| Problem | What to check |
|---------|---------------|
| `fan_events stream --kafka-topic ...` fails immediately | Install the Kafka extra first: `uv sync --extra kafka` |
| Host `fan_ingest` cannot connect to Kafka | Use `localhost:9092`, not `broker:29092` |
| Compose services cannot connect to Kafka | Inside Compose, use `broker:29092`, not `localhost:9092` |
| Host Postgres client cannot connect | Use `localhost:<POSTGRES_PORT>` from `.env`, not `postgres:5432` |
| `llm-api` returns provider errors | Verify Ollama is running on the host or that OpenRouter keys/model access are configured |
| dbt on Windows fails with Postgres DLL issues | Use `uv sync --group dbt` and `uv run dbt ...` rather than a global `dbt` binary |
| You want only one calendar pass from `stream` | Add `--no-calendar-loop` |

## Specs and links

Use these documents when you need deeper detail than the README:

| Topic | Path | Notes |
|-------|------|-------|
| v1 rolling NDJSON contract | [`specs/001-synthetic-fan-events/contracts/fan-events-ndjson-v1.md`](specs/001-synthetic-fan-events/contracts/fan-events-ndjson-v1.md) | Normative v1 schema and ordering rules |
| v2 calendar quick start | [`specs/002-match-calendar-events/quickstart.md`](specs/002-match-calendar-events/quickstart.md) | Current calendar-driven generator walkthrough |
| v3 retail quick start | [`specs/003-ndjson-v3-retail-sim/quickstart.md`](specs/003-ndjson-v3-retail-sim/quickstart.md) | Current retail generator walkthrough |
| Unified stream quick start | [`specs/004-unified-synthetic-stream/quickstart.md`](specs/004-unified-synthetic-stream/quickstart.md) | Current `stream` examples |
| Compose pipeline quick start | [`specs/005-compose-kafka-pipeline/quickstart.md`](specs/005-compose-kafka-pipeline/quickstart.md) | Full Docker operator flow |
| Match-day retail stream details | [`specs/006-stream-three-event-kinds/contracts/cli-match-day-flags-006.md`](specs/006-stream-three-event-kinds/contracts/cli-match-day-flags-006.md) | Extra `stream` retail-tuning flags |
| Stream duration and `t0` details | [`specs/006-stream-three-event-kinds/contracts/cli-stream-006-supplement.md`](specs/006-stream-three-event-kinds/contracts/cli-stream-006-supplement.md) | Post-merge duration semantics |
| Governance | [`.specify/memory/constitution.md`](.specify/memory/constitution.md) | Repo process and conventions |

The historical quickstart under `specs/001-synthetic-fan-events/quickstart.md` predates the consolidated `fan_events` CLI; use the commands in this README for current v1 invocation.

No license file is currently present in the repository root.
