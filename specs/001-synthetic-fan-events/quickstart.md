# Quickstart: Synthetic fan events

**Feature**: `001-synthetic-fan-events`  
**Script**: `scripts/generate_fan_events.py` (to be implemented per [plan.md](./plan.md))

## Prerequisites

- Python **3.12+**
- Repository root as current working directory

## Generate a default file

```bash
python scripts/generate_fan_events.py
```

Creates **`out/fan_events.ndjson`** (directories created if needed).

## Reproducibility check

```bash
python scripts/generate_fan_events.py -o out/run1.ndjson --seed 42 -n 100
python scripts/generate_fan_events.py -o out/run2.ndjson --seed 42 -n 100
```

Then compare files byte-for-byte (e.g. PowerShell):

```powershell
fc /B out\run1.ndjson out\run2.ndjson
```

Expect **no differences**.

## Common options

| Goal | Example |
|------|---------|
| Custom size | `python scripts/generate_fan_events.py -n 500` |
| Custom window | `python scripts/generate_fan_events.py --days 30` |
| One event type | `python scripts/generate_fan_events.py --events ticket_scan` |

## Contract

Normative rules: [contracts/fan-events-ndjson-v1.md](./contracts/fan-events-ndjson-v1.md)

## Next pipeline step

Load NDJSON into raw storage, then model **`fct_ticket_scans`** and **`fct_merch_purchases`** in dbt
(future work).
