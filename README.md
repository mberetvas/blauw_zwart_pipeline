![Blauw zwart - Mock-up data creator](banner.jpg)

# Blauw zwart - Mock-up data creator

Synthetic fan events are produced by the `fan_events` package (`src/fan_events/`). The CLI exposes two subcommands: **`generate_events`** (match-related **v1** rolling window or **v2** calendar) and **`generate_retail`** (**v3** match-independent retail). Run commands from the **repository root** after `uv sync`, using either `uv run fan_events …` or `uv run python -m fan_events …`.

Or you can install the package using

```
uv tool install blauw-zwart-fan-sim-pipeline --from git+https://github.com/mberetvas/blauw_zwart_pipeline
```

After installation, the `fan_events` entry point is on your `PATH`. Use the same arguments as below without the `uv run` prefix (for example `fan_events generate_events --seed 1 -o out/v1.ndjson` or `fan_events generate_retail --seed 1 -o out/retail.ndjson`).

## CLI overview


| Mode             | When                               | Output contract                                                                                                                                 |
| ---------------- | ---------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------- |
| **v1** (default) | `generate_events`, no `--calendar` | Rolling UTC window — no `match_id` on lines                                                                                                      |
| **v2**           | `generate_events --calendar …`     | Match calendar — every line has `match_id`                                                                                                       |
| **v3 retail**    | `generate_retail`                  | `retail_purchase` only — [`fan-events-ndjson-v3.md`](specs/003-ndjson-v3-retail-sim/contracts/fan-events-ndjson-v3.md) |

```bash
# After `uv sync` at the repo root
uv run fan_events generate_events [options]
uv run fan_events generate_retail [options]

# Installed package: same commands without `uv run`
fan_events generate_events [options]
fan_events generate_retail [options]
```

## Parameters and defaults

Flags are **subcommand-specific**. Do not use `generate_events` options (`-n`, `--calendar`, …) with `generate_retail`, or vice versa; use a separate invocation.

### `generate_events` (v1 / v2)


| Argument         | Default                 | Description                                                                                                                        |
| ---------------- | ----------------------- | ---------------------------------------------------------------------------------------------------------------------------------- |
| `-o`, `--output` | `out/fan_events.ndjson` | Output NDJSON path                                                                                                                 |
| `--seed`         | *(none)*                | Fixed RNG seed; **v1** also fixes “now” to a constant UTC instant so output is repeatable. Omit for different random data each run |
| `--events`       | `both`                  | `both`, `ticket_scan`, or `merch_purchase`                                                                                         |


**v1 only** (do not combine with `--calendar`):


| Argument        | Default | Description                                            |
| --------------- | ------- | ------------------------------------------------------ |
| `-n`, `--count` | `200`   | Total events to emit                                   |
| `--days`        | `90`    | Length of UTC rolling window ending at generation time |


**v2 only** (`--calendar` required):


| Argument                    | Default     | Description                                                                                                                                  |
| --------------------------- | ----------- | -------------------------------------------------------------------------------------------------------------------------------------------- |
| `--calendar`                | —           | Path to calendar JSON (see below)                                                                                                            |
| `--from-date` / `--to-date` | *(omitted)* | Inclusive filter on **kickoff UTC** date (`YYYY-MM-DD`). **Omit both** to include every match in the file. If you use one, you must use both |
| `--scan-fraction`           | `0.85`      | Scales `ticket_scan` volume vs effective capacity                                                                                            |
| `--merch-factor`            | `0.25`      | Scales `merch_purchase` volume vs capacity                                                                                                   |


### `generate_retail` (v3)

Match-independent `retail_purchase` lines (three shop channels). **Batch** (default) writes a **globally sorted** file to `-o` / `--output`; **`--stream`** writes **stdout** in generation order (same seed → same bytes for both paths). Default timeline start is **`2026-01-01T00:00:00Z`** unless you pass `--epoch`.

| Argument | Default | Description |
| -------- | ------- | ----------- |
| `-o`, `--output` | `out/retail.ndjson` | Output path; **ignored** when `--stream` |
| `--seed` | *(none)* | Reproducible RNG (batch and stream) |
| `--stream` | off | Emit NDJSON to stdout; no file write |
| `--max-events` | *(see below)* | Cap on events; `0` → empty output |
| `--max-duration` | *(none)* | Max simulated seconds from epoch (`SECONDS`) |
| *(other v3 flags)* | — | Arrival modes, shop weights, epoch override, fan pool: run **`fan_events generate_retail --help`** or see [`specs/003-ndjson-v3-retail-sim/quickstart.md`](specs/003-ndjson-v3-retail-sim/quickstart.md). |

