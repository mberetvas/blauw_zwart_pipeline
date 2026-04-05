# Implementation Plan: NDJSON v3 retail shop simulation

**Branch**: `003-ndjson-v3-retail-sim` | **Date**: 2026-04-05 | **Spec**: [`spec.md`](spec.md)  
**Input**: Feature specification + user notes (align with `v1_batch` / `v2_calendar` / `ndjson_io` / CLI)

## Summary

Add **match-independent** synthetic **`retail_purchase`** NDJSON (**v3**) with **three** shop channels, **stdlib-only** generation, **closed** six-field schema, **default epoch** `2026-01-01T00:00:00Z`, **equal default shop weights**, **batch global sort** and **stream generation-order** output (both **byte-identical** under **`--seed`**). Implementation extends **`fan_events.domain`** with **`RETAIL_PURCHASE`**, **`SHOP_IDS`**, display names, weights, and epoch; adds **`v3_retail.py`** for simulation; extends **`ndjson_io.py`** with **`validate_record_v3`**, **`sort_key_v3`**, **`records_to_ndjson_v3`**; extends **`cli.py`** (and thus **`__main__.py`**) with a **separate subcommand** for retail to keep **mutual exclusion** as clear as v1 vs v2. Normative contract: **`specs/003-ndjson-v3-retail-sim/contracts/fan-events-ndjson-v3.md`**.

## Technical Context

**Language/Version**: Python **3.12+** (`pyproject.toml` `requires-python`)  
**Primary Dependencies**: **stdlib only** for generator/runtime logic (constitution VI); **`tzdata`** may remain as existing timezone support for v2 (unchanged for v3)  
**Storage**: NDJSON **file** (atomic write via existing **`write_atomic_text`**) or **stdout** (stream)  
**Testing**: **pytest**, **`uv run pytest`** from repo root  
**Target Platform**: cross-platform (Windows/Linux/macOS); **LF** newlines for NDJSON lines  
**Project Type**: CLI package **`fan_events`** (`src/fan_events/`)  
**Performance Goals**: demo-scale (e.g. ≥ 50k lines batch per spec SC-003); no production SLO  
**Constraints**: byte-identical output for batch + stream when **`--seed`** + fixed inputs; UTF-8; canonical JSON  
**Scale/Scope**: single feature branch; no Kafka implementation (documentation only below)

## Constitution Check

**Pre–Phase 0**: PASS — spec + contracts cited; dbt marts named provisionally (`fct_retail_purchases`, `dim_shop`); raw append-only; pytest/UV/stdlib generator path documented.

**Post–Phase 1 design**: PASS — **`research.md`**, **`data-model.md`**, **`contracts/fan-events-ndjson-v3.md`**, **`quickstart.md`** complete; no unjustified constitution violations.

## Project Structure

### Documentation (this feature)

```text
specs/003-ndjson-v3-retail-sim/
├── plan.md                 # This file
├── research.md             # Phase 0
├── data-model.md           # Phase 1
├── quickstart.md           # Phase 1
├── contracts/
│   └── fan-events-ndjson-v3.md
└── tasks.md                # /speckit.tasks (not created here)
```

### Source code (concrete)

```text
src/fan_events/
├── domain.py               # + RETAIL_PURCHASE, SHOP_IDS, display names, DEFAULT_SHOP_WEIGHTS, DEFAULT_RETAIL_SIM_EPOCH_UTC
├── ndjson_io.py            # + validate_record_v3, sort_key_v3, records_to_ndjson_v3
├── v3_retail.py            # NEW: generate retail records (batch list + helpers for stream)
├── cli.py                  # + generate_retail subcommand, run_v3, mutual exclusion
├── __main__.py             # unchanged entry (delegates to cli.main)
├── v1_batch.py             # unchanged contract path for v1
└── v2_calendar.py          # unchanged contract path for v2

tests/
├── test_ndjson_v3.py       # NEW (or split): validation, sort, golden batch optional
└── …                       # existing v1/v2 tests stay green
```

**Structure decision**: New logic lives in **`v3_retail.py`** (parallel to **`v1_batch.py`** / **`v2_calendar.py`**). Serialization and contract enforcement stay in **`ndjson_io.py`** alongside v1/v2.

## Architecture

### Data flow

```text
CLI (generate_retail)
  → parse args (seed, epoch, weights, arrival model, max_events/duration, stream vs file)
  → v3_retail.generate_*  → list[dict]  (batch) or yield dict (stream)
  → validate_record_v3 per record
  → batch: records_to_ndjson_v3 (sort_key_v3 + dumps_canonical + trailing newline rules)
  → stream: per line dumps_canonical + "\n" to stdout (no global sort)
  → file: write_atomic_text
```

### `ndjson_io.py` additions

| Symbol | Role |
|--------|------|
| **`validate_record_v3`** | Closed schema: exactly keys `event`, `fan_id`, `item`, `amount`, `timestamp`, `shop`; **`event == retail_purchase`**; **`shop` ∈ SHOP_IDS**; amount > 0; timestamp UTC `Z`; item in **`ITEMS`** (import from **`domain`**) |
| **`sort_key_v3`** | Tuple for global batch order per **`fan-events-ndjson-v3.md`** |
| **`records_to_ndjson_v3`** | Empty list → **`""`**; else validate all, **`sorted(..., key=sort_key_v3)`**, join with **`"\n"`**, trailing **`"\n"`** |

