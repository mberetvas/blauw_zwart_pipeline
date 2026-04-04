# Data model: Match calendar & event linkage (002)

**Spec**: [`spec.md`](spec.md)  
**Contract (NDJSON output)**: [`contracts/fan-events-ndjson-v2.md`](contracts/fan-events-ndjson-v2.md)

## 1. Calendar file (input)

**Format**: UTF-8 JSON document.

**Top-level keys**:

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `matches` | array | Yes | Non-empty at file level; may yield **zero** rows after date filtering (then output file is empty bytes). |

**Each element of `matches`**:

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `match_id` | string | Yes | Stable identifier; **unique** across the entire document. |
| `kickoff_local` | string | Yes | ISO-like local datetime **without** `Z` (e.g. `2026-08-15T18:30:00`); interpreted in `timezone`. |
| `timezone` | string | Yes | IANA name (e.g. `Europe/Brussels`). |
| `attendance` | integer | Yes | Spectators present; must be **> 0** (else validation error). |
| `home_away` | string | Yes | `home` \| `away` (club-relative). |
| `venue_label` | string | Yes | Human-readable venue for **`ticket_scan.location`** and optional **`merch_purchase.location`** (e.g. Jan Breydel for home; opponent stadium name for away). |
| `window_start_offset_minutes` | integer | No | Minutes **before** kickoff (UTC) to start the event window; default **120** if omitted. |
| `window_end_offset_minutes` | integer | No | Minutes **after** kickoff (UTC) to end the window; default **90** if omitted. |
| `competition` | string | No | Free text. |
| `opponent` | string | No | Free text. |

**Validation rules** (generator load phase):

- Duplicate **`match_id`** → error, non-zero exit.
- Missing required field → error.
- **`attendance` ≤ 0** → error.
- **`home_away` = `home`** and **`venue_label`** implies Jan Breydel for Club Brugge home games: **`attendance`** MUST be ≤ **JAN_BREYDEL_MAX_CAPACITY** (29,062) or validation fails (per spec).
- **`away`**: **`attendance`** MUST be ≤ input value (no separate cap in data-model beyond positive integer; “traveling support” plausibility is config/demo concern).

**Kickoff UTC**: `kickoff_local` + `timezone` → single instant in UTC used for window bounds.

## 2. Date range filter (CLI)

| Field | Meaning |
|-------|---------|
| `--from-date` | Inclusive lower bound on **kickoff UTC** date (`YYYY-MM-DD`) or full ISO UTC — exact CLI documented in quickstart. |
| `--to-date` | Inclusive upper bound on **kickoff UTC**. |

Matches with kickoff UTC **before** `--from-date` or **after** `--to-date` are **excluded**. If none remain → **empty** output file (zero bytes).

## 3. Generation parameters (config / CLI)

| Parameter | Meaning | Default (planning) |
|-----------|---------|---------------------|
| `scan_fraction` | Fraction of attendees that yield at least one `ticket_scan` event (deterministic rounding TBD in implementation + contract). | e.g. `0.85` |
| `merch_factor` | Expected merch **events** per attendee before rounding (or integer merch count rule). | e.g. `0.25` |
| `seed` | Global RNG seed; required for byte-identical demos. | none → error in CI; optional for exploratory |

Exact formulas and rounding live in **contract** appendix or implementation with pytest-locked golden files.

## 4. Synthetic event linkage

- Every output record includes **`match_id`** (copied from calendar).
- **`fan_id`**: opaque string; generator may reuse the same **`fan_id`** across multiple matches.
- **`ticket_scan`**: always has **`location`** = effective venue string for that match (from `venue_label` / stand logic in implementation).
- **`merch_purchase`**: optional **`location`**; generator **should** populate with same venue string when the scenario assigns it (per spec).

## 5. Entity relationship (conceptual)

```text
Calendar (matches[])
    └── Match (match_id, kickoff, attendance, …)
            └── many Fan (fan_id) — subset per match, size ≤ capped attendance
                    └── many Event (ticket_scan | merch_purchase) — timestamps ∈ match window
```
