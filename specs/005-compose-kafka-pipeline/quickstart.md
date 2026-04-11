# Quickstart: local Compose pipeline (005)

Prerequisites: **Docker** + **Docker Compose**, **Python 3.12+**, **UV**.

## 1. Configure environment

```bash
cp .env.example .env
```

Edit `.env`: set **strong** values for `POSTGRES_PASSWORD`, `PGADMIN_DEFAULT_PASSWORD`, and align `DATABASE_URL` with `POSTGRES_USER` / `POSTGRES_PASSWORD` / `POSTGRES_DB`. If **port 5432**, **9092**, or **5050** is already taken on your machine, set `POSTGRES_PORT`, or change the Kafka/pgAdmin host mappings in `docker-compose.yml` / env as needed (**FR-014**).

**Topic and partitions (FR-013)**: The fan-events topic is **auto-created on the first produce**. New topics use the broker’s **`KAFKA_NUM_PARTITIONS`** (default **3** in `docker-compose.yml`). Match `KAFKA_TOPIC` / `FAN_EVENTS_KAFKA_TOPIC` / producer flags to the same name (e.g. `fan_events`).

## 2. Start the stack

```bash
docker compose up -d
```

Wait until **Postgres** is healthy (`docker compose ps`) and the **broker** is up. The **ingest** service consumes from `KAFKA_BOOTSTRAP_SERVERS` (**`broker:29092`** — INTERNAL listener; do not use `localhost` inside containers).

## 3. Run the producer on the host (**FR-015**)

```bash
uv sync --extra kafka
uv run fan_events stream --kafka-topic fan_events --kafka-bootstrap-servers localhost:9092 --max-events 100
```

Or set env (PowerShell example):

```powershell
$env:FAN_EVENTS_KAFKA_BOOTSTRAP_SERVERS = "localhost:9092"
$env:FAN_EVENTS_KAFKA_TOPIC = "fan_events"
uv run fan_events stream --kafka-topic fan_events --max-events 100
```

Use **`localhost:9092`** on the host (EXTERNAL advertised listener). Inside Compose, services use **`broker:29092`**.

## 4. Verify

- **Postgres**: `SELECT count(*) FROM fan_events_ingested;`  
  - **pgAdmin**: open `http://localhost:5050` (or `PGADMIN_PORT`), log in with `PGADMIN_DEFAULT_EMAIL` / `PGADMIN_DEFAULT_PASSWORD`. A server **Fan pipeline (postgres)** should be pre-registered; use **Postgres** password from `.env` when prompted if the UI asks.  
  - **Host `psql`**: `psql "postgresql://USER:PASS@localhost:POSTGRES_PORT/POSTGRES_DB"` using values from `.env`.
- **Logs**: `docker compose logs -f ingest` — parse failures log `ingest_parse_skip` with topic/partition/offset; DB errors log `ingest_db_error` with the same coordinates (**SC-003**).

## 5. Durability check (**SC-002**)

**Important**: `docker compose down` **without** `-v` keeps the **`postgres-data`** (and **`kafka-data`**) named volumes. **`docker compose down -v`** removes volumes and **wipes** database (and broker) data.

Checklist:

1. Ingest **at least 50** events (e.g. increase `--max-events`).
2. Note `SELECT count(*) FROM fan_events_ingested;`.
3. Run `docker compose down` (**no** `-v`).
4. Run `docker compose up -d`.
5. Re-run the same `count` query — the row count must be **unchanged** (100% of prior rows retained for the same offsets).

## 6. Concurrency (**SC-004**)

The broker uses **multiple partitions** (default 3). The ingest service runs **one asyncio consumer task per partition**, so inserts can **overlap** across partitions. To observe overlap, produce **≥30** messages within **~60** seconds and inspect `docker compose logs ingest` for interleaved work (timestamps across partitions).

## Failure and retry behavior

- **Invalid JSON / non-object payload**: No row is written; the consumer **logs** a warning and **commits** the offset so consumption advances (no silent stall) (**FR-012**).
- **Database insert failure**: Logged with topic/partition/offset; the worker **re-raises** and the process **exits** non-zero after logging (local demo: fix DB and restart; no unbounded silent retry in v1).

## Troubleshooting

| Issue | Hint |
|-------|------|
| Producer cannot connect | Bootstrap must be **`localhost:9092`** from the host; ensure the stack is up and **9092** is free. |
| Ingest cannot connect | From containers use **`broker:29092`**, not `localhost:9092`. |
| Port already allocated | Change **`POSTGRES_PORT`** in `.env` or adjust published ports in `docker-compose.yml`. |
| pgAdmin server login | Username in `servers.json` is **`postgres`**; it must match **`POSTGRES_USER`** in `.env`. |

## Acceptance (manual)

1. **Compose + host producer**: Stack up, run producer, rows appear in `fan_events_ingested`.
2. **SC-002**: Volume-preserving restart (section 5): count stable after `down` without `-v`.
3. **SC-003**: Produce **100** valid messages; scan `docker compose logs ingest` — no unexplained write errors for acknowledged processing paths.
4. **SC-004**: Produce **≥30** messages quickly; logs show concurrent handling across partitions (section 6).
5. **SC-001** (optional): First-time setup within **30** minutes on a clean machine with prerequisites installed.

## Optional: all-in-Compose producer (secondary)

Not required for v1 (**FR-015**). If added later: a service would use `FAN_EVENTS_KAFKA_BOOTSTRAP_SERVERS=broker:29092` and a project image; keep it out of the primary path above.
