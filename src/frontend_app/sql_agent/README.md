# SQL Agent — Text-to-SQL Chat Pipeline

The chat UI talks to the SQL agent over `/api/ask/stream` using Server-Sent Events. Behind that endpoint, a LangGraph agent translates natural-language questions into validated read-only SQL, runs it against the dbt warehouse, and streams progress and answer text back to the browser. A second "repair" agent gets one shot to recover when the primary agent fails. Multiple guardrails — a least-privilege DB role, AST-level SQL validation, identifier whitelisting, row caps, and a statement timeout — sit between the LLM and Postgres.

A non-streaming `POST /api/ask` route also exists on the Flask app but is not used by the current chat UI, so it is omitted from the diagram below.

## Architecture diagram

**Legend:** solid arrows = synchronous call / return flow; dashed arrows = async / callback-driven flow (SSE progress events, LangChain callbacks, queue writes).

```mermaid
flowchart TD
    user((User))

    %% ── 1. Streaming Layer ───────────────────────────────────────
    subgraph streaming ["Streaming Layer"]
        stream_api["run_ask_stream\nentry point for SSE chat requests"]
        worker["Background Worker\nruns the agent off the request thread"]
        pq["Progress Queue\nbridges worker and SSE loop"]
        throttle["Dedup &amp; Throttle\ncollapses repeats within 0.25 s"]
        sse_yield["SSE Emitter\nyields events to the browser"]
    end

    user -- "POST /api/ask/stream" --> stream_api
    stream_api --> worker
    worker -.-> pq
    pq -.-> throttle
    throttle -.-> sse_yield
    sse_yield -. "progress → meta → answer_delta → done | error" .-> user

    %% ── 2. Prompt Construction ───────────────────────────────────
    subgraph prompting ["Prompt Construction"]
        sem_load1["Load Semantic Layer\n(answer style rules)"]
        build_prompt["Build User Prompt\nquestion + history + style rules"]
    end

    worker --> sem_load1
    sem_load1 --> build_prompt

    %% ── 3. Primary Agent ─────────────────────────────────────────
    subgraph primary_box ["Primary Agent"]
        primary["Primary ReAct Agent\nplans tool calls and drafts the answer"]

        subgraph tools ["Tool Belt"]
            direction LR
            t1["get_semantic_layer\nsubjects, metrics, joins"]
            t2["list_tables"]
            t3["describe_table"]
            t4["search_columns"]
            t5["sample_table"]
            t6["execute_select"]
        end

        subgraph sql_exec ["SQL Execution"]
            strip["Strip Fences\nclean markdown + trailing ;"]
            rewrite["Rewrite Schema Qualifiers\nlayer names → dbt_dev"]
            guard{"SQL Guard\n(AST parse + keyword check)"}
            exec_sql["Execute SQL\nwrap in LIMIT 50"]
            pg[("Postgres\ndbt_dev schema")]
            preview["Data Preview\nfirst 10 rows for the user"]
        end

        sem_file[("semantic_layer.yml")]
        sem_load2["Load Semantic Layer\n(subjects, metrics, join paths)"]
    end

    build_prompt --> primary
    primary --> tools
    tools --> primary
    t1 --> sem_load2
    sem_load2 --> sem_file
    t6 --> strip
    strip --> rewrite
    rewrite --> guard
    guard -- "rejected → JSON error" --> t6
    guard -- "safe SELECT" --> exec_sql
    exec_sql --> pg
    pg --> preview
    preview --> t6

    %% ── 4. Repair Agent ──────────────────────────────────────────
    subgraph repair_box ["Repair Agent"]
        repair_prompt["Build Repair Prompt\nfailed SQL + phase + error"]
        repair["Repair ReAct Agent\nsecond chance to produce an answer"]

        subgraph repair_tools ["Repair Tool Belt"]
            direction LR
            rt1["describe_table"]
            rt2["execute_select"]
        end
    end

    primary -- "failed / no rows / iteration cap" --> repair_prompt
    repair_prompt --> repair
    repair --> repair_tools
    repair_tools --> repair
    rt2 --> strip
    sem_file --> sem_load2

    %% ── 5. Observability ─────────────────────────────────────────
    subgraph obs ["Observability"]
        handler["Agent Observability Handler\ncaptures LLM and tool timings"]
        sink["Progress Sink\nstructured event buffer"]
        user_progress["User Progress Mapper\nturns events into UI updates"]
    end

    primary -. "callbacks" .-> handler
    repair -. "callbacks" .-> handler
    handler -.-> sink
    sink -.-> user_progress
    user_progress -.-> pq

    %% ── Outcome branches ─────────────────────────────────────────
    primary -- "success" --> result_p["Answer\n(repaired=false)"]
    repair -- "success" --> result_r["Answer\n(repaired=true)"]
    repair -- "also failed" --> fail["Failure\n(phase + error message)"]

    result_p --> sse_yield
    result_r --> sse_yield
    fail --> sse_yield

    %% ── Security callout ─────────────────────────────────────────
    sec["Security: llm_reader role\nSELECT-only · 10 s timeout\nrow cap: LIMIT 50"]
    sec -. "enforced on every query" .- guard

    style sec fill:#fde68a,stroke:#b45309,color:#1f2937
```

