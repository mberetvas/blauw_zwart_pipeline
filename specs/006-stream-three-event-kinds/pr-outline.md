# PR outline: 006 continuous unified stream

## Title

**feat(stream): master-clock merged stream, calendar-year loop, match-day retail**

## Summary

- **Master clock**: Merged `fan_events stream` keeps one synthetic timeline; when `--calendar` is set and `--epoch` is omitted, retail emission starts at the **earliest v2 match window** so retail does not precede the calendar. **`--max-duration`** uses **`t0 = min(configured retail epoch, earliest v2 window pass 0)`** via `compute_stream_t0` and `write_merged_stream(..., t0_anchor=...)`.
- **Calendar-year loop**: `iter_looped_v2_records` shifts **`+1` civil year** per pass (`shift_match_context_calendar_years`, Feb 29 → Feb 28). With **`--calendar`**, looping is **on by default**; **`--no-calendar-loop`** yields a single pass. **`--calendar-loop-shift`** is deprecated (ignored) on `stream`.
- **Match-day retail**: New **`retail_intensity`** module builds **`F(t)`**; **`iter_retail_records`** scales Poisson **`λ_eff = rate × F(t)`** (draw order unchanged). **FR-006** flags registered on `stream` with defaults from `contracts/cli-match-day-flags-006.md`; rationale for default windows in **`research.md` §6** (Club Brugge Jan Breydel page).
- **Tests**: Calendar-year shift, `t0` duration vs first-emitted, combo caps, loop / three kinds, `F(t)` units, intensity boost ratio, merge-order (v2-only, ≥1000 lines), stdout vs file bytes.
- **Docs**: **`specs/004-.../cli-stream.md`** links **006** supplement + quickstart; **README** `stream` table updated.

## Scope limits

- **Kafka**: Uses the same `write_merged_stream` path as stdout/file (**`t0_anchor`**, **`max_events`**, **`max_duration`**). Requires **`confluent-kafka`** extra; no schema change vs 004.
- **FR-010 byte-identical golden**: **Deferred** (optional **T027**): retail can share second-resolution timestamps, so strict global merge-key monotonicity for dense retail is not guaranteed without finer timestamps; v2-only merge-order test covers SC-002.

## Reviewer checklist

- [ ] `uv run pytest` (or `cd src && python -m pytest ../tests --ignore=../tests/fan_ingest`) green.
- [ ] `ruff check src` green; new tests formatted if included in CI scope.
- [ ] `fan_events stream --help` lists loop default, `--no-calendar-loop`, and match-day flags.
- [ ] Cross-links: 004 `cli-stream.md` → 006 supplement; README → 006 quickstart.
