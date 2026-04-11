# TODO List

## Project: [Project Name]
### Owner: [Your Name]
### Date Created: [YYYY-MM-DD]
### Last Updated: 2026-04-11

---

### High Priority ⬆️
- [ ] Docker Compose producer (`docker-compose.yml` `producer` service): emit v3 `retail_purchase` lines on the Kafka topic together with v2 calendar match events  
  - Details: The stack runs `fan_events stream` with `--calendar` and Kafka flags; confirm the merged stream actually includes NDJSON v3 `retail_purchase` events (not only `ticket_scan` / `merch_purchase`). If needed, add explicit CLI args or env-driven defaults (e.g. retail caps, `--retail-epoch`, shop/arrival tuning) so v3 traffic is visible in local demos. Validate end-to-end through ingest → Postgres.  
  - Owner:  
  - Due:  
- [ ] Unified orchestrated stream: retail (v3) + match-day events (v2-style) with tunable schedule and fan mix  
  - Details: Today `fan_events` exposes **separate** pipelines in `cli.py`: `generate_events` produces NDJSON v1 (rolling window, `ticket_scan` / `merch_purchase`, no `match_id`) or v2 (calendar-driven `MatchContext` in `v2_calendar.py`, same event types **with** `match_id`); `generate_retail` produces v3 `retail_purchase` only (`v3_retail.py`). There is **no** built-in way to interleave or time-merge those outputs into one chronological NDJSON/stream.  
  - **Goal:** Add an orchestration layer (new module/CLI entry or long-running mode) that drives **continuous v3 retail** generation together with **synthetic match windows** (conceptually v2: kickoff-relative scans/merch), emitting a **single ordered stream** (stdout or file) suitable for demos/load tests.  
  - **Configuration:** (1) **Match cadence** — control spacing between matches (e.g. fixed interval, distribution, or parameterized schedule) instead of relying solely on a static calendar file. (2) **Stadium attendance randomness** — knobs over how many / which `fan_id`s appear in ticket and in-stadium merch on match days (correlation with ongoing retail identities is TBD but should be spec’d). (3) **Run mode** — with RNG seeds and the above settings fixed, generation runs **indefinitely** until the process is stopped manually (no fixed `--max-events` cap on the whole pipeline).  
  - **Constraints / follow-ups:** Reconcile NDJSON contracts (v2 vs v3 shapes) if one file must hold both; or define a documented “unified demo” envelope. Prefer reusing `iter_retail_records` / v2 generators rather than duplicating domain logic from `domain.py`.  
  - Owner: 
  - Due: 
- [ ] Task 1 - Short Description 
  - Details: [add details here]
  - Owner: [who is responsible]
  - Due: [yyyy-mm-dd]
- [ ] Task 2 - Short Description
  - Details: 
  - Owner:
  - Due: 

---

### Medium Priority ➖
- [ ] Task 3 - Short Description
  - Details: 
  - Owner: 
  - Due: 
- [ ] Setup Kafka container
  - Details: Provision a Kafka container, ideally via Docker Compose, for local development and testing. Ensure connectivity settings are documented for producers/consumers.  
  - Owner: 
  - Due: 

---

### Low Priority ⬇️
- [ ] Task 4 - Short Description
  - Details: 
  - Owner: 
  - Due: 

---

## Backlog / Ideas
- [ ] Idea 1 - [brief note]
- [ ] Idea 2 - [brief note]

---

## Blockers / Dependencies
- [ ] Blocker 1 [describe issue or dependent task]
- [ ] Blocker 2

---

## Completed Tasks (Move completed items here and add completion date)
- [x] Example completed task — 2024-06-05

---

*Legend:*
- [ ] = not started
- [~] = in progress
- [x] = completed