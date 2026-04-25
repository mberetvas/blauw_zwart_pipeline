# proleague_ingest

Kafka consumer for the player-stats side of the MVP stack. It subscribes to the `player_stats` topic, then upserts the latest squad scrape into `raw_data.player_stats`.

This service is packaged by [`docker/Dockerfile.scraper-ingest`](../../docker/Dockerfile.scraper-ingest) with [`docker/requirements.scraper-ingest.txt`](../../docker/requirements.scraper-ingest.txt). Like `proleague_scraper`, it is Compose-first rather than part of the repo's `uv` extras.

## How to run (at a glance)

| | |
| --- | --- |
| **Recommended** | **`docker compose up -d`** from the repo root — the **`proleague-ingest`** service runs this consumer. See [`../../docker/README.md`](../../docker/README.md). |
| **Host `uv`** | Not a supported operator path — use Compose. |

## How to run it

```bash
docker compose up -d proleague-scheduler proleague-ingest
docker compose logs -f proleague-ingest
```

Verify rows landed in Postgres:

```bash
docker compose exec postgres sh -lc \
  'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "SELECT player_id, name, scraped_at FROM player_stats ORDER BY name LIMIT 5;"'
```

## Environment variables

| Variable | Default | Purpose |
| --- | --- | --- |
| `KAFKA_BOOTSTRAP_SERVERS` | `broker:29092` | Kafka bootstrap address inside Compose |
| `SCRAPER_KAFKA_TOPIC` | `player_stats` | Topic to subscribe to |
| `SCRAPER_KAFKA_CONSUMER_GROUP` | `scraper-ingest-local` | Consumer group id |
| `DATABASE_URL` | unset | Required write-access Postgres DSN |

## Kafka message shape (v1)

Each message represents one player:

```json
{
  "_schema_version": 1,
  "event_type": "player_stats_scraped",
  "source_url": "https://www.proleague.be/teams/club-brugge-kv-182/squad",
  "scraped_at": "2026-04-13T21:00:00Z",
  "player": {
    "player_id": "3219",
    "slug": "simon-mignolet-3219",
    "name": "Simon Mignolet",
    "position": "Goalkeeper",
    "shirt_number": 1,
    "image_url": "https://imagecache.proleague.be/...",
    "profile": { "...": "..." },
    "stats": [{ "key": "savesMade", "label": "Saves", "value": 72 }]
  }
}
```

The Kafka key is `player_id` bytes for deterministic partition routing. Duplicate deliveries are safe because the Postgres write path is an upsert.

## Postgres table

`raw_data.player_stats` is created by [`docker/postgres/init/003_player_stats.sql`](../../docker/postgres/init/003_player_stats.sql).

| Column | Type | Notes |
| --- | --- | --- |
| `player_id` | `TEXT` primary key | Pro League numeric ID |
| `slug` | `TEXT` | URL slug |
| `name` | `TEXT` | Display name |
| `position` / `field_position` | `TEXT` | Position labels |
| `shirt_number` | `INTEGER` | Squad number |
| `image_url` | `TEXT` | Player image CDN URL |
| `profile` | `JSONB` | Structured player profile data |
| `stats` | `JSONB` | Main-competition stat array |
| `competition` | `TEXT` | Competition name |
| `source_url` | `TEXT` | Squad page used for the scrape |
| `scraped_at` | `TIMESTAMPTZ` | Last successful scrape time |

The `llm_reader` role also has `SELECT` access on this table so `frontend_app` can query it.

## Smoke checks

```bash
docker compose logs -f proleague-scheduler
docker compose logs -f proleague-ingest
curl -s http://localhost:8080/api/player-stats/squad
```

## Troubleshooting

| Problem | What to check |
| --- | --- |
| The consumer exits immediately | `DATABASE_URL` is required |
| The consumer cannot reach Kafka | Inside Compose, use `broker:29092`, not `localhost:9092` |
| Rows never appear in `player_stats` | Confirm `proleague-scheduler` is producing and the topic name matches `SCRAPER_KAFKA_TOPIC` |
| Data looks stale | Restart `proleague-scheduler` to force a fresh scrape |

## Related docs

- [`../../README.md`](../../README.md) - repo-level overview
- [`../proleague_scraper/README.md`](../proleague_scraper/README.md) - scheduler and internal HTTP layer
- [`../frontend_app/README.md`](../frontend_app/README.md) - host-facing API that reads `player_stats`
- [`../../docker/README.md`](../../docker/README.md) - Compose services and operator commands
- [`../../specs/005-compose-kafka-pipeline/quickstart.md`](../../specs/005-compose-kafka-pipeline/quickstart.md) - full stack quickstart