Consider a small **`format_line_v3(rec)`** → **`dumps_canonical(rec) + "\n"`** shared by stream and batch line building to avoid drift.

### `v3_retail.py` responsibilities

- Build **`retail_purchase`** dicts (canonical key order not required pre-**`dumps_canonical`**, but keep one helper **`make_retail_purchase(...)`** for clarity).
- Draw **`fan_id`** from a bounded pool (document default pool sizing in contract or code comment; align style with **`v1_batch`**).
- Draw **`item`** from **`ITEMS`**, **`amount`** in cent precision (same approach as **`v1_batch`** merch).
- Draw **`shop`** using weights (**`DEFAULT_SHOP_WEIGHTS`** or CLI override); reject invalid explicit weights with **`ValueError`** (CLI maps to exit **1**).
- Inter-arrival: implement **at least** three modes per **`research.md`**; accumulate UTC **`datetime`** from **`DEFAULT_RETAIL_SIM_EPOCH_UTC`** or CLI epoch.

### `domain.py` additions

| Constant | Purpose |
|----------|---------|
| **`RETAIL_PURCHASE`** | `"retail_purchase"` |
| **`SHOP_IDS`** | Tuple of three stable ids (order = default weight order) |
| **`SHOP_DISPLAY_NAME`** | `dict[str, str]` id → human label (for docs/dim_shop; not written to NDJSON) |
| **`DEFAULT_SHOP_WEIGHTS`** | Three floats summing to **1.0** (e.g. three **1/3**) aligned to **`SHOP_IDS`** |
| **`DEFAULT_RETAIL_SIM_EPOCH_UTC`** | `datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)` |

## CLI integration (`cli.py`)

- Add subparser **`generate_retail`** (recommended name; mirror **`generate_events`** pattern with **`required=True`** subparsers).
- **`generate_retail`** flags MUST include **`--max-events`** and optional **`--max-duration`** (simulated timeline seconds, name may match **tasks.md** T013), with **whichever-first** stop when both are set—aligned with **FR-009** and **`fan-events-ndjson-v3.md`**.
- **`main`**: dispatch **`run_v3`** when command is **`generate_retail`**; keep **`generate_events`** → **`run_v2`** if **`calendar`** else **`run_v1`**.
- **Mutual exclusion** (enforced in **`parse_args`** after parse, same style as v1/v2):
  - **`generate_retail`** must not appear alongside conflicting global options if any shared flags are reused incorrectly (subparsers isolate most conflicts).
  - If any flags are **shared** at parent level, avoid; prefer **all retail-specific flags** on **`generate_retail`** only.
  - **Do not** allow **`generate_events`** to accept **`--retail`** without review—either retail is **only** under **`generate_retail`**, or document explicit **`parser.error`** bridges.
- Document in help: retail is **v3** only; **no** **`--calendar`**, **no** v1 **`-n`/`--days`**.
- Stream: **`sys.stdout.write`** with **`flush`** policy documented (default: flush each line for pipe-friendly behavior).

## Testing strategy

| Layer | Content |
|-------|---------|
| **Unit** | **`validate_record_v3`**: missing/extra keys, wrong **`shop`**, bad **`amount`**, invalid timestamp format, **`item`** not in **`ITEMS`** |
| **Unit** | **`sort_key_v3`**: total ordering ties (**timestamp**, **fan_id**, **shop**, **item**, **amount**) |
| **Integration** | **`records_to_ndjson_v3`**: empty vs non-empty file bytes; ends with **`\n`** iff ≥1 record |
| **Generator** | Fixed **`--seed`** + fixed args: **batch** file **byte-identical** across two runs; **stream** stdout **byte-identical** |
| **Optional golden** | Commit small **`tests/fixtures/retail_v3_golden.ndjson`** for batch mode (optional but recommended for regression) |

All tests via **`uv run pytest`**.

## Kafka-facing notes (documentation only)

No implementation in this repo. Recommended **message key** strategies for operators mirroring NDJSON to Kafka:

| Strategy | When to use |
|----------|-------------|
| **Key = `fan_id`** | Preserve per-fan ordering of retail events; useful for fan-360–style processing. |
| **Key = `shop`** | Rough **partition-by-channel** balancing; good when scaling consumers by shop. |
| **Key = null / round-robin** | Maximum spread; **no** per-fan ordering guarantee. |

**Value**: JSON body identical to line object (or same fields in Avro/JSON Schema later). **Timestamp**: use record **`timestamp`** for event-time semantics.

## Complexity Tracking

No constitution violations requiring justification; table empty.

## Phase 0 & Phase 1 deliverables

| Artifact | Path | Status |
|----------|------|--------|
| Research | [`research.md`](research.md) | Done |
| Data model | [`data-model.md`](data-model.md) | Done |
| Contract | [`contracts/fan-events-ndjson-v3.md`](contracts/fan-events-ndjson-v3.md) | Done |
| Quickstart | [`quickstart.md`](quickstart.md) | Done |

## Next step

Run **`/speckit.tasks`** to produce **`tasks.md`** (implementation breakdown).
