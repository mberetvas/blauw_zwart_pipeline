# ── Defaults (override on CLI: just stream seed=99 max=100) ──────────
calendar   := "match_day.example.json"
seed       := "42"
max        := "500"
retail_max := "2000"

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
# Run Kafka in Docker (broker on localhost:9092)
kafka:
    docker run --rm -d -p 9092:9092 apache/kafka:4.1.2

# Stream to a local Kafka topic (requires: uv sync --extra kafka && just kafka)
stream-kafka topic="fan-events":
    uv run fan_events stream \
        --calendar {{ calendar }} \
        -s {{ seed }} \
        --retail-max-events {{ retail_max }} \
        --max-events {{ max }} \
        --kafka-topic {{ topic }} \
        --kafka-bootstrap-servers localhost:9092

# Same as stream-kafka but no --max-events (stops when iterators end, or Ctrl+C)
stream-kafka-live topic="fan-events":
    uv run fan_events stream \
        --calendar {{ calendar }} \
        -s {{ seed }} \
        --retail-max-events {{ retail_max }} \
        --kafka-topic {{ topic }} \
        --kafka-bootstrap-servers localhost:9092

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
