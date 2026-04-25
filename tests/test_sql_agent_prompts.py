"""Unit tests for the SQL agent prompt builders."""

from __future__ import annotations

from frontend_app.sql_agent import prompts


def test_agent_system_prompt_has_hard_rules() -> None:
    assert "HARD RULES" in prompts.AGENT_SYSTEM_PROMPT
    assert "execute_select" in prompts.AGENT_SYSTEM_PROMPT
    assert "dbt_dev" in prompts.AGENT_SYSTEM_PROMPT


def test_repair_system_prompt_describes_failure_recovery() -> None:
    assert "fix" in prompts.REPAIR_SYSTEM_PROMPT.lower()
    assert "execute_select" in prompts.REPAIR_SYSTEM_PROMPT


def test_build_user_prompt_minimal() -> None:
    out = prompts.build_user_prompt(
        question="who scored most?",
        conversation_section="",
        answer_style_rules=None,
    )
    assert "Question: who scored most?" in out
    assert prompts.ANSWER_STYLE_HEADER not in out


def test_build_user_prompt_includes_answer_rules() -> None:
    out = prompts.build_user_prompt(
        question="q",
        conversation_section="",
        answer_style_rules=["be concise", "use markdown"],
    )
    assert prompts.ANSWER_STYLE_HEADER in out
    assert "- be concise" in out
    assert "- use markdown" in out
    assert "Question: q" in out


def test_build_user_prompt_includes_conversation() -> None:
    out = prompts.build_user_prompt(
        question="q",
        conversation_section="Previous turn: hi",
        answer_style_rules=None,
    )
    assert "Previous turn: hi" in out
    assert "Question: q" in out


def test_build_repair_user_prompt_contains_all_context() -> None:
    out = prompts.build_repair_user_prompt(
        question="why?",
        failed_sql="SELECT bogus FROM t",
        failure_phase="validation",
        failure_message="column does not exist",
        conversation_section="prev: x",
    )
    assert "Original user question:\nwhy?" in out
    assert "SELECT bogus FROM t" in out
    assert "Failure phase: validation" in out
    assert "Failure message: column does not exist" in out
    assert "prev: x" in out
    assert "```sql" in out


def test_build_repair_user_prompt_handles_empty_sql() -> None:
    out = prompts.build_repair_user_prompt(
        question="q",
        failed_sql="",
        failure_phase="validation",
        failure_message="empty",
        conversation_section="",
    )
    assert "(no SQL was produced)" in out
