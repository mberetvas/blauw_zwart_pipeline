# Data model & timeline model — Feature 006

**Spec**: [spec.md](./spec.md)  
**Contracts**: [contracts/](./contracts/)

This feature does **not** introduce new persisted tables or dbt entities. Below is the **conceptual model** implemented in Python (`src/fan_events/`).

## Entities

### Match row (calendar JSON)

- **Source**: Existing v2 calendar (`specs/002-*`); fields `match_id`, `kickoff_local` (naive), `timezone`, `attendance`, `home_away` (`home` | `away`), `venue_label`, etc.
- **Validation**: Unchanged (`validate_and_parse_matches`).

### MatchContext (v2)

- **Fields**: `row`, `kickoff_utc`, `window_start`, `window_end`, `effective_cap` (existing).
- **Season pass**: For pass index **`k ≥ 0`**, contexts are derived from the template by shifting **+k years** (see `research.md` §1) so **`kickoff_utc`** and v2 event windows move forward monotonically.

### Synthetic retail record (v3)

- **Shape**: Unchanged `retail_purchase` NDJSON (`specs/003-*`).
- **Timestamp**: Always the **master retail clock** `t` (UTC, serialized with `Z`).

### Merged logical record

- **Union** of v2 records (`ticket_scan`, `merch_purchase`) and v3 `retail_purchase`.
- **Ordering key**: `merge_key_tuple` — timestamp UTC, `event`, canonical line bytes (see `orchestrated-stream.md`).

## Timeline / clock

### Master retail clock

- **State**: Single `datetime` (timezone-aware UTC) advanced only **forward** by inter-arrival gaps.
- **Epoch**: CLI `--epoch` (retail); must be **coherent** with v2 schedule (see `research.md` §3).

### Stream `t0` (limits only)

- **Used for**: **`--max-duration`** on the **merged** stream (**006** clarification).
- **Definition**: **`min(retail_epoch_utc, earliest_v2_instant_pass0)`** where **earliest_v2_instant_pass0** is the minimum of all v2-relevant instants in **pass 0** (kickoffs and/or generated event times—normative detail in `contracts/cli-stream-006-supplement.md`).

### Local “day” classification (retail factors)

- For instant **`t`**, convert to each **relevant** `ZoneInfo` (match timezones appearing in the filtered calendar) or use a **single** contract-defined zone (implementation choice documented in contracts—prefer **per-match timezone** for `home_away` and **local calendar date**).

- **Home match day** (local date **D**, zone **Z**): ∃ home match with kickoff local date **D** in **Z**.
- **Away-only day**: ∃ away match on **D** and **no** home match on **D**.
- **Overlap with kickoff window**: ∃ home match with **`t ∈ [kickoff_utc − pre, kickoff_utc + post]`** (use **UTC** instants on master timeline for window tests).

## Relationships

- **One** retail rate function **`factor(t)`** reads **static** calendar template + **pass index** / shifted kickoffs (or precomputed interval tree—implementation detail).
- **v2 iterators** and **retail iterator** are **independent coroutines** merged by **`heapq.merge`**; they share **fan pool** sizing when both active (**004** behavior).

## Validation rules (from spec)

- **FR-006** flags: **> 0** floats for multipliers; **≥ 0** ints for minutes; away multiplier ignored if enable false.
- **Calendar errors**: Still **`CalendarError`** → stderr, exit **1**.

## State transitions

- **Season pass**: `k → k+1` after **`iter_v2_records_merged_sorted`** completes one full cycle over filtered contexts for pass **k**; **no** retail clock reset.
