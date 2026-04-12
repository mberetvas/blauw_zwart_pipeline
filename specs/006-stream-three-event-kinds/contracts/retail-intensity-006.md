# Retail arrival intensity — Feature 006

**Spec**: [spec.md](../spec.md)  
**Flags**: [cli-match-day-flags-006.md](./cli-match-day-flags-006.md)

## Model

At each retail generation step with master clock **`t`** (UTC):

1. Let **`R_base`** be the CLI baseline Poisson rate (**`--poisson-rate`**).
2. Compute **`F(t) ≥ 1`** — the **dimensionless factor** from calendar rules below.
3. Draw inter-arrival gap **`G ~ Exponential`** with rate **`λ_eff = R_base × F(t)`**  
   (equivalently `G = -ln(U)/(R_base × F(t))` with `U ~ Uniform(0,1)` — **same RNG draw order** as v3 except **`λ_eff` varies per step**).

**Determinism**: For fixed **`--seed`**, the sequence of **`(U, …)`** draws and the computed **`F(t)`** at each step MUST be reproducible.

## Calendar classification (instant `t`)

Use **filtered** template matches (`--from-date` / `--to-date`). For each match, **`kickoff_utc`** is on the **master timeline** for **every** season pass **`k`** (shifted by **+k calendar years** per feature spec).

### Local day

For classification, map **`t`** to **local calendar date** in the match row’s **`timezone`** (`ZoneInfo`). **Home match day** / **away-only day** are evaluated per **local date** in that zone.

**Implementation note**: A single instant **`t`** may be “Saturday evening UTC” and “Sunday local” for Europe/Brussels—classification MUST use the **match’s** zone for that match’s **home/away** day logic (document chosen aggregation if simplifying to one zone).

### Home match day

**`D`** is a **home match day** if there exists a **home** (`home_away == "home"`) match whose **local kickoff date** equals **`D`** (in that match’s timezone).

### Away-only day

**`D`** is **away-only** if there is **≥1 away** match on **`D`** and **no** home match on **`D`**.

### Home kickoff window (UTC)

For each **home** match with kickoff **`K`** (UTC):

**`W = [K − pre·1m, K + post·1m]`** using CLI **`--retail-home-kickoff-pre-minutes`** / **`--retail-home-kickoff-post-minutes`**.

## Piecewise factor `F(t)`

Let:

- **`H`** = **`--retail-home-match-day-multiplier`**
- **`E`** = **`--retail-home-kickoff-extra-multiplier`**
- **`A_en`** = **`--retail-away-match-day-enable`**
- **`A`** = **`--retail-away-match-day-multiplier`**

1. If **`t`** lies in **any** home kickoff window **`W`**:  
   **`F(t) = H × E`**  
   If **`t`** lies in **several** overlapping windows, **`F(t)`** is still **`H × E`** (same value — overlaps do not stack further).

2. Else if **`t`’s local day (in the classification zone used)** is a **home match day**:  
   **`F(t) = H`**.

3. Else if **`A_en`** and the day is **away-only**:  
   **`F(t) = A`**.

4. Else:  
   **`F(t) = 1`**.

## Acceptance threshold (SC-003)

**Placeholder for implementation**: Set **`MIN_HOME_VS_NONHOME_RETAIL_RATIO`** in tests to a value **≥ 1.25** (25% uplift) over a **bounded** golden fixture **unless** calibration shows a higher floor is needed—document final constant next to test.

## Relation to v2 `match_window`

v2 ticket/merch uses **`match_window`** defaults (**120** pre, **90** post) in `v2_calendar.py` for **scan/merch** events. **Retail** kickoff windows use **FR-006** defaults (**90** / **120**) and are **independent** by design.