## How it works

- **Two-stage pipeline.** A primary ReAct agent (using `agent_model`) gets the full 6-tool belt. If it fails to produce a successful `execute_select` result, a repair agent (using `repair_model`) is invoked with only `describe_table` + `execute_select`. At most one repair pass runs per request.
- **Dual SQL guardrail.** Every SQL string passed to `execute_select` is pre-processed (`_strip_fences` → `_rewrite_layer_schema_qualifiers`) then validated in two layers: (1) sqlglot parses the Postgres-dialect AST and rejects any mutating node type (`_MUTATING_AST_TYPES`: `Insert`, `Update`, `Delete`, `Drop`, `Create`, `Alter`, `AlterColumn`, `TruncateTable`, `Merge`, `Copy`, `Command`) or multi-statement input; (2) a regex (`_MUTATING`) rejects residual keywords (`INSERT`, `UPDATE`, `DELETE`, `DROP`, `GRANT`, `REVOKE`, `SET ROLE`, …) and stray semicolons. Rejection returns a structured JSON error (`{"error": "...", "phase": "validation", "sql": "..."}`) to the agent — not a hard exception — so the agent can fix the SQL and retry.
- **Identifier whitelisting.** All tools that accept a `table` argument (`describe_table`, `sample_table`, `search_columns`, `list_tables` internally) validate the identifier format (`[A-Za-z_][A-Za-z0-9_]*`) and then check it against live `information_schema.tables` for the dbt schema via `_ensure_known_table` before any SQL is constructed.
- **SQL post-processing.** `_execute_sql` wraps the validated SQL in `SELECT * FROM (\n{sql}\n) AS llm_query LIMIT 50` to hard-cap row count. The `data_preview` field returned to the caller is further capped at 10 rows (`_result_to_data_preview`).
- **Database role.** The DB connection uses the `llm_reader` Postgres role (`SELECT`-only on `dbt_dev` + `raw_data.player_stats`) with `statement_timeout = '10s'` set on every connection.
- **Semantic layer.** `load_semantic_layer()` is called **twice** per request: once in `run_ask` to extract `answer_style.rules` for the user prompt, and again when the agent calls the `get_semantic_layer()` tool at runtime to learn about subjects, metrics, dimensions, join paths, and layering rules.
- **Repair prompt construction.** `build_repair_user_prompt` injects the failed SQL, the failure phase (`"validation"` / `"execution"` / `"no_sql"`), and the failure message into the repair agent's user prompt so it has full context to diagnose and fix.

### Threading and request-ID propagation

`run_ask_stream` spawns a daemon `threading.Thread` that calls `run_ask(on_progress=...)`. Progress payloads flow through a `queue.Queue`. The main thread polls the queue (100 ms timeout), deduplicates, throttles, and yields `StreamEvent` objects. A `threading.Event` signals worker completion. After the worker finishes, any remaining queued progress events are drained before emitting `meta` / `answer_delta` / `done` (or `error`).

`set_request_id` is called inside the worker thread to propagate the correlation ID (a `ContextVar`) across the thread boundary; `reset_request_id` restores the previous value on thread exit.

### Observability

`AgentObservabilityHandler` is a LangChain `BaseCallbackHandler` that emits timing events (`llm_start`, `llm_done`, `tool_start`, `tool_done`, `*_error`) into a `ProgressSink`. In streaming mode these events are mapped through `_user_progress()` into user-friendly `StreamEvent("progress", ...)` payloads — for example a `tool_start` for `execute_select` becomes a `"Running the query"` progress card in the chat UI.

## Reference

### SSE streaming events

`run_ask_stream` yields `StreamEvent(name, data)` objects. The frontend receives these as Server-Sent Events. Events are emitted in the order shown below.

