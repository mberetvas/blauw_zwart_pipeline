# AI Chat Feature: Architecture & Flow

## Executive Summary

The AI chat transforms questions into read-only SQL queries through a two-stage ReAct agent pipeline (primary + optional repair stage), validated with sqlglot AST + regex, executed via llm_reader PostgreSQL role with 10s timeout, and returned as natural-language answers. Supports both sync JSON and streaming SSE responses.

## Quick Architecture

\\\
Browser Request → Flask validates → AgentRequest → Primary Agent 
    (full tools: list_tables, describe_table, execute_select, etc.) 
    → If success: return result
    → Else: Repair Agent (constrained tools) → return result
    → Format JSON or SSE → HTTP Response
\\\

## Request Handling (Flask: app.py)

1. **Validate** - Question required, provider defaults to "openrouter"
2. **Normalize history** - Up to 3 prior turns, each with question + answer + optional sql/preview
3. **Build context** - Conversation block helps agent scope follow-ups
4. **Resolve models** - env vars: OPENROUTER_AGENT_MODEL, OPENROUTER_REPAIR_MODEL
5. **Create AgentRequest** - Pass to pipeline

**Endpoints:**
- POST /api/ask - Sync; returns {answer, sql, data_preview, trace, repaired}
- POST /api/ask/stream - SSE; emits progress, meta, answer_delta, done

## Primary Agent (graph.py)

**Init:**
- Resolve model (env override or default)
- Load semantic layer (non-fatal if missing)
- Build prompts (system: "You are careful analyst...", user: question + context)
- Create ChatOpenRouter instance

**Execution:**
- LangGraph ReAct agent (create_agent)
- Recursion limit = max_iterations × 2 + 5 (default: 8 → 21)
- Tools: list_tables(), describe_table(), search_columns(), sample_table(), execute_select(), get_semantic_layer()
- Iterate: reason → select tool → execute → observe → loop
- Stop when final message (Markdown, no tool calls)

**Classification:**
- Success: parsed_result["rows"] exists, no error → AgentResult(repaired=False)
- Failure: no SQL, validation error, execution error, or iteration cap → Repair Agent

## Repair Agent (if primary failed)

- Constrained toolset: only describe_table() + execute_select()
- Max iterations: max(3, primary_max // 2) (typically 4)
- **Exactly ONE attempt** - no retry
- Return AgentResult(repaired=True) if successful, else AgentFailure

## Tools (tools.py)

| Tool | Purpose |
|------|---------|
| list_tables() | Lists all tables with layer (staging/intermediate/marts) |
| describe_table(table) | Column metadata, types, descriptions |
| search_columns(pattern) | Find columns by name (ILIKE, case-insensitive) |
| sample_table(table) | Peek at rows (max 10) |
| execute_select(sql) | Execute validated SELECT; returns {rows: [...], sql: "..."} or {error, phase} |
| get_semantic_layer() | Load metrics, join paths, answer rules |

**Security:**
- Validation: sqlglot AST + regex (no mutations allowed)
- Role: llm_reader (read-only)
- Timeout: 10s per query
- Wrapping: SELECT * FROM (...) LIMIT 100
- Identifiers validated against information_schema

## SQL Validation (guardrails.py)

**Layer 1 (sqlglot AST):**
- Parse as Postgres dialect
- Check: exactly 1 statement
- Check: top-level is Select/With/Union/Subquery/Paren
- Check: no mutating nodes (Insert, Update, Delete, Create, Drop, etc.) anywhere

**Layer 2 (regex):**
- Forbidden keywords: INSERT, UPDATE, DELETE, DROP, ALTER, CREATE, GRANT, REVOKE, etc.

## Database Execution (database.py)

Input SQL → Wrap: SELECT * FROM (...) LIMIT 100 → Connect as llm_reader → 
SET statement_timeout='10s' → Execute → Fetch rows → Serialize (Decimal→float, datetime→ISO) → Output

## Streaming (SSE: graph.py)

**Architecture:**
- Worker thread: runs run_ask(), emits progress to queue
- Main thread: drains queue (250ms throttle), yields StreamEvent objects
- HTTP stream: Flask sends as text/event-stream

**Events (success):**
progress: "Warming up..." → "Thinking..." → "Cleaning attic..." → "Checking records..."
meta: {sql, data_preview, trace_notes, repaired}
answer_delta: "Answer paragraph 1..."
answer_delta: "Answer paragraph 2..."
done: {}

**Throttle:** 250ms between identical progress states

## Complete Example

Q: "Which fans spent over €1000?"

1. Agent iteration 1: Calls list_tables() → sees mart_fan_loyalty
2. Agent iteration 2: Calls describe_table("mart_fan_loyalty") → sees total_spend column
3. Agent iteration 3: Calls execute_select("SELECT fan_id, total_spend FROM mart_fan_loyalty WHERE total_spend > 1000")
   - Validated (sqlglot + regex)
   - Executed as llm_reader with 10s timeout
   - Wrapped in LIMIT 100
   - Returns 12 rows
4. Agent iteration 4: Final message (no tools): "12 fans have spent over €1000..."

Response: {answer: "12 fans have spent over €1000...", sql: "SELECT...", data_preview: [...], repaired: false}

## Configuration

| Env Var | Purpose | Default |
|---------|---------|---------|
| OPENROUTER_API_KEY | API key (required) | None |
| OPENROUTER_AGENT_MODEL | Primary agent model | Uses OPENROUTER_MODEL |
| OPENROUTER_REPAIR_MODEL | Repair agent model | Uses OPENROUTER_MODEL |
| AGENT_MAX_TOOL_ITERATIONS | Max tool calls | 8 |
| LLM_READER_DATABASE_URL | Read-only DB (llm_reader role) | Falls back to DATABASE_URL |
| SEMANTIC_LAYER_FILE | Semantic metadata YAML | sql_agent/semantic/semantic_layer.yml |
| DBT_RELATION_SCHEMA | dbt schema | dbt_dev |

## Files

- app.py - Flask HTTP layer, endpoints, request validation
- sql_agent/graph.py - Agent orchestration, primary + repair, streaming
- sql_agent/tools.py - Tool definitions, schema discovery
- sql_agent/guardrails.py - SQL validation (sqlglot + regex)
- sql_agent/database.py - Postgres execution, role enforcement
- sql_agent/providers.py - OpenRouter integration
- sql_agent/prompts.py - Prompt templates
- sql_agent/semantic_layer.py - Semantic metadata loading
- sql_agent/observability.py - Telemetry handler

## Key Takeaways

1. **Two-stage pipeline:** Primary agent with full tools, optional repair with constrained tools
2. **Read-only guarantee:** Validated SQL, llm_reader role, 10s timeout, LIMIT 100
3. **Streaming support:** SSE with real-time progress (throttled to 250ms)
4. **Error recovery:** If primary fails, repair agent gets one attempt
5. **Conversation aware:** Prior turns help scope follow-ups correctly
