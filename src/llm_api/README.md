# llm_api

Flask UI + JSON API for the MVP demo. This package serves the Data Q&A chat, the fan leaderboard, the player-stats page, and the settings page that persists runtime LLM configuration.

## Screenshots

### Chat UI

![LLM front end - Chat UI](../../assets/chat-ai.jpg)

### Fan leaderboard

![LLM front end - Fan leaderboard](../../assets/fan%20leaderboard.jpg)

### Player stats

![LLM front end - Player stats](../../assets/player-stats.jpg)

## What it serves

| Surface | What it does |
| --- | --- |
| Data Q&A (`/`) | Natural-language question -> SQL -> answer flow over Postgres |
| Leaderboard (`/leaderboard`) | Reads `mart_fan_loyalty` and ranks fans |
| Player stats (`/player-stats`) | Compares cached squad data and can fetch individual player details |
| Settings (`/settings`) | Persists runtime Ollama / OpenRouter settings |

## Run it in Compose

1. Copy `.env.example` to `.env`.
2. Start the stack with `docker compose up -d`.
3. If you use the default provider, run Ollama on the host and pull `gemma4:e2b`.
4. Wait for dbt to materialize the marts (`docker compose logs -f dbt-scheduler`).
5. Open <http://localhost:8080>.

Quick API smoke test:

```bash
curl -s -X POST http://localhost:8080/api/ask \
  -H "Content-Type: application/json" \
  -d "{\"question\":\"Who are the top 5 fans by total spend?\"}"
```

## Run it on the host

```bash
uv sync --extra api
uv run python -m llm_api.app
```

When the API runs on your machine against the Compose Postgres instance, use host-friendly DSNs (`localhost:<POSTGRES_PORT>`) instead of the Compose-internal `postgres:5432` addresses from `.env.example`.

## Runtime configuration

### Provider and app settings

| Variable | Default | Purpose |
| --- | --- | --- |
| `LLM_READER_DATABASE_URL` | falls back to `DATABASE_URL` | Read-only Postgres DSN used for SQL execution |
| `DATABASE_URL` | unset | Fallback DB connection for read-only queries |
| `LLM_PROVIDER` | `ollama` | Server-side default provider (`ollama` or `openrouter`) |
| `OLLAMA_URL` | `http://host.docker.internal:11434` | Ollama base URL |
| `OLLAMA_MODEL` | `gemma4:e2b` | Default Ollama model |
| `OLLAMA_TIMEOUT` | `120` | Ollama request timeout in seconds |
| `OPENROUTER_API_KEY` | unset | OpenRouter API key |
| `OPENROUTER_BASE_URL` | `https://openrouter.ai/api/v1` | OpenRouter API base URL |
| `OPENROUTER_MODEL` | first built-in default | Default OpenRouter model id |
| `OPENROUTER_MODELS` | built-in defaults | Comma-separated suggestion list for the settings UI |
| `OPENROUTER_TIMEOUT` | `120` | OpenRouter request timeout in seconds |
| `LLM_CONFIG_PATH` | `src/llm_api/llm_config.json` or `/data/llm_config.json` in Compose | JSON file for persisted runtime config |
| `PROLEAGUE_SCRAPER_URL` | `http://proleague-scraper:8001` | Internal scraper base URL for player lookups and image proxying |
| `PORT` | `8080` | Direct app port when running manually |

### Schema and semantic prompt context

| Variable | Default | Purpose |
| --- | --- | --- |
| `SCHEMA_FILES` | unset | Highest-priority comma-separated list of dbt schema files |
| `DBT_MODELS_DIR` | unset | Folder scan mode for `*_schema.yaml` plus `marts/schema.yml` |
| `SCHEMA_FILE` | `src/llm_api/schema.yml` | Single-file fallback when the dbt-derived inputs are unset |
| `DBT_RELATION_SCHEMA` | `dbt_dev` | Schema name echoed into the SQL prompt |
| `SCHEMA_CONTEXT_MAX_CHARS` | `0` | Maximum merged schema length (`0` means unlimited) |
| `SCHEMA_CONTEXT_OVERFLOW` | `error` | Overflow mode: `error` or `truncate` |
| `SEMANTIC_LAYER_FILE` | `src/llm_api/semantic/semantic_layer.yml` | Optional semantic layer YAML path |
| `SEMANTIC_CONTEXT_MAX_CHARS` | `0` | Maximum rendered semantic-layer length (`0` means unlimited) |

