# dbt analytics

## How to run (at a glance)

| | |
| --- | --- |
| **Demo stack / scheduled builds** | **`docker compose up -d`** from the repo root starts **`dbt-scheduler`** with the rest of the MVP (see [`../docker/README.md`](../docker/README.md)). This is the **recommended** path for keeping marts fresh while the stack runs. |
| **Local `uv run dbt …`** | **Optional development** workflow when iterating on models against a running Postgres (from the host). It is **not** a substitute for Compose for “running the project”. |

The repo ships a dbt project under `dbt/` for analytics models such as `mart_fan_loyalty`. The same project is used in **Compose** (primary for the demo) and optionally on the host with `uv run dbt …` for development.

## What matters here

| Asset | Path |
| --- | --- |
| dbt project config | [`../dbt_project.yml`](../dbt_project.yml) |
| Local profiles | [`profiles.yml`](profiles.yml) and [`profiles.yml.example`](profiles.yml.example) |
| Loyalty mart | [`models/marts/mart_fan_loyalty.sql`](models/marts/mart_fan_loyalty.sql) |
| Schema docs used by `frontend_app` | `models/**/*_schema.yaml` and [`models/marts/schema.yml`](models/marts/schema.yml) |

## Run dbt via Compose (recommended for the MVP)

The `dbt-scheduler` service uses the same project but runs inside Docker (usually started with the full stack):

```bash
docker compose up -d
docker compose logs -f dbt-scheduler
```

To run only the scheduler (if the rest of the stack is already up):

```bash
docker compose up -d dbt-scheduler
docker compose logs -f dbt-scheduler
```

By default it refreshes `+mart_fan_loyalty +mart_player_season_summary` immediately on startup and then every `DBT_RUN_INTERVAL_MINUTES`.

## Run dbt locally (development only)

Use this when you are editing SQL/YAML and want faster iteration against Postgres on `localhost` — **not** as the primary way to run the demo stack.

```bash
uv sync --group dbt
uv run --env-file .env dbt debug --project-dir . --profiles-dir dbt
uv run --env-file .env dbt run --project-dir . --profiles-dir dbt --select +mart_fan_loyalty
```

The project file lives at the repo root, so run dbt commands from the repo root even though the models live in `dbt/`.

## Environment variables

| Variable | Default | Purpose |
| --- | --- | --- |
| `DBT_PROFILES_DIR` | `./dbt` | Directory containing `profiles.yml` |
| `DBT_POSTGRES_HOST` | `localhost` | Host-side Postgres hostname |
| `DBT_POSTGRES_PORT` | `5432` | Host-side Postgres port |
| `DBT_TARGET_SCHEMA` | `dbt_dev` | Schema where dbt builds its relations |
| `DBT_RUN_INTERVAL_MINUTES` | `5` | Compose scheduler interval |
| `DBT_RUN_SELECTOR` | `+mart_fan_loyalty +mart_player_season_summary` | Compose scheduler model selector |
| `POSTGRES_USER` | from `.env` | dbt profile credential |
| `POSTGRES_PASSWORD` | from `.env` | dbt profile credential |
| `POSTGRES_DB` | from `.env` | dbt profile database |

## Windows notes

If `dbt --version` prints `dbt-fusion`, the binary on your PATH is not the Postgres adapter used by this repo. On Windows, prefer:

```bash
uv sync --group dbt
uv run --env-file .env dbt ...
```

Do not point `DBT_PROFILE` at a file path such as `dbt/profiles.yml`. If you set it at all, it should be the profile name `fan_sim_pipeline`.

## Why `frontend_app` cares about this folder

`frontend_app` can build its Text-to-SQL schema context directly from the dbt YAML docs in this project. In Compose the API image bakes in a copy of the dbt schemas; on the host you can point `DBT_MODELS_DIR=./dbt/models`.

## Troubleshooting

| Problem | What to check |
| --- | --- |
| dbt cannot connect to Postgres from the host | Use `localhost:<POSTGRES_PORT>` from `.env`, not `postgres:5432` |
| dbt on Windows fails with Postgres DLL errors | Use `uv run dbt ...` rather than a global `dbt` binary |
| dbt says the profile is not found | `DBT_PROFILE` should be unset or `fan_sim_pipeline`, and `DBT_PROFILES_DIR` should point at the `dbt/` folder |

## Related docs

- [`../README.md`](../README.md) - repo-level overview
- [`../docker/README.md`](../docker/README.md) - Compose scheduler and stack-level docs
- [`../src/frontend_app/README.md`](../src/frontend_app/README.md) - how dbt YAML docs feed the Text-to-SQL prompts
