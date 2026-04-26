---
description: This file defines the code documentation and commenting standards for Python code in the project, including docstring format and when to use inline comments.
applyTo: **/*.py
---
# Python Code Documentation & Commenting Standards

## Overview
All Python code in this project must follow **literate-style commenting** — code that reads like prose and is self-explanatory without requiring external documentation. This combines structured docstrings with strategic inline narrative comments.

## Docstring Standard: Google Style

Every function, class, and module must include a Google-style docstring with these sections:

### For Functions & Methods
```python
def function_name(arg1: str, arg2: int) -> dict[str, Any]:
    """Brief one-line summary ending with a period.

    Longer description explaining the purpose, behavior, and context.
    Include the "why" not just the "what". Can span multiple paragraphs.

    Args:
        arg1: Description of first argument, with type hints optional
            (they're already in the signature).
        arg2: Description of second argument. Can span multiple lines
            with proper indentation.

    Returns:
        Description of return value type and structure. For dicts,
        explain key names and their meanings.

    Raises:
        SpecificException: When this exception is raised and why.
        AnotherException: When this is raised.

    Note:
        Any important caveats, non-obvious behavior, or performance
        considerations.
    """
```

### For Classes
```python
class ClassName:
    """Brief one-line summary.

    Longer description of the class purpose and typical usage.

    Attributes:
        attr_name: Description of the attribute and its type.
    """
```

### For Modules
Include a module-level docstring at the top of the file explaining its purpose, architecture, and public API.

## Inline Narrative Comments: Explain Intent at Decision Points

Insert comments at key flow control points to explain **why** the code takes a certain path, not **what** the code does (the code itself shows that).

### Good (Explains Intent)
```python
# Load the semantic layer for answer-style rules; failure is non-fatal.
layer = {}
try:
    layer = load_semantic_layer()
except Exception as exc:
    log.info("semantic_layer_load_failed_non_fatal error={}", exc)

# First pass: build a map of {tool_call_id → sql} so we can match
# each ToolMessage to its original SQL string.
last_call_id_to_sql: dict[str, str] = {}
for msg in messages:
    if isinstance(msg, AIMessage) and getattr(msg, "tool_calls", None):
        for tc in msg.tool_calls:
            # ...

# Primary succeeded — extract rows, SQL, and final prose answer.
rows = list(parsed["rows"])
sql_used = parsed.get("sql") or raw_sql or ""
```

### Bad (Restates the Code)
```python
# Set layer to an empty dict
layer = {}

# Try to load the semantic layer
try:
    layer = load_semantic_layer()
# Catch any exception
except Exception as exc:
    log.info("semantic_layer_load_failed_non_fatal error={}", exc)

# Iterate through the messages
for msg in messages:
    # Check if msg is an AIMessage
    if isinstance(msg, AIMessage):
```

## When to Add Inline Comments

Add narrative comments at these moments:

1. **Major algorithm phases** — when the code transitions to a new logical step
   ```python
   # --- Primary stage: full toolset, unrestricted schema discovery -----------
   ```

2. **Non-obvious guard clauses** — when a check prevents bugs or handles edge cases
   ```python
   # Guard against unexpected state shapes by returning an empty list.
   if not isinstance(msgs, list):
       return []
   ```

3. **Complex multi-step operations** — to break them into digestible chunks
   ```python
   # First pass: collect all tool_call_ids
   # Second pass: match them to results
   ```

4. **Why, not what** — when the reason for the code is not immediately clear
   ```python
   # LangGraph counts individual node visits, not iterations, so we
   # multiply by 2 and add a buffer for entry/exit nodes.
   recursion_limit = max_iterations * 2 + 5
   ```

5. **Fallback/recovery logic** — when the code handles errors or unexpected input
   ```python
   # Parse the tool's JSON response; fall back to error dict on decode failure.
   try:
       parsed = json.loads(content)
   except (json.JSONDecodeError, TypeError):
       parsed = {"error": "execute_select returned non-JSON content"}
   ```

## Docstring Sections: When to Use Each

- **Args**: Always include for any function with parameters.
- **Returns**: Always include unless the function returns `None` (but still document if side effects matter).
- **Raises**: Include when the function may raise checked exceptions. Omit for obvious built-ins like `TypeError` unless they're intentional contract violations.
- **Note**: Use for gotchas, performance considerations, or non-obvious constraints.

## Examples

### ✅ Well-Documented Function
```python
def _classify_outcome(
    parsed_result: dict[str, Any] | None,
    raw_sql: str | None,
) -> tuple[bool, str, str | None]:
    """Classify an execute_select result into a (success, phase, error) triple.

    Inspects the parsed JSON payload and decides whether the agent stage
    should be considered successful. Returns structured information for
    logging and decision-making.

    Args:
        parsed_result: The JSON-decoded content of the last execute_select
            ToolMessage, or None if the tool was never called.
        raw_sql: The SQL string passed to execute_select, or None if
            unavailable. Used for symmetry but not in classification logic.

    Returns:
        A three-tuple (success, phase, error_message):

        - success (bool): True only when parsed_result contains a "rows"
          key with no "error" key.
        - phase (str): "ok" on success; "no_sql" when tool was never called;
          otherwise the phase from parsed_result (defaulting to "validation").
        - error_message (str | None): Human-readable failure description,
          or None on success.
    """
    # Tool was never called — agent finished without producing any SQL.
    if parsed_result is None:
        return False, "no_sql", "Agent finished without calling execute_select."

    # Tool returned an error payload from validation or execution layer.
    if "error" in parsed_result:
        return False, str(parsed_result.get("phase") or "validation"), str(parsed_result["error"])

    # Happy path: tool ran successfully and returned rows.
    if "rows" in parsed_result:
        return True, "ok", None

    # Unexpected payload shape — treat as a no-sql failure.
    return False, "no_sql", "execute_select returned an unexpected payload."
```

## Enforcement

- **Required**: Every public function, class, and module must have a docstring.
- **Required**: Complex functions (>10 lines) must have at least 2-3 strategic inline comments.
- **Required**: Any function that performs multiple logical steps must mark transitions.
- **Preferred**: Even short helper functions benefit from a one-liner docstring + inline comments.

## Related Files
- See `.vscode/settings.json` for docstring linting rules (pylint, pydocstyle).
- See `/tests/test_*.py` for examples of well-documented test functions.

## Quick Checklist for Code Review

- [ ] Every function/class has a Google-style docstring?
- [ ] Docstring includes Args, Returns, and (if applicable) Raises/Note?
- [ ] Inline comments explain **why**, not **what**?
- [ ] Comments appear at algorithm phase transitions, guard clauses, and complex steps?
- [ ] No redundant comments that just repeat the code?
- [ ] Docstring examples (if present) are runnable and correct?
