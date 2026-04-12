# Feature 006 — Research: continuous stream, master clock, match-day retail

**Date**: 2026-04-12  
**Plan**: [plan.md](./plan.md)  
**Spec**: [spec.md](./spec.md)

## 1. Calendar recycling: calendar year vs fixed 365-day shift

**Decision**: Shift each season pass by **+1 calendar year** on the **match’s local civil date** (using each row’s `timezone`), then recompute **`kickoff_utc`** and v2 **match windows** from the updated naive `kickoff_local`. Use **stdlib-only** date arithmetic (`datetime.date` / `datetime.datetime` with `replace(year=…)` and **Feb 29 → Feb 28** clamp when the target year is not a leap year).

**Rationale**: Matches **FR-004** / clarifications (true “next season” on the same fixture list). The current `iter_looped_v2_records` uses a uniform **`timedelta` × cycle** (default **365 days**), which **diverges** from calendar-year replay on leap boundaries and is not spec-compliant for 006.

**Alternatives considered**:

- **Keep `timedelta(days=365)`** — rejected: not “+1 calendar year”; drifts vs civil calendar and spec.
- **Add `dateutil.relativedelta`** — rejected for core runtime: extra non-stdlib dependency; constitution VI prefers stdlib unless justified.

## 2. Default infinite calendar on `stream` (merged + `--calendar`)

**Decision**: When **`fan_events stream`** runs with **`--calendar`** and **without** `--no-retail`, **calendar recycling MUST be on by default** (equivalent to today’s **`--calendar-loop`**, but spec-aligned shift from §1). Preserve an **explicit opt-out** flag (e.g. **`--no-calendar-loop`**) for bounded single-pass behavior and tests.

**Rationale**: **SC-001** / **FR-004** require the process **not** to stop because the iterator exhausted; today **`--calendar-loop` defaults false**, so a naive merged run **ends** after one pass.

**Alternatives considered**:

- **Require operators to pass `--calendar-loop`** — rejected: contradicts “single command runs indefinitely” acceptance.
- **Always loop with no opt-out** — rejected: harms deterministic short tests and batch-like runs; opt-out is needed.

## 3. Master clock and retail time base

**Decision**: Treat **`iter_retail_records`** as advancing a **single synthetic clock** `t` in UTC. **`epoch_utc`** MUST be chosen so retail does **not** jump backward when v2 begins; align with **004 research §5**: define stream **`t0 = min(retail_epoch, earliest v2 timestamp)`** used **only** for **`--max-duration`**, while retail’s **inter-arrival** process still starts from **`epoch_utc`** (document if those differ). **No reset** of `t` when a new v2 season pass starts.

**Rationale**: **FR-003** forbids an independent retail timeline; retail timestamps must continue forward across v2 cycles.

**Alternatives considered**:

- **Reset retail epoch each v2 lap** — rejected: breaks master-clock coherence.
- **Separate retail RNG clock** — rejected.

## 4. Match-day-correlated Poisson rate (home / away / kickoff window)

**Decision**: Keep **one** Poisson draw discipline: at each step, **`gap = Exp(1) / λ_eff`** where **`λ_eff = R_base × factor(t)`**, with **`R_base`** from **`--poisson-rate`** (existing v3 CLI). **`factor(t)`** is **piecewise** from **FR-006** / [`contracts/retail-intensity-006.md`](./contracts/retail-intensity-006.md): baseline **`1.0`** on non–home-match days (and away-only when away boost off), **`retail-home-match-day-multiplier`** on **home match days** outside windows, extra **`× retail-home-kickoff-extra-multiplier`** inside **any** **home** **`[kickoff−pre, kickoff+post]`** (if multiple windows overlap, use **maximum** factor so intensity is not accidentally damped). **Away-only days**: **`× retail-away-match-day-multiplier`** only if **`--retail-away-match-day-enable`**.

**Rationale**: Matches **rate-based** clarification and **003** semantics; scales **intensity** not quotas; **max** for overlaps is simple to document and test.

**Alternatives considered**:

- **Sum exponents / add rates** in overlap — rejected: harder to explain; **max** matches “peak near kickoff” intent.
- **Separate retail generator per day class** — rejected: breaks single master iterator.

## 5. `--max-duration` anchor (`t0`) vs first-emitted line

