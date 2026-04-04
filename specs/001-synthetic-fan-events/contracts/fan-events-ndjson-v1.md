# Contract: Fan events NDJSON v1

**Version**: 1.0  
**Feature**: `001-synthetic-fan-events`  
**Status**: Normative for generator output

## File format

- **Encoding**: UTF-8 (no BOM).
- **Line endings**: `\n` (LF) between records; generator SHOULD use `\n` only so byte reproducibility
  holds across platforms when the same Python version runs the script.
- **Trailing newline**: A successful file MUST end with **exactly one** `\n` after the last JSON line
  (POSIX text file). Empty files (zero events) MUST contain **no** bytes. This rule is **normative** for
  byte-identical reproducibility (FR-005).
- **One record**: Exactly one JSON object per non-empty line; no pretty-printed multi-line objects.

## Canonical JSON serialization

Implementations claiming byte-identical output MUST serialize each object with:

- `sort_keys=True`
- `separators=(",", ":")`
- `ensure_ascii=False`

Numbers MUST not use locale-specific formatting. `amount` MUST represent a positive EUR value **quantized
to cent precision** (0.01); the reference script uses values that round-trip as floats without spurious
precision beyond cents.

## Event discriminator

Property **`event`** (string) MUST be either `ticket_scan` or `merch_purchase`. No other values in v1.

## Record shapes

### `ticket_scan`

Required properties: `amount` and `item` MUST NOT appear.

| Property | Type | Constraints |
|----------|------|-------------|
| `event` | string | `ticket_scan` |
| `fan_id` | string | non-empty |
| `location` | string | non-empty |
| `timestamp` | string | UTC, ISO-8601, `Z` offset only (e.g. `2026-01-15T14:30:00Z`) |

### `merch_purchase`

Required properties: `location` MUST NOT appear.

| Property | Type | Constraints |
|----------|------|-------------|
| `event` | string | `merch_purchase` |
| `fan_id` | string | non-empty |
| `item` | string | non-empty |
| `amount` | number | `> 0`, EUR for demo |
| `timestamp` | string | UTC, ISO-8601, `Z` |

## Ordering (FR-007)

Sort keys for the **entire file** before writing:

1. `timestamp` ascending (ISO strings sort lexicographically in UTC `Z` form).
2. `event` ascending in **enum order**: `ticket_scan`, then `merch_purchase`.
3. `fan_id` ascending (lexical Unicode).
4. If still tied: for `ticket_scan`, `location` ascending; for `merch_purchase`, `item` ascending then
   `amount` ascending.

## CLI surface (reference)

Documented for operators and CI; exact flag names MAY be adjusted in code if quickstart stays in sync.

| Flag | Meaning | Default |
|------|---------|---------|
| `--output` / `-o` | Output file path | `out/fan_events.ndjson` |
| `--count` / `-n` | Total events to emit | `200` |
| `--days` | Rolling window length (UTC) ending at generation “now” | `90` |
| `--seed` | RNG seed for reproducibility | omitted → non-deterministic run |
| `--events` | `both` \| `ticket_scan` \| `merch_purchase` | `both` |

## Failure semantics

Any contract violation or I/O error: **non-zero exit**, **no durable complete output file** at the
target path (atomic write discipline).

## Downstream

Raw lines are intended for append-only ingest. Target dbt facts: **`fct_ticket_scans`**,
**`fct_merch_purchases`** (names may be adjusted in dbt project when added).
