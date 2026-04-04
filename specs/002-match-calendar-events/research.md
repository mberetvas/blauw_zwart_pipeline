# Research: Match-calendar generation (002)

**Date**: 2026-04-04  
**Scope**: Resolve format and timezone choices without new runtime dependencies.

## Calendar interchange format

| Decision | **JSON document** (UTF-8) with a top-level **`matches`** array |
| Rationale | `json` is stdlib; schema is easy to validate in tests; supports nested optional fields (window overrides) without CSV quoting issues. |
| Alternatives considered | **CSV**: good for spreadsheets; adds parsing edge cases and duplicate column names. **One JSON line per match (NDJSON)**: viable; rejected for v1 of calendar format to keep a single array validation (duplicate `match_id` across lines is harder to catch before full parse). |

## Timezone handling

| Decision | **`zoneinfo.ZoneInfo`** (`from zoneinfo import ZoneInfo`) for IANA ids (e.g. `Europe/Brussels`); kickoff interpreted as **local wall time** in that zone, then converted to **UTC** for windows and output timestamps. |
| Rationale | Standard library in Python 3.12; matches spec clarification (Brussels → UTC). |
| Alternatives considered | Fixed UTC offset only: fails DST transitions. **pytz**: extra dependency; rejected under FR-PY-003. |

**Implementation note (2026-04-04):** The **`tzdata`** PyPI package is listed as a **runtime** dependency in `pyproject.toml` so IANA zones resolve on **Windows** (stdlib `zoneinfo` uses the tzdata package when the OS has no zoneinfo database). This is the supported approach in PEP 615; no `pytz` dependency.

## DST / ambiguous local times

| Decision | Document in **data-model**: if `kickoff_local` is **missing** or **ambiguous** in the zone, the generator **fails** with a clear message (no silent fold). |
| Rationale | Fail-fast matches spec edge-case posture; exact exception text is implementation detail covered by tests. |

## Empty output file

| Decision | **Zero bytes** for no matches in range (aligns with v1 empty-file rule). |
