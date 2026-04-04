# Contract: Fan events NDJSON v2 (calendar-driven)

**Version**: 2.0  
**Feature**: `002-match-calendar-events`  
**Status**: Normative for **calendar mode** generator output  
**Predecessor**: [`../../001-synthetic-fan-events/contracts/fan-events-ndjson-v1.md`](../../001-synthetic-fan-events/contracts/fan-events-ndjson-v1.md)

## Migration from v1

| Aspect | v1 | v2 |
|--------|----|----|
| Use case | Rolling UTC window (`001` script without `--calendar`) | Match calendar + date filter |
| `match_id` | Absent | **Required** on every record |
| `merch_purchase.location` | MUST NOT appear | **Optional**; when present, same string rules as v1 `ticket_scan.location` |
| Parsers | Existing v1 validators | MUST allow `match_id` and optional merch `location`; v1-only tools reject unknown keys unless updated |

v1 files and the v1 code path remain valid for **`001`** behavior; **do not** feed v2 lines to v1-only consumers without updating parsers.

## File format

Same as v1: UTF-8, LF, one JSON object per line, trailing newline after last line, **empty file = zero bytes**.

## Canonical JSON serialization

Unchanged from v1:

- `sort_keys=True`, `separators=(",", ":")`, `ensure_ascii=False`
- `amount`: EUR, **cent precision**, `> 0` for `merch_purchase`

## Event discriminator

Property **`event`**: `ticket_scan` \| `merch_purchase` only.

## Record shapes

### `ticket_scan`

| Property | Type | Constraints |
|----------|------|-------------|
| `event` | string | `ticket_scan` |
| `fan_id` | string | non-empty |
| `location` | string | non-empty |
| `match_id` | string | non-empty |
| `timestamp` | string | UTC ISO-8601 with **`Z`** |

`amount` and `item` MUST NOT appear.

### `merch_purchase`

| Property | Type | Constraints |
|----------|------|-------------|
| `event` | string | `merch_purchase` |
| `fan_id` | string | non-empty |
| `item` | string | non-empty |
| `amount` | number | `> 0`, EUR |
| `match_id` | string | non-empty |
| `timestamp` | string | UTC ISO-8601 with **`Z`** |
| `location` | string | Optional; if present, non-empty; same semantics as v1 `ticket_scan.location` |

## Ordering (global sort before write)

Sort the **entire file** lexicographically by this tuple (all ascending):

1. `timestamp`
2. `event` in enum order: `ticket_scan`, then `merch_purchase`
3. `fan_id` (Unicode lexical)
4. `match_id` (Unicode lexical)
5. **Tie-break for `ticket_scan`**: `location`
6. **Tie-break for `merch_purchase`**: `item`, then `amount`, then **`location` if present** (treat missing `location` as empty string for ordering)

This extends v1 (which used timestamp, event, fan_id, then location vs item/amount) with **`match_id`** before per-type tie-breaks so ordering remains **total** and **deterministic**.

## Domain constant

- **`JAN_BREYDEL_MAX_CAPACITY`**: **29,062** (spectators). Enforced at calendar validation for **home** matches at Jan Breydel per feature spec.

## CLI surface (calendar mode — reference)

Exact names MAY adjust if `quickstart.md` stays in sync.

| Flag | Meaning |
|------|---------|
| `--calendar` | Path to calendar JSON (see `data-model.md`) |
| `--from-date` / `--to-date` | Inclusive kickoff UTC date filter |
| `--output` / `-o` | Output NDJSON path |
| `--seed` | RNG seed (**required** for byte-identical runs) |

Rolling-mode flags (`--days`, `--count`) **MUST NOT** be combined with `--calendar` (mutually exclusive).

## Failure semantics

Non-zero exit; no durable complete output on failure (atomic write), same family as v1.
