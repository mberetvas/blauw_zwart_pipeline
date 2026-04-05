# Research: NDJSON v3 retail shop simulation (003)

**Date**: 2026-04-05  
**Scope**: Align generation and CLI with existing v1/v2 patterns; **stdlib-only** runtime for the generator (FR-PY-003).

## Module layout

| Decision | Add **`src/fan_events/v3_retail.py`** for retail simulation (record builders, arrival logic, fan/item selection). Extend **`ndjson_io.py`** with **`validate_record_v3`**, **`sort_key_v3`**, **`records_to_ndjson_v3`**. Keep **`domain.py`** as the home for **`RETAIL_PURCHASE`**, **`SHOP_IDS`**, display-name map, **`DEFAULT_SHOP_WEIGHTS`**, and **`DEFAULT_RETAIL_SIM_EPOCH_UTC`**. |
| Rationale | Mirrors **`v1_batch.py`** / **`v2_calendar.py`** + shared **`ndjson_io`**; one place for contracts and sorting. |
| Alternatives considered | Single oversized **`retail_sim.py`** without `v3_` prefix: rejected—naming consistency with **`v1_*`** / **`v2_*`**. Splitting validation into a third file: rejected—validators stay next to v1/v2 in **`ndjson_io`**. |

## Arrival processes (stdlib)

| Decision | **Poisson / exponential inter-arrival**: use **`random.Random.expovariate(lambd)`** where **`lambd`** is the rate parameter (events per second) documented in CLI/contract; cumulative seconds added to a running **`datetime`** in UTC. **Fixed rate**: deterministic **`timedelta`** step per event. **Weighted inter-arrival**: draw next gap from a discrete set with RNG (documented in contract). |
| Rationale | No **`numpy`**; **`expovariate`** matches exponential gaps for Poisson-like counts over the line. |
| Alternatives considered | **`random.gauss`** for gaps: can produce negative gaps—would need clamping; rejected for default Poisson path. |

## Monotonic timestamps

| Decision | Maintain **`t = epoch`**; each event sets **`t = t + gap`** (or first event at **`epoch + gap₀`** per contract). If a model could theoretically violate monotonicity, **clamp** so **`timestamp` ≥ previous** (prefer avoiding—tests lock Poisson + fixed paths). |
| Rationale | Spec requires non-decreasing **`timestamp`**; ties allowed. |
| Alternatives considered | Re-sort after generation: breaks “generation order = stream order” for byte-identical stream; rejected for stream path. |

## Batch vs stream serialization

| Decision | **Batch**: build **`list[dict]`**, then **`records_to_ndjson_v3`** (validate each, **global sort** via **`sort_key_v3`**, canonical lines + trailing newline, empty → **`""`**). **Stream**: same dict construction path; emit **`dumps_canonical(rec)` + `"\n"`** per record after **`validate_record_v3`**, **no** global sort; order = generation order. |
| Rationale | Matches spec FR-007 / FR-008; stream byte identity uses same canonical **`dumps_canonical`**. |
| Alternatives considered | Stream without validation: rejected—contract-backed testing (constitution). |

## CLI surface

| Decision | Add a **dedicated subparser** (e.g. **`generate_retail`**) next to **`generate_events`**, so **v1 rolling**, **v2 calendar**, and **v3 retail** are **mutually exclusive** by structure (same pattern as requiring a subcommand today). Alternatively, a **`--retail`** flag on **`generate_events`** with **`parse_args`** checks that forbid **`--calendar`**, **`-n`/`--count`/`--days`**, and v2-only flags—**plan recommends subparser** for clearest help text and parity with “mode” separation. |
| Rationale | User asked for mutual exclusion **as clear as v1 vs v2**; subparsers avoid ambiguous combinations. |
| Alternatives considered | Only flags on **`generate_events`**: more error-prone; still viable with strict **`parser.error`** branches. |

## dbt / warehouse (provisional)

| Decision | **`fct_retail_purchases`** + **`dim_shop`** keyed by **`shop`** id; implementation of models is **out of scope** for this generator plan—note in plan only. |
| Rationale | Spec FR-WH-001; demo path may land later. |

## Kafka-oriented documentation

| Decision | No broker code in this repo; document **recommended partition keys** in **`plan.md`** only (**`fan_id`** for fan-ordered consumption; **`shop`** for per-channel scaling)—see plan. |
| Rationale | User request; keeps generator free of Kafka dependencies. |
