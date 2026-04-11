# Quickstart: local Compose pipeline (005)

Prerequisites: **Docker** + **Docker Compose**.

## 1. Configure environment

```bash
cp .env.example .env
```

Edit `.env`: set **strong** values for `POSTGRES_PASSWORD`, `PGADMIN_DEFAULT_PASSWORD`, and align `DATABASE_URL` with `POSTGRES_USER` / `POSTGRES_PASSWORD` / `POSTGRES_DB`. If **port 5432**, **9092**, or **5050** is already taken on your machine, set `POSTGRES_PORT`, or change the Kafka/pgAdmin host mappings in `docker-compose.yml` / env as needed (**FR-014**). The bundled Compose producer reuses `KAFKA_BOOTSTRAP_SERVERS=broker:29092` and `KAFKA_TOPIC`, plus the `FAN_EVENTS_STREAM_*` pacing/seed defaults from `.env`.

**Topic and partitions (FR-013)**: The fan-events topic is **auto-created on the first produce**. New topics use the broker’s **`KAFKA_NUM_PARTITIONS`** (default **3** in `docker-compose.yml`). Match `KAFKA_TOPIC` / `FAN_EVENTS_KAFKA_TOPIC` / producer flags to the same name (e.g. `fan_events`).

## 2. Start the stack

```bash
docker compose up -d
```

Wait until **Postgres** and **broker** are healthy (`docker compose ps`). The **producer** and **ingest** services both wait for those dependencies before starting. Inside Compose, both services use the Kafka **INTERNAL** listener (`broker:29092`); `localhost:9092` remains only for optional host-side clients.

## 3. Verify messages are flowing

```bash
docker compose logs -f producer ingest
```

You should see the producer enter Kafka mode and the ingest service start consuming from the same topic.

To confirm the topic exists and has traffic, inspect it from the broker container (replace `fan_events` if you changed `KAFKA_TOPIC`):

```bash
docker compose exec broker /opt/kafka/bin/kafka-console-consumer.sh --bootstrap-server localhost:9092 --topic fan_events --from-beginning --max-messages 3
```

## 4. Verify rows in Postgres

Using the database container:

```bash
docker compose exec postgres sh -lc 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "SELECT count(*) FROM fan_events_ingested;"'
```

Or via pgAdmin:

1. Open `http://localhost:5050` (or `PGADMIN_PORT`).
2. Sign in with `PGADMIN_DEFAULT_EMAIL` / `PGADMIN_DEFAULT_PASSWORD`.
3. Open the pre-registered server and run `SELECT count(*) FROM fan_events_ingested;`.

Host access still works if you prefer a host client:

```powershell
$env:PGPASSWORD = "<POSTGRES_PASSWORD_FROM_.env>"
psql "postgresql://<POSTGRES_USER>:$env:PGPASSWORD@localhost:<POSTGRES_PORT>/<POSTGRES_DB>" -c "SELECT count(*) FROM fan_events_ingested;"
```

For an extra producer on the host, use **`localhost:9092`** (EXTERNAL listener). Inside Compose, services always use **`broker:29092`**.

## 5. Durability check (**SC-002**)

**Important**: `docker compose down` **without** `-v` keeps the **`postgres-data`** (and **`kafka-data`**) named volumes. **`docker compose down -v`** removes volumes and **wipes** database (and broker) data.

Checklist:

1. Let the stack ingest for a short while and note `SELECT count(*) FROM fan_events_ingested;`.
2. Run `docker compose down` (**no** `-v`).
3. Run `docker compose up -d`.
4. Re-run the same `count` query after services are healthy.
5. The new count should be **greater than or equal to** the pre-restart count: previous rows are retained, and the restarted producer may already have added more.

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

1. **Compose-managed flow**: Stack up, producer starts automatically, rows appear in `fan_events_ingested`.
2. **SC-002**: Volume-preserving restart (section 5): existing rows survive `down` without `-v`.
3. **SC-003**: Produce **100** valid messages; scan `docker compose logs ingest` — no unexplained write errors for acknowledged processing paths.
4. **SC-004**: Produce **≥30** messages quickly; logs show concurrent handling across partitions (section 6).
5. **SC-001** (optional): First-time setup within **30** minutes on a clean machine with prerequisites installed.
