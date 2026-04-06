# Data model: `fan_events stream` (004)

## Purpose

Describe runtime entities for the unified NDJSON orchestrator — **not** new warehouse tables.

## Entities

### `StreamConfig` (conceptual)

| Field | Description |
|-------|-------------|
| `calendar_path` | Optional path to calendar JSON; if absent, **no** v2 events. |
| `from_date` / `to_date` | Optional UTC date bounds (same semantics as `generate_events --calendar`). |
| `scan_fraction` / `merch_factor` | v2 volume parameters (defaults as today). |
| `events_mode` | `both` / `ticket_scan` / `merch_purchase`. |
| `retail_kwargs` | Dict aligned with **`_retail_generator_kwargs`** (`epoch`, arrival, caps, `fan_pool`, …). |
| `seed` | Optional global RNG seed (v2 + retail + pacing). |
| `fan_pool` | Unified upper bound for `fan_id` numeric suffix when both sources active (see FR-012). |
| `max_events` | Optional cap on **emitted** lines after merge. |
| `max_simulated_duration_seconds` | Optional cap on synthetic timeline (see `research.md`). |
| `emit_wall_clock_min` / `max` | Optional pacing between **merged** lines. |
| `output` | `-` or `None` → stdout; else **append** path. |

### `MergedRecord` (conceptual)

In-memory representation is a **dict** matching **v2 or v3** contract (`validate_record_v2` / `validate_record_v3`).

### Merge key (total order)

Aligned with [`contracts/orchestrated-stream.md`](./contracts/orchestrated-stream.md):

1. Parse `timestamp` → UTC `datetime` for comparison.
2. **`event`** string (lexicographic).
3. **`dumps_canonical(rec)`** UTF-8 bytes lexicographic (same as K3).

### State

- **Orchestrator** holds: RNG(s), optional **pacing** RNG, iterators, **emitted count**, **deadline** for simulated duration.
- **No** persistent DB state.

## Validation rules

- Each emitted line: **v2** validator for match events; **v3** validator for `retail_purchase`.
- **Ordering**: consecutive lines must satisfy merge key **non-decreasing** (strict total order via K3).

## Relationships

- **Calendar JSON** → `MatchContext[]` (existing `v2_calendar`).
- **Retail** → `iter_retail_records` (existing `v3_retail`).
