# Data model: Synthetic fan events (logical)

**Feature**: `001-synthetic-fan-events`  
**Encoding**: UTF-8 NDJSON, one JSON object per line (see [contracts/fan-events-ndjson-v1.md](./contracts/fan-events-ndjson-v1.md)).

## Fan (synthetic)

| Field | Description |
|-------|-------------|
| `fan_id` | Stable opaque string identifier for the synthetic person (e.g. `fan_00042`). |

**Rules**: Appears on every event line; no PII; values drawn from a bounded generator pool for demo scale.

## Event: `ticket_scan`

| Field | Type | Required |
|-------|------|----------|
| `event` | string, literal `ticket_scan` | yes |
| `fan_id` | string | yes |
| `location` | string (venue / gate / stand — demo vocabulary) | yes |
| `timestamp` | string, UTC ISO-8601 with `Z` suffix | yes |

**Rules**: No `item` or `amount` on this record shape.

## Event: `merch_purchase`

| Field | Type | Required |
|-------|------|----------|
| `event` | string, literal `merch_purchase` | yes |
| `fan_id` | string | yes |
| `item` | string | yes |
| `amount` | number, **strictly > 0**, demo currency EUR, two decimal places in canonical form | yes |
| `timestamp` | string, UTC ISO-8601 with `Z` suffix | yes |

**Rules**: No `location` on this record shape. Invalid amounts must abort the run (spec FR-008).

## Event batch (file)

- Ordered **non-decreasing** by `timestamp`, with tie order defined in the contract.
- Line count equals successful event count; no trailing partial line.
- **Downstream mapping** (not implemented in this feature): append-only raw landing → dbt staging →
  **`fct_ticket_scans`**, **`fct_merch_purchases`**.

## Validation summary

| Rule | Where enforced |
|------|----------------|
| Required fields per `event` | Generator before write; contract for reviewers |
| `amount > 0` | Generator |
| UTF-8, one JSON object per line | Generator serialization |
| Global sort + tie-break | Generator before serialization |
| Fail-fast on any violation | Generator; no durable output file |