| Event name | Payload shape | Description |
| --- | --- | --- |
| `progress` | `{"step_key": str, "title": str, "detail": str, "phase": str, "ts": str}` | Emitted throughout the agent run. `step_key` values: `run_start`, `llm_start`, `llm_done`, `tool_start`, `tool_done`, `repair_start`, `finalizing`, `llm_error`, `tool_error`, `run_error`. `phase` is `"primary"`, `"repair"`, or `"final"`. Duplicate `(step_key, phase, title, detail)` tuples are throttled to at most one per 0.25 s. |
| `meta` | `{"sql": str, "data_preview": list[dict], "trace_notes": list[str], "repaired": bool}` | Emitted once after the agent completes successfully. Contains the executed SQL, up to 10 preview rows, the `notes` trace log, and whether the repair pass was used. |
| `answer_delta` | `{"text": str}` | One or more chunks of the Markdown answer. The answer is split on `\n\n` paragraph boundaries to give a streaming feel without re-invoking the LLM. Each chunk has `\n\n` appended. |
| `done` | `{}` | Terminal event: the stream is complete. |
| `error` | `{"message": str, "phase"?: str, "sql"?: str, "notes"?: list[str]}` | Terminal event: the agent failed. On `AgentFailure`, includes `phase`, `sql`, and `notes`. On uncaught exceptions, only `message` is present. |

### Agent result and failure fields

- **`AgentResult.repaired: bool`** — whether the repair agent produced the final answer.
- **`AgentResult.notes: list[str]`** — human-readable trace log (model used, repair triggered, etc.).
- **`AgentFailure.phase` values:**
    - `"validation"` — guardrail rejected the SQL.
    - `"execution"` — Postgres runtime error or uncaught exception.
    - `"no_sql"` — agent finished without calling `execute_select`.
    - `"iteration_cap"` — LangGraph raised `GraphRecursionError` (recursion limit exceeded).

### Iteration caps

`AGENT_MAX_TOOL_ITERATIONS` (env var, default `8`, clamped to `1`–`25`) controls the primary agent. Its LangGraph `recursion_limit` is computed as `max_iter * 2 + 5`. The repair agent cap is `max(3, max_iter // 2)`.

### Environment variables

