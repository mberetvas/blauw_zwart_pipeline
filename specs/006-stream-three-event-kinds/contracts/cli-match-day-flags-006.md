# Normative CLI: match-day retail flags (`fan_events stream`)

**Feature**: `006-stream-three-event-kinds`  
**Mirror of**: [spec.md §FR-006](../spec.md) (must stay in sync)

Applies to **`fan_events stream`** when **merged calendar + retail** mode is active (`--calendar` present, `--no-retail` absent).

## Flags and defaults

- **`--retail-home-match-day-multiplier`**: type **`float`**, default **`2.0`**, MUST be **`> 0`**. On any synthetic instant on a **home match day**, outside all **home kickoff windows** (below), retail intensity uses **`R_base ×` this value**.

- **`--retail-home-kickoff-pre-minutes`**: type **`int`**, default **`90`**, MUST be **`≥ 0`**. For each **home** match, window start at **`kickoff − pre`** on the **master timeline** (UTC instants).

- **`--retail-home-kickoff-post-minutes`**: type **`int`**, default **`120`**, MUST be **`≥ 0`**. Window end at **`kickoff + post`** for that home match.

- **`--retail-home-kickoff-extra-multiplier`**: type **`float`**, default **`1.5`**, MUST be **`> 0`**. For synthetic instants inside **any** home match’s **`[kickoff − pre, kickoff + post]`** window, intensity uses **`R_base × retail-home-match-day-multiplier ×` this value** (multiplicative stacking).

- **`--retail-away-match-day-enable`**: **boolean**, default **`false`**. When **`false`**, **`--retail-away-match-day-multiplier`** is ignored and **away-only** days use **`R_base`** only.

- **`--retail-away-match-day-multiplier`**: type **`float`**, default **`1.75`**, MUST be **`> 0`**. When **enable** is **`true`**, **away-only fixture days** (≥1 away, **no** home match that local day) use **`R_base ×` this value**. Days with **both** home and away are **home match days**; **away multiplier does not apply**.

## `R_base`

**`R_base`** is the baseline Poisson rate from existing v3 retail CLI (e.g. **`--poisson-rate`**) before match-day factors.
