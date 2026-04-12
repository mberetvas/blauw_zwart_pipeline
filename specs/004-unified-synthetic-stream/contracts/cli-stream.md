# CLI contract: `fan_events stream` (normative supplement)

This document describes the **operator-facing** CLI for the unified stream feature. **Event payloads** remain defined by v2/v3 interchange docs; **merge rules** remain in [`orchestrated-stream.md`](./orchestrated-stream.md).

## Subcommand

- **Name**: `stream` (required first argument after `fan_events`).

## Output

- **Stdout** when **no** `-o` / `--output`, or when output is explicitly **`"-"`** (implementation must pick one convention and document in `--help`).
- **Append-only file** when `-o PATH` is set: open in append mode, write **complete LF-terminated** lines.

## Sources (normative)

Implement **exactly** one of these modes:

| Mode | `--calendar` | `--no-retail` | v2 match events | v3 `retail_purchase` |
|------|--------------|---------------|-----------------|----------------------|
| **Merged** | **Present** | **Omit** | Yes | Yes |
| **Calendar-only** | **Present** | **Present** | Yes | No |
| **Retail-only** | **Absent** | **Omit** (do **not** pass `--no-retail`) | No | Yes |

**Validation rules:**

- `--no-retail` **without** `--calendar` is an **error** (there would be no retail and no v2 source).
- **v1 rolling** flags (`-n` / `--count` / `-d` / `--days` as rolling-window options without calendar) are **not** valid on `stream` (v1 out of scope).
- **Invalid calendar** path or JSON MUST surface **`CalendarError`** (or equivalent) like `generate_events --calendar`, non-zero exit.

Retail generation uses the same **conceptual** parameters as `generate_retail` (epoch, arrival mode, fan pool, etc.) via shared kwargs; **post-merge** caps use the flags in § Post-merge limits.

## Post-merge limits (FR-008)

These apply to the **merged** NDJSON line stream **after** interleaving v2 and v3:

- **`--max-events`**: stop after emitting **N** complete lines (optional).
- **`--max-duration`**: maximum **simulated** span in seconds from the agreed `t0` anchor (see [`research.md`](../research.md)); stop before emitting a line whose timestamp would exceed the window (optional).

**Do not** reuse **`generate_retail`** short flags **`-n` / `-d`** on `stream` for these limits — use **`--max-events` / `--max-duration`** long names only on the `stream` subparser to avoid ambiguity with retail’s `-n`/`--max-events` and `-d`/`--max-duration`.

When **both** `--max-events` and `--max-duration` are **absent**, the run is **unbounded** until interrupt, failure, or generator exhaustion (see spec FR-008). **Help** must warn about resource use.

## Feature 006 (continuous calendar + `t0` + match-day retail)

Calendar **season recycling** (default with `--calendar`), **`t0`** anchor semantics for **`--max-duration`**, **match-day retail** tuning flags, and **merged** default retail epoch alignment are specified in:

- [`specs/006-stream-three-event-kinds/contracts/cli-stream-006-supplement.md`](../../006-stream-three-event-kinds/contracts/cli-stream-006-supplement.md)
- [`specs/006-stream-three-event-kinds/quickstart.md`](../../006-stream-three-event-kinds/quickstart.md)

## Shared flags (non-exhaustive)

- **`-s` / `--seed`**: optional; feeds RNG for v2, retail, and pacing (where applicable).
- **Calendar**: `--calendar`, `--from-date`, `--to-date`, `--scan-fraction`, `--merch-factor`, `--events` — same semantics as `generate_events` calendar mode.
- **Retail**: mirror `generate_retail` options where applicable (`--epoch`, `--arrival-mode`, `--poisson-rate`, `--fan-pool`, retail-internal **`--max-events` / `--max-duration`** for the **retail** iterator only — use **distinct long names** on `stream`, e.g. **`--retail-max-events`** and **`--retail-max-duration`**, if both retail-internal caps and post-merge caps are exposed; see implementation).
- **Pacing**: `--emit-wall-clock-min`, `--emit-wall-clock-max` (pair), applied between **merged** lines (same pattern as `generate_retail --stream`).

## Mutual exclusion / validation

- **v1 rolling flags** (`-n` count rolling with **no** calendar, etc.) **not** valid on `stream` (v1 out of scope).
- **Help text**: must **warn** about unbounded resource use when post-merge limits are omitted.

## Versioning

CLI shape may evolve with **patch** doc updates; breaking renames require note in `spec.md` / release notes.
