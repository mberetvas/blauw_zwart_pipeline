# Quickstart: Synthetic fan events

**Feature**: `001-synthetic-fan-events`  
**Script**: `scripts/generate_fan_events.py`

## Prerequisites

- Python **3.12+**
- Repository root as current working directory

## Generate a default file

```bash
python scripts/generate_fan_events.py
```

Creates **`out/fan_events.ndjson`** (directories created if needed). Defaults: **200** events, **90** day
UTC window, **`--events both`**.

## Reproducibility check

With **`--seed`**, the generator uses a **fixed UTC “now”** (`2026-04-01T15:00:00Z`) for the time window
so two runs with the same seed and flags stay **byte-identical**. Without `--seed`, “now” is the real
clock and outputs differ run-to-run.

```bash
python scripts/generate_fan_events.py -o out/run1.ndjson --seed 42 -n 100
python scripts/generate_fan_events.py -o out/run2.ndjson --seed 42 -n 100
```

Compare byte-for-byte on Windows (use **`fc.exe`** so PowerShell does not treat `fc` as an alias):

```powershell
fc.exe /B out\run1.ndjson out\run2.ndjson
```

Expect **FC: no differences encountered**.

## Common options

| Goal | Example |
|------|---------|
| Custom size | `python scripts/generate_fan_events.py -n 500` |
| Custom window | `python scripts/generate_fan_events.py --days 30` |
| One event type | `python scripts/generate_fan_events.py --events ticket_scan` |
| Custom output | `python scripts/generate_fan_events.py -o data/raw/events.ndjson` |

## Contract

Normative rules: [contracts/fan-events-ndjson-v1.md](./contracts/fan-events-ndjson-v1.md)

## Next pipeline step

Load NDJSON into raw storage, then model **`fct_ticket_scans`** and **`fct_merch_purchases`** in dbt
(future work).
