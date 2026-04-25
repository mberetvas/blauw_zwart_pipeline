# Logging Policy

This project uses a single Loguru-based logging system configured by `common.logging_setup`.

## Goals

- Keep logs readable in terminal with clear colors per level.
- Use only two operational levels in application code: `INFO` and `DEBUG`.
- Keep `INFO` concise and high-signal.
- Place `DEBUG` logs before the related action with useful execution context.

## Configuration

- Entry points call `configure_logging(level=os.environ.get("LOG_LEVEL", "INFO"))`.
- `LOG_LEVEL=INFO` shows milestone notifications.
- `LOG_LEVEL=DEBUG` shows step-by-step pre-action context.
- Stdlib `logging` records are intercepted and normalized through Loguru.
- Request IDs are injected via `register_request_id_getter(...)` and shown as `req_id`.

## Message conventions

- `INFO` is for lifecycle milestones and outcomes:
  - startup/shutdown
  - stage completed
  - batch summary
  - failure summary
- `DEBUG` is for execution context before work:
  - task identifier
  - what just happened
  - what is expected next
  - key non-sensitive parameters

## Good examples

- `INFO`: `run_ask_complete repaired=true rows=12`
- `DEBUG`: `task=execute_select_run previous=validation_passed next=query_database sql_preview=...`

## Avoid

- Per-item `INFO` logs inside tight loops.
- Repeating the same narrative in route and orchestration layers.
- Logging full secrets, tokens, or raw personal data.
