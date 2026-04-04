# Blue-Black Fan-360

Demo-quality end-to-end fan event pipeline (warehouse-first with dbt, not a production platform).

**Governance:** Architects and reviewers should treat [`.specify/memory/constitution.md`](.specify/memory/constitution.md) as the source of truth for non-negotiable rules (spec-first contracts, byte-identical seeded runs where specified, NDJSON contract testing, versioned schema changes, UTC temporal rules, modelled analytics, immutable raw, dbt data quality, demo-first trade-offs, pytest-backed Python via UV, stdlib-first generators unless the spec adds a dependency).

**Synthetic events:** Run `uv run python scripts/generate_fan_events.py` from the repo root. Rolling-window output (**v1** contract): [`specs/001-synthetic-fan-events/quickstart.md`](specs/001-synthetic-fan-events/quickstart.md). Match-calendar / season output (**v2** contract): [`specs/002-match-calendar-events/quickstart.md`](specs/002-match-calendar-events/quickstart.md).

**Compliance note:** The constitution expects **CI** to run **`dbt test`** once a warehouse integration path exists. This repo is still **incremental**: synthetic raw NDJSON lands before dbt/CI; see **`Constitution follow-up`** in [`specs/001-synthetic-fan-events/plan.md`](specs/001-synthetic-fan-events/plan.md) for the explicit deferral.