| Variable | Default | Description |
| --- | --- | --- |
| `OPENROUTER_API_KEY` | _(none)_ | **Required.** OpenRouter API key. Never exposed in full to clients (GET returns a masked suffix). |
| `OPENROUTER_BASE_URL` | `https://openrouter.ai/api/v1` | OpenRouter API base URL. |
| `OPENROUTER_MODELS` | `deepseek/deepseek-v3.2, google/gemini-3.1-flash-lite-preview, minimax/minimax-m2.5, x-ai/grok-4.1-fast` | Comma-separated model catalog for the UI model picker. |
| `OPENROUTER_TIMEOUT` | `120` | HTTP timeout in seconds for OpenRouter requests (valid: 1–600). |
| `OPENROUTER_AGENT_MODEL` | _(none)_ | Seed for the `agent_model` setting at startup. See [LLM config precedence](#llm-config-precedence). |
| `OPENROUTER_REPAIR_MODEL` | _(none)_ | Seed for the `repair_model` setting at startup. Falls back to the resolved agent model when unset. |
| `OPENROUTER_MODEL` | `deepseek/deepseek-v3.2` | Legacy default. Used as agent model when no other override is set. |
| `AGENT_MAX_TOOL_ITERATIONS` | `8` | Max tool iterations for the primary agent (clamped 1–25). Repair cap = `max(3, value // 2)`. |
| `SEMANTIC_LAYER_FILE` | `semantic/semantic_layer.yml` (beside the module) | Path to the semantic layer YAML. If explicitly set but missing, raises `SemanticLayerError`. |
| `SEMANTIC_CONTEXT_MAX_CHARS` | `0` (uncapped) | Max characters for the rendered semantic context. `0` = no limit; exceeding truncates with a banner. |
| `DBT_RELATION_SCHEMA` | `dbt_dev` | Postgres schema where dbt builds all relations. Used by all tools for `information_schema` lookups. |
| `LLM_CONFIG_PATH` | `src/frontend_app/llm_config.json` | Path to the persisted JSON config overlay. Created/updated by `PUT /api/llm-config`. |
| `LLM_READER_DATABASE_URL` | _(none)_ | Postgres connection string for the `llm_reader` role. Falls back to `DATABASE_URL`. |
| `DATABASE_URL` | _(none)_ | Fallback Postgres connection string. |
| `DBT_MODELS_DIR` | _(none)_ | Directory of dbt model YAML files for column descriptions in tool responses (auto-discovers `*_schema.yaml` and `marts/schema.yml`). |

### LLM config precedence

OpenRouter is the only supported provider. Settings are seeded from env vars, overlaid by an optional `LLM_CONFIG_PATH` JSON file at startup, and updatable at runtime via `PUT /api/llm-config`.

1. Environment variables seed the defaults at startup.
2. If `LLM_CONFIG_PATH` points to an existing JSON file, its keys overlay the env defaults (persisted settings win).
3. `PUT /api/llm-config` updates the in-memory state and atomically rewrites the JSON file.

Model role resolution:

- **`agent_model`**: per-request override → `agent_model` setting → legacy `openrouter_model`.
- **`repair_model`**: per-request override → `repair_model` setting → resolved `agent_model`.

### Security design

Layers are listed defence-in-depth, from outermost (identity) inward to execution and output limits.

| Layer | Mechanism | Detail |
| --- | --- | --- |
| **Identity — database role** | `llm_reader` Postgres role | `SELECT`-only on `dbt_dev.*` and `raw_data.player_stats`. No write, DDL, or admin privileges. Created by `docker/postgres/init/002_llm_reader.sql`. |
| **Identity — API key masking** | `to_public_config()` | `GET /api/llm-config` returns only the last 4 characters of the OpenRouter API key, prefixed with `****`. |
| **Input shaping — pre-processing** | `_strip_fences` + `_rewrite_layer_schema_qualifiers` | Strips markdown code fences and trailing semicolons; rewrites `staging.` / `intermediate.` / `marts.` prefixes to `dbt_dev.` (LLMs sometimes infer layer labels as SQL schemas). |
| **Validation — AST guard** | sqlglot parse + walk | Parses the SQL as Postgres dialect. Rejects: parse failures, multi-statement input, non-`SELECT` top-level nodes, and any node matching `_MUTATING_AST_TYPES` (`Insert`, `Update`, `Delete`, `Drop`, `Create`, `Alter`, `AlterColumn`, `TruncateTable`, `Merge`, `Copy`, `Command`) anywhere in the tree. |
| **Validation — keyword regex** | `_MUTATING` regex | Defence-in-depth second pass: rejects `INSERT`, `UPDATE`, `DELETE`, `DROP`, `TRUNCATE`, `ALTER`, `CREATE`, `REPLACE`, `GRANT`, `REVOKE`, `EXECUTE`, `EXEC`, `CALL`, `COPY`, `VACUUM`, `ANALYZE`, `COMMENT`, `LOCK`, `CLUSTER`, `REINDEX`, `REFRESH`, `SET ROLE`, `RESET`. Also rejects stray `;` characters. |
| **Validation — identifier whitelist** | `_ensure_known_table` | Format-validated (`[A-Za-z_][A-Za-z0-9_]*` regex) and checked against live `information_schema.tables` for the dbt schema before any SQL is constructed. Prevents injection via fabricated table names. |
| **Validation — soft errors** | Structured JSON, not exceptions | Guardrail rejections return `{"error": "...", "phase": "validation", "sql": "..."}` to the agent as a tool response, allowing it to self-correct rather than crashing the pipeline. |
| **Execution — statement timeout** | `SET statement_timeout = '10s'` | Set on every `_run_read_query` connection. Kills runaway queries server-side. |
| **Execution — row cap** | `LIMIT 50` outer wrap | `_execute_sql` wraps all agent SQL in `SELECT * FROM (...) AS llm_query LIMIT 50`. |
| **Output — preview cap** | `data_preview` ≤ 10 rows | `_result_to_data_preview` slices to the first 10 rows before returning to the caller/SSE stream. |
| **Output — tool result caps** | Bounded tool responses | `list_tables` ≤ 200 rows, `describe_table` ≤ 300 columns, `search_columns` ≤ 100 hits, `sample_table` ≤ 10 rows (constants `_MAX_TABLES_RETURNED`, `_MAX_COLUMNS_RETURNED`, `_MAX_SEARCH_RESULTS`, `_MAX_SAMPLE_ROWS`). Bounds context-window usage and prevents the agent from pulling the full database into its prompt. |
| **Exposure — no schema in prompt** | Tools-based discovery | The system prompt contains no table or column names. The agent must call `list_tables`, `describe_table`, etc. to discover schema, reducing the risk of prompt-injected SQL targeting known columns. |
