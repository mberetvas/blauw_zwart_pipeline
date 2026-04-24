"""sql_agent — Text-to-SQL pipeline for the frontend_app Flask host.

Architecture overview
=====================

The package is a tool-calling LangChain + LangGraph agent that turns a natural
language question into a single read-only PostgreSQL SELECT statement, executes
it, and returns a Markdown answer based on the rows.

Provider routing
----------------

OpenRouter is the only supported provider. ``providers.build_chat_model(model)``
returns a ``langchain_openrouter.ChatOpenRouter`` configured from
``llm_runtime_config`` (API key, base URL, timeout). Two model **roles** are
configurable, both via OpenRouter:

* ``agent_model`` — used by the primary tool-calling loop (cheap/fast).
* ``repair_model`` — used by the bounded one-shot SQL repair pass; defaults to
  the agent model when unset, can be overridden to a stronger model.

Each role's id is resolved as: per-request body field → JSON config key
(``agent_model`` / ``repair_model``) → env var (``OPENROUTER_AGENT_MODEL`` /
``OPENROUTER_REPAIR_MODEL``) → fallback to the generic ``openrouter_model``.
The legacy request field ``model`` is treated as a synonym for ``agent_model``.

Tool surface (read-only)
------------------------

Defined in :mod:`frontend_app.sql_agent.tools`:

* ``list_tables`` / ``describe_table`` / ``search_columns`` / ``sample_table``
  — schema discovery, all routed through the ``llm_reader`` Postgres role with
  a 10s ``statement_timeout``. Identifier args are whitelisted against
  ``list_tables()`` to prevent injection.
* ``get_semantic_layer`` — returns the parsed semantic-layer YAML so the
  model can pick the right marts/metrics/joins on its own.
* ``execute_select`` — the **only** path that runs model-generated SQL; goes
  through the sqlglot pipeline below.

sqlglot pipeline (in :mod:`frontend_app.sql_agent.guardrails`)
--------------------------------------------------------------

Every SQL string the agent passes to ``execute_select`` is:

1. Stripped of Markdown code fences.
2. Layer qualifiers (``staging.x``, ``marts.x``, ``intermediate.x``) rewritten
   to the configured dbt schema (``DBT_RELATION_SCHEMA``, default ``dbt_dev``).
3. Parsed by ``sqlglot.parse(sql, dialect='postgres')`` — must yield exactly
   one top-level statement.
4. AST-walked to reject any DDL/DML node (Insert, Update, Delete, Drop,
   Create, Alter, AlterColumn, TruncateTable, Merge, Copy, Command).
5. Belt-and-braces regex check for known mutating keywords.

On failure, ``execute_select`` returns ``{"error": ..., "phase":
"validation"}`` so the agent can self-correct.

Graph topology (in :mod:`frontend_app.sql_agent.graph`)
-------------------------------------------------------

1. **Primary agent** — ``langgraph.prebuilt.create_react_agent`` over
   ``ALL_TOOLS`` and the ``agent_model``. Bounded by
   ``AGENT_MAX_TOOL_ITERATIONS`` (env, default 8).
2. If the primary agent did not produce a successful ``execute_select``, a
   single **repair pass** is run with the ``repair_model`` and a constrained
   toolset (``REPAIR_TOOLS = [describe_table, execute_select]``).
3. If repair also fails, the request returns an :class:`AgentFailure` whose
   ``phase`` maps to HTTP 422 (validation/no_sql/iteration_cap) or 500
   (execution).

Public API
----------

``run_ask(request) -> AgentResult | AgentFailure`` — used by ``POST /api/ask``.
``run_ask_stream(request) -> Iterator[StreamEvent]`` — used by
``POST /api/ask/stream``; emits ``meta`` → one or more ``answer_delta`` →
``done`` (or a single ``error`` event on failure).
"""
