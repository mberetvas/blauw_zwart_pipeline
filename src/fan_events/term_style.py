"""TTY-aware ANSI styling for argparse help (stdlib only; respects NO_COLOR / FORCE_COLOR)."""

from __future__ import annotations

import argparse
import inspect
import os
import sys
from gettext import gettext as _
from typing import IO, TextIO

_RESET = "\033[0m"
_BOLD = "\033[1m"
_DIM = "\033[2m"
_FG_CYAN = "\033[36m"
_FG_RED = "\033[31m"

# Club Brugge–inspired “BLAUW ZWART” banner (FIGlet-style; one RGB per line, top → bottom).
_BLAUW_ZWART_LINES = (
    "██████╗ ██╗      █████╗ ██╗   ██╗██╗    ██╗    ███████╗██╗    ██╗ █████╗ ██████╗ ████████╗",
    "██╔══██╗██║     ██╔══██╗██║   ██║██║    ██║    ╚══███╔╝██║    ██║██╔══██╗██╔══██╗╚══██╔══╝",
    "██████╔╝██║     ███████║██║   ██║██║ █╗ ██║      ███╔╝ ██║ █╗ ██║███████║██████╔╝   ██║   ",
    "██╔══██╗██║     ██╔══██║██║   ██║██║███╗██║     ███╔╝  ██║███╗██║██╔══██║██╔══██╗   ██║   ",
    "██████╔╝███████╗██║  ██║╚██████╔╝╚███╔███╔╝    ███████╗╚███╔███╔╝██║  ██║██║  ██║   ██║   ",
    "╚═════╝ ╚══════╝╚═╝  ╚═╝ ╚═════╝  ╚══╝╚══╝     ╚══════╝ ╚══╝╚══╝ ╚═╝  ╚═╝╚═╝  ╚═╝   ╚═╝   ",
)

_BLAUW_ZWART_RGB = (
    (0, 113, 182),
    (8, 98, 153),
    (16, 84, 125),
    (24, 69, 97),
    (32, 54, 68),
    (40, 40, 40),
)

# Blank lines before/after the art so help is not flush against the shell prompt or usage:.
_BANNER_MARGIN = "\n\n"


def blauw_zwart_banner(*, color: bool) -> str:
    """
    Multi-line “BLAUW ZWART” banner. With ``color=True``, apply 24-bit ANSI per line and reset.
    With ``color=False``, plain Unicode lines only (no escape codes).
    """
    if not color:
        body = "\n".join(_BLAUW_ZWART_LINES) + "\n"
        return _BANNER_MARGIN + body + _BANNER_MARGIN
    lines: list[str] = []
    for line, rgb in zip(_BLAUW_ZWART_LINES, _BLAUW_ZWART_RGB, strict=True):
        r, g, b = rgb
        lines.append(f"\033[38;2;{r};{g};{b}m{line}")
    body = "\n".join(lines) + _RESET + "\n"
    return _BANNER_MARGIN + body + _BANNER_MARGIN


def use_color(stream: TextIO | IO[str]) -> bool:
    # FORCE_COLOR first: when set (non-empty), force color on even if NO_COLOR is set.
    if os.environ.get("FORCE_COLOR", ""):
        return True
    # NO_COLOR: variable present disables color regardless of value (https://no-color.org/).
    if "NO_COLOR" in os.environ:
        return False
    isatty = getattr(stream, "isatty", None)
    return bool(isatty and isatty())


def _wrap(text: str, prefix: str) -> str:
    return f"{prefix}{text}{_RESET}"


def style_heading(text: str, color: bool) -> str:
    if not color:
        return text
    return _wrap(text, f"{_BOLD}{_FG_CYAN}")


def style_usage_line(line: str, color: bool) -> str:
    if not color:
        return line
    return _wrap(line, f"{_BOLD}{_FG_CYAN}")


def style_description(text: str, color: bool) -> str:
    if not color:
        return text
    return _wrap(text, f"{_DIM}{_FG_CYAN}")


def style_error_message(text: str, color: bool) -> str:
    if not color:
        return text
    return _wrap(text, _FG_RED)


class ColoredHelpFormatter(argparse.HelpFormatter):
    """Colors usage, section titles, and description/epilog; leaves option columns plain."""

    def __init__(
        self,
        prog: str,
        indent_increment: int = 2,
        max_help_position: int = 24,
        width: int | None = None,
    ) -> None:
        super().__init__(prog, indent_increment, max_help_position, width)
        self._color = use_color(sys.stdout)

    def _fill_text(self, text: str, width: int, indent: str) -> str:
        """Preserve newlines in description/epilog (like RawDescriptionHelpFormatter)."""
        if not text:
            return ""
        return "".join(indent + line for line in text.splitlines(keepends=True))

    def _set_color(self, color: bool) -> None:
        """Init argparse 3.14+ _theme; apply TTY/NO_COLOR via use_color (not parser.color)."""
        if hasattr(argparse.HelpFormatter, "_set_color"):
            super()._set_color(color)
        self._color = use_color(sys.stdout)

    def _format_usage(self, usage: str | None, actions, groups, prefix: str | None) -> str:
        block = super()._format_usage(usage, actions, groups, prefix)
        if not self._color or not block:
            return block
        lines = block.splitlines(keepends=True)
        if not lines:
            return block
        first = lines[0]
        nl = ""
        if first.endswith("\n"):
            nl = "\n"
            first = first[:-1]
        if first.lower().startswith("usage:"):
            lines[0] = style_usage_line(first, True) + nl
        return "".join(lines)

    def start_section(self, heading: str) -> None:
        if heading and self._color:
            heading = style_heading(heading, True)
        super().start_section(heading)

    def add_text(self, text: str | None) -> None:
        if text and self._color:
            text = style_description(text, True)
        super().add_text(text)


class ColoredArgumentParser(argparse.ArgumentParser):
    def __init__(self, *args, **kwargs) -> None:
        # Disable CPython 3.14+ built-in argparse theme so we do not double-style.
        if "color" in inspect.signature(argparse.ArgumentParser.__init__).parameters:
            kwargs["color"] = False
        super().__init__(*args, **kwargs)

    def print_help(self, file: TextIO | None = None) -> None:
        if file is None:
            file = sys.stdout
        self._print_message(blauw_zwart_banner(color=use_color(file)), file)
        super().print_help(file)

    def error(self, message: str) -> None:
        self.print_usage(sys.stderr)
        c = use_color(sys.stderr)
        msg = style_error_message(message, c)
        self.exit(2, _("%(prog)s: error: %(message)s\n") % {"prog": self.prog, "message": msg})
