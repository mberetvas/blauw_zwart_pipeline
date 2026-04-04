# Blauw zwart - Mock-up data creator

Synthetic fan events are produced by the `fan_events` package (`src/fan_events/`). The CLI is the `fan_events` command (subcommand `generate_events`). Run commands from the **repository root** after `uv sync`. You can also use `uv run python -m fan_events generate_events …` if you prefer the module form.

## CLI overview

| Mode | When | Output contract |
|------|------|-------------------|
| **v1** (default) | No `--calendar` | Rolling UTC window — no `match_id` on lines |
| **v2** | `--calendar <path>` | Match calendar — every line has `match_id` |

```bash
uv run fan_events generate_events [options]
```

## Parameters and defaults

Arguments apply to **both** modes unless noted.

| Argument | Default | Description |
|----------|---------|-------------|
| `-o`, `--output` | `out/fan_events.ndjson` | Output NDJSON path |
| `--seed` | *(none)* | Fixed RNG seed; **v1** also fixes “now” to a constant UTC instant so output is repeatable. Omit for different random data each run |
| `--events` | `both` | `both` \| `ticket_scan` \| `merch_purchase` |

**v1 only** (do not combine with `--calendar`):

| Argument | Default | Description |
|----------|---------|-------------|
| `-n`, `--count` | `200` | Total events to emit |
| `--days` | `90` | Length of UTC rolling window ending at generation time |

**v2 only** (`--calendar` required):

| Argument | Default | Description |
|----------|---------|-------------|
| `--calendar` | — | Path to calendar JSON (see below) |
| `--from-date` / `--to-date` | *(omitted)* | Inclusive filter on **kickoff UTC** date (`YYYY-MM-DD`). **Omit both** to include every match in the file. If you use one, you must use both |
| `--scan-fraction` | `0.85` | Scales `ticket_scan` volume vs effective capacity |
| `--merch-factor` | `0.25` | Scales `merch_purchase` volume vs capacity |

**v1 example**

```bash
uv run fan_events generate_events --seed 1 -n 200 --days 90 -o out/v1.ndjson
```

**v2 example** (all matches in the calendar file)

```bash
uv run fan_events generate_events --calendar my_calendar.json --seed 42 -o out/v2.ndjson
```

**v2 example** (date range)

```bash
uv run fan_events generate_events --calendar my_calendar.json --from-date 2026-09-01 --to-date 2026-12-31 --seed 42 -o out/v2.ndjson
```

## Match calendar JSON (v2 input)

UTF-8 JSON with a top-level `matches` array. Each object **must** include:

| Field | Type | Notes |
|-------|------|--------|
| `match_id` | string | Unique in the file |
| `kickoff_local` | string | Naive local datetime, e.g. `2026-08-15T18:30:00` (no `Z`) |
| `timezone` | string | IANA zone, e.g. `Europe/Brussels` |
| `attendance` | integer | `> 0`; for `home` at Jan Breydel, ≤ **29,062** |
| `home_away` | string | `home` or `away` |
| `venue_label` | string | Used in output locations |

**Optional** per match: `window_start_offset_minutes` (default **120**), `window_end_offset_minutes` (default **90**), `competition`, `opponent`.

Template (required fields only):

```json
{
  "matches": [
    {
      "match_id": "m-001",
      "kickoff_local": "2026-08-15T18:30:00",
      "timezone": "Europe/Brussels",
      "attendance": 500,
      "home_away": "home",
      "venue_label": "Jan Breydel Stadium"
    }
  ]
}
```

## v2: UTC timestamps and the match window

Read this before comparing **output** times to **`kickoff_local`** in the calendar.

1. **Every `timestamp` in the NDJSON is UTC** (ISO-8601 with a `Z` suffix). It is **not** local stadium time. To reason in local time, convert `Z` times to `timezone` (or convert kickoff to UTC and compare in UTC only).

2. **Kickoff** is the instant `kickoff_local` interpreted in `timezone`, then converted to UTC. All window math uses that **kickoff UTC** instant.

3. **Default event window** (unless you set `window_start_offset_minutes` / `window_end_offset_minutes` on the match): from **120 minutes before** kickoff UTC to **90 minutes after** kickoff UTC. Synthetic event times are picked uniformly at random inside that closed interval.

4. **Example:** `kickoff_local` `2026-08-15T18:30:00` with `Europe/Brussels` in summer (CEST, UTC+2) → kickoff **16:30 UTC**. Window → **14:30Z** … **18:00Z**. In Brussels wall-clock time that is about **16:30–20:00**, not the same numbers as the `Z` strings read naively as local time.

## Expected output

- **File**: UTF-8, Unix line endings, **one JSON object per line**, newline after the last line.
- **Serialization**: Canonical JSON (`sort_keys`, compact separators, non-ASCII preserved).
- **v1 lines**: `ticket_scan` and/or `merch_purchase` records **without** `match_id` (see `specs/001-synthetic-fan-events/contracts/fan-events-ndjson-v1.md`).
- **v2 lines**: Same event types; **every** record includes **`match_id`**; timestamps are UTC with a `Z` suffix (**see [v2: UTC timestamps and the match window](#v2-utc-timestamps-and-the-match-window)**); global line order follows the v2 contract (see `specs/002-match-calendar-events/contracts/fan-events-ndjson-v2.md`).
- **Empty output**: If v2 date filtering removes all matches, the file is **empty** (zero bytes).

Normative details: `specs/001-synthetic-fan-events/` (v1), `specs/002-match-calendar-events/` (v2). Governance: [`.specify/memory/constitution.md`](.specify/memory/constitution.md).
