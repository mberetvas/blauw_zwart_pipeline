![Blauw zwart - Synthetic Fan Data Platform](assets/banner_v2.jpg)

# blauw-zwart-fan-sim-pipeline

MVP / non-production sandbox for Club Brugge fan-data demos. The repo combines synthetic fan events, Kafka/Postgres ingest, a Pro League player-stats pipeline, dbt analytics, and a small Flask Text-to-SQL UI.

This is for people who want to run the local stack once, work on one package without reverse-engineering the rest, or jump straight to the right quickstart/spec.

## Repo layout at a glance

| Path | What lives there |
| --- | --- |
| `src/fan_events/` | Synthetic fan-event CLI: rolling batches, calendar-driven match events, retail events, and unified streams |
| `src/fan_ingest/` | Kafka consumer that persists `fan_events` into Postgres |
| `src/proleague_scraper/` | Pro League squad scraper, daily scheduler, and internal HTTP read layer |
| `src/proleague_ingest/` | Kafka consumer that upserts `player_stats` into Postgres |
| `src/llm_api/` | Flask UI + API for Data Q&A, leaderboard, and player stats |
| `dbt/` | Analytics models, dbt profiles, and local dbt workflow |
| `docker-compose.yml` and `docker/` | Local operator stack, image definitions, and init SQL |
| `specs/` | Deep feature quickstarts and contracts |

## How the pieces connect

1. `fan_events` generates synthetic fan events and can publish them to Kafka topic `fan_events`.
2. `fan_ingest` consumes `fan_events` and writes raw rows to Postgres.
3. `proleague_scraper` scrapes Club Brugge squad data, publishes `player_stats`, and serves a small internal HTTP read layer.
4. `proleague_ingest` consumes `player_stats` and upserts `public.player_stats`.
5. `dbt` builds analytics models such as `mart_fan_loyalty`.
6. `llm_api` reads the dbt marts plus player stats and serves the browser UI and JSON API.

## Prerequisites

| Requirement | Why it matters |
| --- | --- |
| Python 3.12+ | Needed for host-side package work, tests, and local CLIs |
| [uv](https://docs.astral.sh/uv/) | Recommended way to install extras, run CLIs, run dbt, and run tests |
| Docker + Docker Compose | Fastest way to run the full MVP stack |
| [Ollama](https://ollama.com/) | Needed only for the default local LLM provider used by `llm_api` |
| [just](https://just.systems/) | Optional convenience wrapper around common stack and CLI commands |

## Fastest path to run the stack once

1. Copy `.env.example` to `.env` (`Copy-Item .env.example .env` in PowerShell).
2. Start the stack from the repo root with `docker compose up -d`.
3. If you want the default Data Q&A flow, make sure Ollama is running on the host and pull `gemma4:e2b`.
4. Open <http://localhost:8080>.

That path starts Kafka, Postgres, pgAdmin, the fan-event producer/consumer pair, the player-stats scraper/consumer pair, the dbt scheduler, and `llm-api`. For service-by-service notes, ports, env vars, and operator commands, use [`docker/README.md`](docker/README.md).

If you are editing code rather than operating the stack, the repo-wide checks are `uv run pytest` and `uv run ruff check .`.

## Documentation map

| Component | README path | What you find there |
| --- | --- | --- |
| `fan_events` | [`src/fan_events/README.md`](src/fan_events/README.md) | CLI modes, install options, common commands, Kafka output notes, and links to the fan-event specs |
| `fan_ingest` | [`src/fan_ingest/README.md`](src/fan_ingest/README.md) | Kafka-to-Postgres ingest flags, env vars, host-vs-Compose connection notes, and persistence docs |
| `proleague_scraper` | [`src/proleague_scraper/README.md`](src/proleague_scraper/README.md) | Scheduler + HTTP read layer, internal routes, env vars, scrape workflow, and compliance notes |
| `proleague_ingest` | [`src/proleague_ingest/README.md`](src/proleague_ingest/README.md) | `player_stats` consumer behavior, message shape, Postgres table summary, and verification commands |
| `llm_api` | [`src/llm_api/README.md`](src/llm_api/README.md) | Flask UI/API usage, provider config, Text-to-SQL flow, routes, screenshots, and guardrails |
| `dbt` | [`dbt/README.md`](dbt/README.md) | Local dbt setup, Compose dbt scheduler notes, profiles, env vars, and Windows-specific dbt guidance |
| Local stack | [`docker/README.md`](docker/README.md) | Compose services, published ports, `.env` knobs, operator commands, `just` wrappers, and stack troubleshooting |

Deep quickstarts and contracts stay under [`specs/`](specs). Each component README links to the relevant spec instead of duplicating it.

Note: no license file is currently present in the repository root.
