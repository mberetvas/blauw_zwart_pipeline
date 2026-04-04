# Quickstart: Calendar-driven synthetic fan events (002)

**Spec**: [`spec.md`](spec.md)  
**Contract**: [`contracts/fan-events-ndjson-v2.md`](contracts/fan-events-ndjson-v2.md)  
**Data model**: [`data-model.md`](data-model.md)

## Prerequisites

- Python **3.12+** (see `pyproject.toml`)
- [UV](https://github.com/astral-sh/uv) for locked env (`uv sync`, `uv run pytest`, `uv run python …`)
- Runtime dependency **`tzdata`** (via `pyproject.toml`) so `zoneinfo` can resolve IANA zones such as **`Europe/Brussels`** on all platforms (including Windows).

## Capacity & timezone assumptions

- **Jan Breydel** maximum home attendance: **29,062** spectators (named constant in contract and code; invalid calendar rows must fail validation).
- Calendar **`kickoff_local`** values use the IANA **`timezone`** on each row (e.g. **`Europe/Brussels`**); all emitted event **`timestamp`** values are **UTC** with a **`Z`** suffix.
- Default **match-day window**: **T−120 minutes** to **T+90 minutes** relative to kickoff (UTC), unless overridden per row in the calendar (see `data-model.md`).

## Example calendar

- [`fixtures/calendar_example.json`](fixtures/calendar_example.json) — full example rows  
- [`../../tests/fixtures/calendar_two_tiny.json`](../../tests/fixtures/calendar_two_tiny.json) — small fixture used in tests (fast iteration)

## End-to-end: small calendar → one season NDJSON file

From the **repository root** after `uv sync`:

```bash
uv run python scripts/generate_fan_events.py \
  --calendar tests/fixtures/calendar_two_tiny.json \
  --from-date 2026-01-01 \
  --to-date 2027-12-31 \
  --seed 42 \
  --output out/season.ndjson
```

This produces **`fan-events-ndjson-v2`** output (every line includes **`match_id`**). **`--days`** and **`--count`** are **only** for rolling **v1** mode and must not be combined with **`--calendar`**.

- **`--calendar`**: enables **v2** calendar mode.
- **`--from-date` / `--to-date`**: inclusive filter on **kickoff UTC** calendar dates (`YYYY-MM-DD`).
- **`--seed`**: optional; same seed + same inputs ⇒ byte-identical output (recommended for demos and CI).

Optional tuning (defaults match `fan_events.domain`):

- `--scan-fraction` — scales **`ticket_scan`** event count vs effective capacity.
- `--merch-factor` — scales **`merch_purchase`** event count vs effective capacity.
- `--events` — `both` | `ticket_scan` | `merch_purchase`.

## Rolling-window generator (v1)

```bash
uv run python scripts/generate_fan_events.py --seed 1 -n 200 --days 90 -o out/fan_events.ndjson
```

Output follows **`fan-events-ndjson-v1`** (no **`match_id`**).

## Validate

From the repository root:

```bash
uv run pytest
uv run ruff check .
```

## Related

- Rolling-window generator (v1): [`../001-synthetic-fan-events/quickstart.md`](../001-synthetic-fan-events/quickstart.md)