## Routes

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/` | Main chat UI |
| `GET` | `/leaderboard` | Fan leaderboard page |
| `GET` | `/player-stats` | Player stats comparison page |
| `GET` | `/settings` | Settings page |
| `GET` | `/health` | Health check |
| `GET` | `/api/leaderboard?window=all` | Live all-time leaderboard from `mart_fan_loyalty` |
| `GET` | `/api/llm-config` | Read public runtime config |
| `PUT` | `/api/llm-config` | Persist runtime config changes |
| `POST` | `/api/ask` | Non-streaming question -> SQL -> answer flow |
| `POST` | `/api/ask/stream` | Streaming SSE version of the same pipeline |
| `GET` | `/api/player-stats/squad` | Cached Club Brugge squad from Postgres |
| `GET` | `/api/player-stats/player?url=<url>` | Live single-player fetch via `proleague-scraper` |
| `GET` | `/api/player-stats/image?url=<url>` | Server-side image proxy for approved league CDNs |

## How the Data Q&A flow works

In one sentence: English question -> LLM proposes SQL -> the app runs a bounded read-only query -> the LLM turns the result rows into a human answer.

Current pipeline:

1. The browser sends a question, provider/model selection, and a small slice of recent conversation.
2. The app builds a SQL-generation prompt from dbt schema YAML, optional semantic-layer text, recent conversation, and the question itself.
3. The first LLM call returns one PostgreSQL `SELECT` or `WITH ... SELECT`.
4. Flask validates and executes that SQL as the `llm_reader` role.
5. The app builds an answer prompt from the question plus real result rows.
6. The second LLM call returns the final markdown answer, either as one JSON response or as SSE fragments.

### Guardrails

| Guardrail | Detail |
| --- | --- |
| Read-only SQL only | Query must begin with `SELECT` or `WITH` |
| No multi-statement input | Semicolons are rejected |
| Outer row cap | Execution is wrapped in an outer `LIMIT 50` |
| Time limit | Every DB session sets `statement_timeout` to 10 seconds |

### Streaming details

`POST /api/ask/stream` emits Server-Sent Events with `meta`, `answer_delta`, `done`, or `error` events. Successful follow-up questions also carry a small history window so prompts like "these fans" or "that match" stay scoped.

### What the model sees vs what the UI gets

| Variable | Contents | Consumer |
| --- | --- | --- |
| `preview` | Up to 10 executed rows as JSON | Second LLM call |
| `data_preview` | All executed rows up to the `LIMIT 50` cap | HTTP JSON response and SSE `meta` event |

## Leaderboard scoring (current v1)

`GET /api/leaderboard` reads `dbt_dev.mart_fan_loyalty` and computes:

```text
points = ROUND(
    CASE WHEN matches_attended > 0 THEN 1000 ELSE 0 END
    + 150 * matches_attended
    + total_spend
    + 5 * merch_purchase_count
    + 5 * retail_purchase_count
)::bigint
```

Tie-breakers are `points DESC`, `matches_attended DESC`, `total_spend DESC`, then `fan_id ASC`.

## Troubleshooting

| Problem | What to check |
| --- | --- |
| Provider errors in `/api/ask` | Ollama may not be running on the host, or OpenRouter credentials/model access may be wrong |
| Host-run API cannot reach Postgres | Use `localhost:<POSTGRES_PORT>` in the DSN, not the Compose hostname `postgres` |
| `/player-stats` shows no players | The first scrape has not completed yet; check `proleague-scheduler` and `proleague-ingest` logs |
| Player images do not load | The proxy route is `/api/player-stats/image`; inspect `docker compose logs -f llm-api` for upstream/proxy errors |
| Schema-context startup error | Check `SCHEMA_FILES`, `DBT_MODELS_DIR`, `SCHEMA_FILE`, and the overflow settings |

## Related docs

- [`../../README.md`](../../README.md) - repo-level overview
- [`../../docker/README.md`](../../docker/README.md) - Compose stack and operator commands
- [`../../dbt/README.md`](../../dbt/README.md) - dbt setup and the models this API reads
- [`../proleague_scraper/README.md`](../proleague_scraper/README.md) - internal player-scraper service
- [`../proleague_ingest/README.md`](../proleague_ingest/README.md) - cached `player_stats` ingest path
- [`../../specs/005-compose-kafka-pipeline/quickstart.md`](../../specs/005-compose-kafka-pipeline/quickstart.md) - end-to-end local stack walkthrough
