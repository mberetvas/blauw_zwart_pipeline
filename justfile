# ── Defaults (override on CLI: just stream seed=99 max=100) ──────────
calendar        := "match_day.example.json"
seed            := "42"
max             := "500"
retail_max      := "2000"
# Wall-clock delay between emitted lines (seconds). Both are required by fan_events; use 0 and 0 to disable.
emit_min        := "1"
emit_max        := "3"
# Calendar-loop shift in days (default: 365 = replay season one year later)
loop_shift_days := "365"

# ── Help / discovery ────────────────────────────────────────────────
# Show top-level CLI help
help:
    uv run fan_events --help

# Show stream subcommand help
stream-help:
    uv run fan_events stream --help

# Show generate_events subcommand help
generate-help:
    uv run fan_events generate_events --help

# Show generate_retail subcommand help
retail-help:
    uv run fan_events generate_retail --help

# ── Linting ─────────────────────────────────────────────────────────
# Run Ruff lint checks
ruff-check:
    uv run ruff check .

# Run Ruff lint checks and auto-fix issues where possible
ruff-fix:
    uv run ruff check . --fix

# ── Stream (merged v2 + v3 to stdout) ──────────────────────────────
# Quickstart stream: calendar + retail merged to stdout (matches quickstart.md)
stream:
    uv run fan_events stream \
        --calendar {{ calendar }} \
        -s {{ seed }} \
        --retail-max-events {{ retail_max }} \
        --max-events {{ max }}

# Calendar-only stream (no retail lines)
stream-calendar:
    uv run fan_events stream \
        --calendar {{ calendar }} \
        --no-retail \
        -s {{ seed }} \
        --max-events {{ max }}

# Continuous calendar loop to stdout — replays the season indefinitely, shifting each cycle
# forward by loop_shift_days (default: 365). Stops on Ctrl+C or when --max-events is reached.
# Override defaults e.g.: just stream-loop seed=7 emit_min=0.1 emit_max=0.5 loop_shift_days=7
stream-loop:
    uv run fan_events stream \
        --calendar {{ calendar }} \
        --no-retail \
        -s {{ seed }} \
        --calendar-loop \
        --calendar-loop-shift {{ loop_shift_days }} \
        --emit-wall-clock-min {{ emit_min }} \
        --emit-wall-clock-max {{ emit_max }}

# Continuous calendar loop merged with retail — runs forever (Ctrl+C to stop)
stream-loop-merged:
    uv run fan_events stream \
        --calendar {{ calendar }} \
        -s {{ seed }} \
        --calendar-loop \
        --calendar-loop-shift {{ loop_shift_days }} \
        --retail-max-events {{ retail_max }} \
        --emit-wall-clock-min {{ emit_min }} \
        --emit-wall-clock-max {{ emit_max }}

# Retail-only stream (no calendar/v2 lines)
stream-retail:
    uv run fan_events stream \
        -s {{ seed }} \
        --retail-max-events {{ retail_max }} \
        --max-events {{ max }}

# Stream to an NDJSON file (append-only)
stream-file out="out/mixed.ndjson":
    uv run fan_events stream \
        --calendar {{ calendar }} \
        -s {{ seed }} \
        --retail-max-events {{ retail_max }} \
        --max-events {{ max }} \
        -o {{ out }}

# ── Kafka ───────────────────────────────────────────────────────────
# Run Kafka via Docker Compose (broker on localhost:9092; data persisted in volume kafka-data)
compose-up:
    docker compose up -d

# Stop Kafka Compose stack (volume kafka-data is kept; use `docker compose down -v` to wipe data)
compose-down:
    docker compose down

# Stop Kafka Compose stack and remove volumes, images, and orphans
compose-down-clean:
    docker compose down -v --rmi all --remove-orphans

# Create Kafka topic fan_events (requires: just kafka-up; uses single replica to match local broker)
# Use //opt/... so Git Bash on Windows does not rewrite /opt to Git's install directory before docker exec.
kafka-create-topic topic="fan_events":
    docker compose exec broker //opt/kafka/bin/kafka-topics.sh --bootstrap-server localhost:9092 --create --if-not-exists --topic {{ topic }} --partitions 3 --replication-factor 1

# Show Kafka broker container logs (default last 200 lines; e.g. just kafka-logs tail=500)
kafka-logs tail="200":
    docker compose logs --tail {{ tail }} broker

# Stream Kafka broker logs until Ctrl+C
kafka-logs-follow:
    docker compose logs -f broker

# Stream to a local Kafka topic (requires: uv sync --extra kafka && just kafka)
stream-kafka topic="fan_events":
    uv run fan_events stream \
        --calendar {{ calendar }} \
        -s {{ seed }} \
        --retail-max-events {{ retail_max }} \
        --max-events {{ max }} \
        --kafka-topic {{ topic }} \
        --kafka-bootstrap-servers localhost:9092

# Same as stream-kafka but no --max-events (stops when iterators end, or Ctrl+C).
# Random sleep between lines: uniform(emit_min, emit_max) seconds — override e.g. emit_min=0.001 emit_max=2.5
stream-kafka-live topic="fan_events":
    uv run fan_events stream \
        --calendar {{ calendar }} \
        -s {{ seed }} \
        --retail-max-events {{ retail_max }} \
        --emit-wall-clock-min {{ emit_min }} \
        --emit-wall-clock-max {{ emit_max }} \
        --kafka-topic {{ topic }} \
        --kafka-bootstrap-servers localhost:9092

# Consume from Kafka topic fan_events and print each message to stdout (Ctrl+C to stop)
kafka-consume topic="fan_events":
    uv run python scripts/kafka_consume_fan_events.py --topic {{ topic }}

# ── Postgres helpers ───────────────────────────────────────────────
# Grant llm_reader SELECT on raw_data.player_stats.
# Run once after `docker compose up -d` when the postgres-data volume pre-dates
# 003_player_stats.sql (init scripts only execute on a fresh/empty volume).
# NOTE: The raw_data schema and player_stats table are created by `proleague-scraper`
# at startup via ensure_player_stats_table(). That service must have run at least once
# before this recipe will succeed.
# Safe to re-run — GRANT is idempotent.
db-grant-player-stats:
    docker compose exec postgres psql -U postgres -d fan_pipeline -c "GRANT USAGE ON SCHEMA raw_data TO llm_reader; GRANT SELECT ON raw_data.player_stats TO llm_reader;"

# ── Batch generators ───────────────────────────────────────────────
# Generate v1 rolling-window batch
generate-events:
    uv run fan_events generate_events -s {{ seed }} -o out/fan_events.ndjson

# Generate v2 calendar batch
generate-calendar:
    uv run fan_events generate_events \
        -c {{ calendar }} \
        -s {{ seed }} \
        -o out/v2.ndjson

# Generate v3 retail batch
generate-retail:
    uv run fan_events generate_retail -s {{ seed }} -o out/retail.ndjson
