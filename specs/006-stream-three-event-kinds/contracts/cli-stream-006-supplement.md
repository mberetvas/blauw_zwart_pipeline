# CLI supplement: `fan_events stream` — Feature 006

**Amends / extends**: [`specs/004-unified-synthetic-stream/contracts/cli-stream.md`](../../004-unified-synthetic-stream/contracts/cli-stream.md)  
**Related**: [cli-match-day-flags-006.md](./cli-match-day-flags-006.md), [retail-intensity-006.md](./retail-intensity-006.md)

## 1. Continuous calendar (`--calendar`)

When **`--calendar`** is set (**merged** or **calendar-only** with **`--no-retail`**):

- The stream MUST **recycle** the calendar **indefinitely** per **006** **FR-004** (season passes with **+1 calendar year** per pass).
- **Implementation direction**: default behavior aligns with **006**; an explicit **opt-out** (e.g. **`--no-calendar-loop`**) MAY exist for single-pass runs and tests.

**004 doc gap**: `cli-stream.md` currently describes merge modes but not **006** default looping—treat this file as normative for **006** until **004** is patched to reference it.

## 2. Post-merge `--max-duration` anchor

**`--max-duration`** applies to the **merged** NDJSON stream **after** interleaving.

- **Anchor `t0`**: **`min(retail_epoch_utc, earliest_v2_relevant_instant_pass0)`** where **earliest_v2_relevant_instant_pass0** is the **minimum** UTC instant among all v2 synthetic events that **could** be emitted in **season pass 0** (or a documented equivalent such as **min kickoff_utc** over filtered home/away matches if tighter—**must** be fixed in implementation and tests).
- **Rule**: Stop **before** emitting a line whose **`timestamp`** would satisfy **`(ts − t0).total_seconds() > max_duration`**.
- **Cross-pass**: Caps are **global**; **no** reset per season (**006** clarifications).

**004 / code note**: when **`t0_anchor`** is passed, `write_merged_stream` uses the fixed anchor above; when omitted, legacy **first-emitted** anchoring remains for backward compatibility.

## 3. New retail flags

All **match-day retail** flags are normative in [cli-match-day-flags-006.md](./cli-match-day-flags-006.md).

## 4. Kafka

No change to topic / key / value layout vs **004** unless **004** Kafka contract is separately amended.