If **`--max-events`** and **`--max-duration`** are both set, generation stops when **either** bound is hit first. If **both** are omitted, the effective default is **`--max-events` 200** (Poisson inter-arrivals until that count). If only **`--max-duration`** is set, event count is unconstrained until the duration window is exceeded.

## Examples

Use `uv run fan_events` from the repo root after `uv sync`. If you installed the package, run **`fan_events`** with the same arguments (omit `uv run`).

**v1** (rolling window)

```bash
uv run fan_events generate_events --seed 1 -n 200 --days 90 -o out/v1.ndjson
```

**v2** (all matches in the calendar file)

```bash
uv run fan_events generate_events --calendar my_calendar.json --seed 42 -o out/v2.ndjson
```

**v2** (date range on kickoff UTC)

```bash
uv run fan_events generate_events --calendar my_calendar.json --from-date 2026-09-01 --to-date 2026-12-31 --seed 42 -o out/v2.ndjson
```

**v3** (batch to file)

```bash
uv run fan_events generate_retail -o out/retail.ndjson --seed 42
```

**v3** (stream to stdout)

```bash
uv run fan_events generate_retail --stream --seed 42 --max-events 100
```

## Match calendar JSON (v2 input)

UTF-8 JSON with a top-level `matches` array. Each object **must** include:


| Field           | Type    | Notes                                                     |
| --------------- | ------- | --------------------------------------------------------- |
| `match_id`      | string  | Unique in the file                                        |
| `kickoff_local` | string  | Naive local datetime, e.g. `2026-08-15T18:30:00` (no `Z`) |
| `timezone`      | string  | IANA zone, e.g. `Europe/Brussels`                         |
| `attendance`    | integer | `> 0`; for `home` at Jan Breydel, ≤ **29,062**            |
| `home_away`     | string  | `home` or `away`                                          |
| `venue_label`   | string  | Used in output locations                                  |


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

Read this before comparing **output** times to `kickoff_local` in the calendar.

1. **Every `timestamp` in the NDJSON is UTC** (ISO-8601 with a `Z` suffix). It is **not** local stadium time. To reason in local time, convert `Z` times to `timezone` (or convert kickoff to UTC and compare in UTC only).
2. **Kickoff** is the instant `kickoff_local` interpreted in `timezone`, then converted to UTC. All window math uses that **kickoff UTC** instant.
3. **Default event window** (unless you set `window_start_offset_minutes` / `window_end_offset_minutes` on the match): from **120 minutes before** kickoff UTC to **90 minutes after** kickoff UTC. Synthetic event times are picked uniformly at random inside that closed interval.
4. **Example:** `kickoff_local` `2026-08-15T18:30:00` with `Europe/Brussels` in summer (CEST, UTC+2) → kickoff **16:30 UTC**. Window → **14:30Z** … **18:00Z**. In Brussels wall-clock time that is about **16:30–20:00**, not the same numbers as the `Z` strings read naively as local time.

## Expected output

- **File**: UTF-8, Unix line endings, **one JSON object per line**, newline after the last line.
- **Serialization**: Canonical JSON (`sort_keys`, compact separators, non-ASCII preserved).
- **v1 lines**: `ticket_scan` and/or `merch_purchase` records **without** `match_id` (see `specs/001-synthetic-fan-events/contracts/fan-events-ndjson-v1.md`).
- **v2 lines**: Same event types; **every** record includes `match_id`; timestamps are UTC with a `Z` suffix (**see [v2: UTC timestamps and the match window](#v2-utc-timestamps-and-the-match-window)**); global line order follows the v2 contract (see `specs/002-match-calendar-events/contracts/fan-events-ndjson-v2.md`).
- **v3 lines**: `retail_purchase` only, closed six-field schema; batch output is globally sorted (see `specs/003-ndjson-v3-retail-sim/contracts/fan-events-ndjson-v3.md`).
- **Empty output**: If v2 date filtering removes all matches, the file is **empty** (zero bytes). Retail with `--max-events 0` (or equivalent) yields an **empty** file or no stdout bytes in stream mode.

Normative details: `specs/001-synthetic-fan-events/` (v1), `specs/002-match-calendar-events/` (v2), `specs/003-ndjson-v3-retail-sim/` (v3). Governance: [.specify/memory/constitution.md](.specify/memory/constitution.md).
