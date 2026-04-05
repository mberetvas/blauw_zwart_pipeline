# Contract: Fan events NDJSON v3 (retail shop simulation)

**Version**: 3.0  
**Feature**: `003-ndjson-v3-retail-sim`  
**Status**: Normative for **retail** generator output  
**Predecessors**: [`../../001-synthetic-fan-events/contracts/fan-events-ndjson-v1.md`](../../001-synthetic-fan-events/contracts/fan-events-ndjson-v1.md), [`../../002-match-calendar-events/contracts/fan-events-ndjson-v2.md`](../../002-match-calendar-events/contracts/fan-events-ndjson-v2.md)

## Migration from v1 / v2

| Aspect | v1 / v2 | v3 (this contract) |
|--------|---------|---------------------|
| Use case | Rolling window; or match calendar | **Match-independent** retail only |
| `event` values | `ticket_scan`, `merch_purchase` | **`retail_purchase`** only |
| `match_id` | v2 required | **MUST NOT** appear |
| `shop` | N/A | **Required** on every line |
| v1/v2 loaders | Expect ticket/merch only | **`retail_purchase`** lines are **invalid** for v1/v2-only validators |

v1 and v2 files and code paths remain valid for their features; do not assume v1/v2 parsers accept v3 lines without updates.

## File format

Same as v1/v2: **UTF-8**, **LF** between records, **one JSON object per line**, **trailing newline** after the last line when **≥ 1** line; **empty successful output = zero bytes** (no newline).

## Canonical JSON serialization

Same as v1/v2:

- `sort_keys=True`, `separators=(",", ":")`, `ensure_ascii=False`
- `amount`: EUR, **cent precision**, `> 0`

## Event discriminator

Property **`event`**: **`retail_purchase`** only for this contract version.

## Record shape: `retail_purchase`

**Closed schema (v3.0)**: exactly these keys — no **`currency`**, **`sku`**, or other fields unless a future contract version adds them explicitly.

| Property | Type | Constraints |
|----------|------|-------------|
| `event` | string | **`retail_purchase`** |
| `fan_id` | string | Non-empty |
| `item` | string | Non-empty; from shared catalog `ITEMS` in `src/fan_events/domain.py` |
| `amount` | number | `> 0`, EUR, cent precision |
| `timestamp` | string | UTC ISO-8601 with **`Z`** |
| `shop` | string | One of: **`jan_breydel_fan_shop`**, **`webshop`**, **`bruges_city_shop`** |

## Ordering

### Batch / file mode (global sort before write)

Sort the **entire file** lexicographically by this tuple (all ascending):

1. `timestamp`
2. `event` (enum order: only `retail_purchase` in pure v3 files)
3. `fan_id` (Unicode lexical)
4. `shop` (Unicode lexical)
5. `item` (Unicode lexical)
6. `amount` (numeric)

### Stream mode

**Global sort is not guaranteed.** Emission order is **deterministic generation order** when **`--seed`** is set. **Timestamps are non-decreasing** along that order. For byte-identical **stdout**, use the same **`dumps_canonical`** line format as batch.

## Domain constants (FR-SC-006)

- **Default simulation epoch (UTC)**: **`2026-01-01T00:00:00Z`** — synthetic timeline anchor when CLI does not override.
- **Shop identifiers**: `jan_breydel_fan_shop`, `webshop`, `bruges_city_shop` (see feature **spec.md** for display labels).

## Failure semantics

Non-zero exit on validation or I/O error; no durable complete output on failure (atomic write for file mode), same family as v1/v2.

## CLI surface (retail v3 — reference)

Exact flag names live in **`quickstart.md`**; must include **`--seed`**, optional **epoch**, shop weights, arrival model parameters, **`--output`** for file mode, and a **stream** vs **file** mode switch. **Mutually exclusive** with v1 rolling options (`-n` / `--count` / `--days`) and v2 **`--calendar`** (and related flags)—see implementation **plan.md**.

If both **`max_events`** and a simulated **duration** cap are supported, generation stops when **either** bound is reached (whichever comes first), unless the quickstart documents a different rule for a specific release.

## Default arrival model (implementation)

When the CLI does not select an arrival model, the implementation SHOULD default to **Poisson / exponential inter-arrival** with a documented **rate** parameter (see **`quickstart.md`** after flags are finalized). This clause is non-normative for interchange validation; it guides CLI defaults only.

## Examples (non-normative illustrations)

**Valid** line (single line, canonical JSON; fields ordered as `sort_keys` would emit):

```json
{"amount":12.34,"event":"retail_purchase","fan_id":"fan_00042","item":"Pet 1891","shop":"webshop","timestamp":"2026-01-01T00:05:00Z"}
```

**Invalid** (rejection reasons):

1. **Extra key** — `"match_id":"m1"` added: closed schema v3.0 forbids keys other than the six listed; **invalid**.
2. **Wrong `shop`** — `"shop":"airport_kiosk"`: not one of the three normative shop ids; **invalid**.
3. **Missing `amount`** — omit `amount`: required property missing; **invalid**.
