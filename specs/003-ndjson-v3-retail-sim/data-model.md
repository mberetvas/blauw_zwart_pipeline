# Data model: NDJSON v3 retail (003)

**Spec**: [`spec.md`](spec.md)  
**Contract (NDJSON output)**: [`contracts/fan-events-ndjson-v3.md`](contracts/fan-events-ndjson-v3.md)

## 1. Output event: `retail_purchase`

**Grain**: one synthetic off-match retail line (no **`match_id`**).

| Field | Type | Required (v3.0) | Constraints |
|-------|------|-----------------|-------------|
| `event` | string | Yes | **`retail_purchase`** only |
| `fan_id` | string | Yes | Non-empty |
| `item` | string | Yes | Non-empty; value **∈** `ITEMS` in `domain.py` |
| `amount` | number | Yes | **> 0**, EUR, cent precision (same as v1 **`merch_purchase`**) |
| `timestamp` | string | Yes | UTC ISO-8601 with **`Z`** |
| `shop` | string | Yes | **∈** `SHOP_IDS` (see §2) |

**Closed schema (v3.0)**: no other keys. Extra keys ⇒ invalid record.

## 2. Shop dimension (normative ids)

| `shop` (id) | Display label (non-normative) |
|---------------|-------------------------------|
| `jan_breydel_fan_shop` | Jan Breydel fan shop (in-stadium retail) |
| `webshop` | Webshop |
| `bruges_city_shop` | Bruges city shop |

**Default mixture**: equal weight **1/3** per shop when CLI weights omitted (ordered consistently with **`SHOP_IDS`** in code).

## 3. Simulation parameters (config / CLI)

| Parameter | Meaning | Default |
|-----------|---------|---------|
| `seed` | **`random.Random`** seed; required for byte-identical runs | omitted → non-deterministic (document) |
| `epoch_utc` | Start anchor for synthetic timeline | **`2026-01-01T00:00:00Z`** |
| Shop weights | Three non-negative weights aligned to **`SHOP_IDS`** | equal **1/3** each |
| Arrival model | `poisson` \| `fixed` \| `weighted` (exact enum in contract) | **poisson** default for CLI when unspecified (see contract non-normative note) |
| Rate / gaps | Model-specific (e.g. λ for Poisson, Δ for fixed) | contract + quickstart |
| `max_events` | Stop after **N** lines | optional |
| Simulated `duration` | Stop after cumulative simulated time reaches cap | optional |

**Stopping rules**: If both **`max_events`** and **`duration`** are supported, document precedence (e.g. whichever comes first) in the contract.

## 4. Entity relationship (conceptual)

```text
Synthetic timeline (epoch UTC + inter-arrival gaps)
    └── many retail_purchase (fan_id, shop, item, amount, timestamp)
            shop ∈ {jan_breydel_fan_shop, webshop, bruges_city_shop}
            item ∈ ITEMS
```

No calendar, no match, no ticket scan in default configuration.

## 5. Consumer rules (migration)

- **v1/v2** validators: **`event`** must be **`ticket_scan`** or **`merch_purchase`** only; **`retail_purchase`** is **invalid** for those contracts (see spec FR-SC-004).
- **v3** ingest: use **`validate_record_v3`** (or equivalent) and **`fan-events-ndjson-v3.md`**.
