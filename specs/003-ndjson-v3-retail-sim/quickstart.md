# Quickstart: NDJSON v3 retail generation (003)

**Contract**: [`contracts/fan-events-ndjson-v3.md`](contracts/fan-events-ndjson-v3.md)  
**Spec**: [`spec.md`](spec.md)

## Prerequisites

- Python **3.12+** (see `pyproject.toml`)
- UV: `uv run pytest` / `uv run python -m fan_events …`

## Run

### File mode (batch, globally sorted NDJSON)

```bash
uv run python -m fan_events generate_retail -o out/retail.ndjson --seed 42
```

### Stream mode (stdout, generation order, byte-identical with same seed)

```bash
uv run python -m fan_events generate_retail --stream --seed 42 --max-events 100
```

### Mutual exclusion (same idea as v1 vs v2)

- Do **not** combine **`generate_retail`** with **`generate_events`** flags for **rolling** (`-n`, `--days`) or **calendar** (`--calendar`, `--from-date`, …).
- Use **one** generation mode per invocation.

## Parameters (reference)

| Concept | Role |
|---------|------|
| `--seed` | Deterministic RNG; batch + stream byte identity per spec |
| `--epoch` | Defaults to **`2026-01-01T00:00:00Z`**; override for shifted timelines |
| `--shop-weights W1 W2 W3` | Default **equal thirds**; explicit weights must match three shops |
| `--arrival-mode` | `poisson` (default), `fixed`, or `weighted_gap` (see `--help`) |
| `--max-events` / `--max-duration` | If both set, generation stops when **either** bound is hit first |

## Validate

```bash
uv run pytest
```

Include tests for **`validate_record_v3`**, **`sort_key_v3`**, and golden **batch** output when **`--seed`** is fixed.
