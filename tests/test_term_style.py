"""Colored argparse help (FORCE_COLOR / NO_COLOR)."""

import io
import sys

import pytest

from fan_events.term_style import (
    ColoredArgumentParser,
    ColoredHelpFormatter,
    use_color,
)


def test_help_contains_ansi_when_forced(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FORCE_COLOR", "1")
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True)
    p = ColoredArgumentParser(
        prog="t",
        formatter_class=ColoredHelpFormatter,
        description="Short description.",
    )
    p.add_argument("-x", help="x help")
    buf = io.StringIO()
    p.print_help(buf)
    assert "\033[" in buf.getvalue()


def test_no_color_empty_value_suppresses(monkeypatch: pytest.MonkeyPatch) -> None:
    """NO_COLOR must be honored when set to empty string (variable present)."""
    monkeypatch.setenv("NO_COLOR", "")
    monkeypatch.delenv("FORCE_COLOR", raising=False)
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True)
    assert use_color(sys.stdout) is False


def test_force_color_overrides_no_color(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FORCE_COLOR", "1")
    monkeypatch.setenv("NO_COLOR", "1")
    monkeypatch.setattr(sys.stdout, "isatty", lambda: False)
    assert use_color(sys.stdout) is True


def test_help_uses_color_when_force_overrides_no_color(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FORCE_COLOR", "1")
    monkeypatch.setenv("NO_COLOR", "1")
    monkeypatch.setattr(sys.stdout, "isatty", lambda: False)
    p = ColoredArgumentParser(
        prog="t",
        formatter_class=ColoredHelpFormatter,
        description="Short description.",
    )
    p.add_argument("-x", help="x help")
    buf = io.StringIO()
    p.print_help(buf)
    assert "\033[" in buf.getvalue()


def test_no_color_suppresses_ansi(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NO_COLOR", "1")
    monkeypatch.delenv("FORCE_COLOR", raising=False)
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True)
    p = ColoredArgumentParser(
        prog="t",
        formatter_class=ColoredHelpFormatter,
        description="Short description.",
    )
    p.add_argument("-x", help="x help")
    buf = io.StringIO()
    p.print_help(buf)
    assert "\033[" not in buf.getvalue()
