"""Colored argparse help (FORCE_COLOR / NO_COLOR)."""

import io
import sys

import pytest

from fan_events.term_style import (
    ColoredArgumentParser,
    ColoredHelpFormatter,
    blauw_zwart_banner,
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


def test_blauw_zwart_banner_plain_has_no_ansi() -> None:
    s = blauw_zwart_banner(color=False)
    assert "\033" not in s
    assert "\n\n" + "██████╗ ██╗      █████╗" in s
    assert s.count("██████╗ ██╗      █████╗") == 1
    assert s.count("\n") >= 6


def test_blauw_zwart_banner_colored_truecolor_and_reset() -> None:
    s = blauw_zwart_banner(color=True)
    assert "\033[38;2;0;113;182m" in s
    assert "\033[38;2;40;40;40m" in s
    assert s.rstrip().endswith("\033[0m")


def test_subparser_print_help_starts_with_banner(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NO_COLOR", "1")
    monkeypatch.delenv("FORCE_COLOR", raising=False)
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True)
    root = ColoredArgumentParser(prog="fan_events", formatter_class=ColoredHelpFormatter)
    sub = root.add_subparsers(parser_class=ColoredArgumentParser)
    gen = sub.add_parser("generate_events", formatter_class=ColoredHelpFormatter)
    gen.add_argument("-o", help="Output path")
    buf = io.StringIO()
    gen.print_help(buf)
    assert any(ln.startswith("██████╗ ██╗      █████╗") for ln in buf.getvalue().splitlines())


def test_print_help_starts_with_plain_banner_first_line(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NO_COLOR", "1")
    monkeypatch.delenv("FORCE_COLOR", raising=False)
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True)
    p = ColoredArgumentParser(prog="t", formatter_class=ColoredHelpFormatter)
    p.add_argument("-x", help="x help")
    buf = io.StringIO()
    p.print_help(buf)
    assert any(ln.startswith("██████╗ ██╗      █████╗") for ln in buf.getvalue().splitlines())


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
