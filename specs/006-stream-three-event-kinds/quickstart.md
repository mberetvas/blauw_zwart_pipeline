# Quickstart — Feature 006 (`fan_events stream`)

**Contracts**: [contracts/](./contracts/) · **Spec**: [spec.md](./spec.md)

**How to run (at a glance):** **`docker compose up -d`** runs the full MVP. The commands below use **`uv run python -m fan_events stream …`** for the **synthetic CLI** on the host. **`uv run pytest`** / **`uv run ruff`** at the end are **development / CI** only.

## Prerequisites

- Python **3.12+**, **uv** (CLI examples: `uv run python -m fan_events …` from repo root).
- Example calendar (e.g. `match_day.example.json` or repo calendars under `calendars/`).

## Merged stream (v2 + v3), continuous seasons (after 006 implementation)

```bash
cd /path/to/blauw_zwart_fan_sim_pipeline
uv run python -m fan_events stream --calendar calendars/match_day.example.json --seed 42 --max-events 500
```

- **`--max-events` / `--max-duration`**: optional **post-merge** caps (global across season passes per **006**).
- **Match-day retail tuning** (once implemented — see [cli-match-day-flags-006.md](./contracts/cli-match-day-flags-006.md)):

```bash
uv run python -m fan_events stream -c calendars/match_day.example.json --seed 1 \
  --retail-home-match-day-multiplier 2.5 \
  --retail-home-kickoff-pre-minutes 90 \
  --retail-home-kickoff-post-minutes 120 \
  --retail-home-kickoff-extra-multiplier 1.5 \
  --max-events 2000
```

- **Away match-day boost** (optional):

```bash
uv run python -m fan_events stream -c calendars/match_day.example.json --seed 2 \
  --retail-away-match-day-enable \
  --retail-away-match-day-multiplier 2.0 \
  --max-events 1000
```

## Output sinks

- **Stdout** (default): omit `-o` or use `-o -`.
- **Append file**: `-o path/to/out.ndjson`.
- **Kafka** (optional extra): same flags as **004** (`--kafka-topic`, env vars — see `cli.py` / **004** docs).

## Interrupt

**Ctrl+C** exits with code **130**; each line is written **atomically** (`write` + `flush`) so consumers should not see torn JSON lines.

## Tests (for implementers)

```bash
uv run pytest
uv run ruff check src tests
```
