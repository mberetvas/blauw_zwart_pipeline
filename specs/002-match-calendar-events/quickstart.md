# Quickstart: Calendar-driven synthetic fan events (002)

**Spec**: [`spec.md`](spec.md)  
**Contract**: [`contracts/fan-events-ndjson-v2.md`](contracts/fan-events-ndjson-v2.md)  
**Data model**: [`data-model.md`](data-model.md)

## Prerequisites

- Python **3.12+** (see `pyproject.toml`)
- [UV](https://github.com/astral-sh/uv) for locked dev env (`uv run pytest`, `uv run python …`)

## Capacity & timezone assumptions

- **Jan Breydel** maximum home attendance: **29,062** spectators (named constant in contract and code; invalid calendar rows must fail validation).
- Calendar **`kickoff_local`** values use the IANA **`timezone`** on each row (e.g. **`Europe/Brussels`**); all emitted event **`timestamp`** values are **UTC** with a **`Z`** suffix.
- Default **match-day window**: **T−120 minutes** to **T+90 minutes** relative to kickoff (UTC), unless overridden per row in the calendar (see `data-model.md`).

## Example calendar

See [`fixtures/calendar_example.json`](fixtures/calendar_example.json).

## Generate one season segment (after implementation)

From the repository root (commands illustrative until implementation lands):

```bash
uv run python scripts/generate_fan_events.py --calendar specs/002-match-calendar-events/fixtures/calendar_example.json --from-date 2026-08-01 --to-date 2027-06-30 --output out/season.ndjson --seed 42
```

- **`--calendar`**: enables **v2** calendar mode (NDJSON per `fan-events-ndjson-v2.md`).
- **`--days` / `--count`**: **not** used in calendar mode (rolling **v1** mode only).

## Validate

```bash
uv run pytest
```

Contract tests should assert NDJSON shape, **global sort order**, UTF-8 encoding, and **byte-identical** output for fixed seed + fixture.

## Related

- Rolling-window generator (v1): [`../001-synthetic-fan-events/quickstart.md`](../001-synthetic-fan-events/quickstart.md)