**Decision**: Implement **`--max-duration`** on the **merged** stream per **006 / `cli-stream.md` clarification**: measure **(timestamp − t0)** in seconds, where **`t0`** is the **agreed stream anchor** (**min** of configured retail **epoch** and the **earliest scheduled v2 time** in the **first season pass**, evaluated **before** emission—see **004 research §5**). **Update `write_merged_stream`** (or a thin wrapper) so it **does not** use “first **emitted** line” as the duration anchor when that would contradict the spec.

**Rationale**: **006** clarifications require **global** caps across laps; anchor must be **stable** and match operator docs.

**Alternatives considered**:

- **First emitted timestamp** — rejected: skews duration when the first line is late; conflicts with clarified spec.
- **Per-pass reset** — rejected.

## 6. Belgian / Jan Breydel–grounded defaults for kickoff windows (bounded research)

**Decision**: Keep **FR-006** defaults **`pre=90`**, **`post=120`**, **`home-day=2.0`**, **`kickoff-extra=1.5`** as **demo defaults**, and document them as **inspired by** (not a statistical fit to) Club Brugge match-day operations:

- **Stadium opens ~1h30 before kickoff** on match days (“**Jan Breydel is op wedstrijddagen open vanaf 1:30 uur voor de aftrap**”). Source: Club Brugge official arrival page ([`https://www.clubbrugge.be/nl/aankomst-jan-breydel`](https://www.clubbrugge.be/nl/aankomst-jan-breydel)), section **INGANGEN**.
- **Main Club Shop** (Olympialaan): **open 2 hours before kickoff**, closed at kickoff, reopens after the final whistle until **1 hour after the match**; in-stadium sales units **1h30 before**, **half-time**, and **30 minutes after** full time. Same page, **CLUB SHOP** / **Verkoopunits in Jan Breydel**.

**Rationale**: **`pre=90`** aligns with **stadium** and **in-stadium unit** opening lead times; **`post=120`** covers **post-final-whistle** concourse/shop activity (order of magnitude; club shop lists **up to 1h** after on some units—**120** is a slightly conservative retail tail for **synthetic** load). **`2.0` / `1.5`** multipliers are **tunable** placeholders ensuring **testable** home-day uplift, not empirical revenue modeling.

**Alternatives considered**:

- **Match v2 `match_window` defaults (120/90)** — noted: v2 ticket/merch windows already use **120 pre / 90 post** in `v2_calendar.match_window`; retail kickoff window is **independent** per **FR-006** and may stay **90/120** for operator clarity—document relationship in contracts to avoid confusion.
- **Cite only generic “European football” blogs** — rejected: prefer **primary club/stadium** source for this repo’s Blauw-Zwart demo story.

## 7. Test strategy (design input; no `tasks.md` here)

**Decision**:

- **Infinite / lapped calendar**: **Unit** tests on **`shift_match_context` / loop iterator** with **2+ cycles**, **`--max-events`** cap; assert **strictly increasing** `kickoff_utc` across boundary and **`match_id`** / suffix rules; **Feb 29** template row in a **non-leap** target year for **clamp** behavior.
- **Monotonic / contract order**: Reuse **`merge_key_tuple`** + **`heapq.merge`**; property tests on **merged** iterator with **capped** output; **regression** byte-compare small fixtures with **fixed `--seed`**.
- **Home vs off-day retail**: **Deterministic** test: fixed **seed**, **`--max-events`**, calendar with **known** home and away-only dates; compare **`retail_purchase` counts** (or **total inter-arrival rate proxy**) over **equal simulated intervals** on **home match days** vs **away-only** + **no-fixture** days—assert ratio **≥ contract threshold** (set in **`retail-intensity-006.md`** to satisfy **SC-003**).

**Rationale**: Stochastic process → **ratio / threshold** tests with **fixed seed** beat flaky p-values in CI.

**Alternatives considered**:

- **Pure statistical tests (p < 0.05)** — optional **supplement** only; not primary gate.

## 8. Kafka / schema / 004 contracts

**Decision**: **Kafka** topic / key / serialization: **unchanged** from **004** implementation (`cli.py` / `_run_stream_kafka`); **006** does not introduce new broker fields. **v2/v3 NDJSON shapes**: **unchanged**; **ordering** still **[`orchestrated-stream.md`](../004-unified-synthetic-stream/contracts/orchestrated-stream.md)**. **Patch** **`cli-stream.md`** (004) **or** add **006** supplement for: default **calendar loop**, **`t0` duration semantics**, and **new retail flags** (avoid silent drift between 004 doc and behavior).

**Rationale**: Constitution **X** / **FR-011** require explicit contract tracking.

**Alternatives considered**:

- **New orchestrated-stream v2** — only if merge key changes (not planned).
