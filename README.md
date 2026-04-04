# Blue-Black Fan-360

Demo-quality end-to-end fan event pipeline (warehouse-first with dbt, not a production platform).

**Governance:** Architects and reviewers should treat [`.specify/memory/constitution.md`](.specify/memory/constitution.md) as the source of truth for non-negotiable rules (modelled analytics, immutable raw, dbt data quality, demo-first trade-offs).

**Compliance note:** The constitution expects **CI** to run **`dbt test`** once a warehouse integration path exists. This repo is still **incremental**: synthetic raw NDJSON ([`specs/001-synthetic-fan-events/quickstart.md`](specs/001-synthetic-fan-events/quickstart.md)) lands before dbt/CI; see **`Constitution follow-up`** in [`specs/001-synthetic-fan-events/plan.md`](specs/001-synthetic-fan-events/plan.md) for the explicit deferral.
