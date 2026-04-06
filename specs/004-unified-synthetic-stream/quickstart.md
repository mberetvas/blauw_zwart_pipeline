# Quickstart: `fan_events stream`

**Prerequisites**: Python **3.12+**, `uv` (see repository README). Run from repo root: `uv run fan_events …`.

## Stream to stdout (merged v2 + v3)

```bash
uv run fan_events stream --calendar specs/002-match-calendar-events/examples/minimal_calendar.json \
  -s 42 --retail-max-events 2000 --max-events 500
```

`--retail-max-events` / `--retail-max-duration` cap the **retail** iterator before merge. **`--max-events`** / **`--max-duration`** cap the **merged** line stream after interleaving.

## Append to a file (append-only)

```bash
uv run fan_events stream --calendar my_calendar.json -s 42 -o out/mixed.ndjson --max-events 10000
```

Omit **`-o`** or use **`-o -`** for stdout.

## Calendar-only or retail-only

```bash
uv run fan_events stream --calendar my_calendar.json --no-retail -s 42 --max-events 100
uv run fan_events stream -s 1 --retail-max-events 50 --max-events 50
```

## Native Kafka output (optional `[kafka]` extra)

Install the optional extra and set the broker/topic via environment variables:

```bash
pip install 'blauw-zwart-fan-sim-pipeline[kafka]'
export FAN_EVENTS_KAFKA_BOOTSTRAP_SERVERS=localhost:9092
```

Publish directly to a Kafka topic:

```bash
uv run fan_events stream --calendar my_calendar.json -s 42 --max-events 1000 --kafka-topic fan-events
```

Or activate Kafka mode via env var alone (no `--kafka-topic` flag required):

```bash
export FAN_EVENTS_KAFKA_TOPIC=fan-events
uv run fan_events stream --calendar my_calendar.json -s 42 --max-events 1000
```

`--kafka-topic` and `-o / --output` are mutually exclusive. TLS/SASL settings are env-only (`FAN_EVENTS_KAFKA_*`) to keep secrets out of shell history.

## Pipe to **kcat** (alternative — no extra required)

As an alternative to the built-in Kafka sink, pipe stdout to `kcat` (operator configures brokers via `kcat` env/flags):

```bash
uv run fan_events stream --calendar my_calendar.json -s 42 --max-events 1000 | kcat -P -b localhost:9092 -t fan-events
```

Replace broker/topic with your environment. **Unbounded** runs can fill disks or overload brokers — use **`--max-events`** / **`--max-duration`** for demos.

## Unbounded runs

If **no** `--max-events` and **no** `--max-duration`, the process may run until **Ctrl+C** (see spec FR-008). Prefer explicit limits for CI and load tests.

## Reproducibility

Use the same **`--seed`**, calendar file, and flags for **byte-identical** output (where generators are deterministic).
