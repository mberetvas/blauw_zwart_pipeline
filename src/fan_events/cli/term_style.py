"""Apply Club Brugge-flavored ANSI styling to the ``fan_events`` CLI.

The helpers in this module keep the CLI stdlib-only while still making help and
error output easier to scan. Color use is TTY-aware and respects ``NO_COLOR``
plus ``FORCE_COLOR`` for users who prefer or forbid ANSI escape sequences.
"""

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
    """Return the multi-line Club Brugge banner used in CLI help output.

    Args:
        color: Whether to wrap each banner line in 24-bit ANSI color escapes.

    Returns:
        Banner string including surrounding blank-line margins.
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
    """Determine whether ANSI styling should be emitted for a stream.

    Args:
        stream: Output stream that may or may not be attached to a TTY.

    Returns:
        ``True`` when color output should be enabled.
    """
    # FORCE_COLOR first: when set (non-empty), force color on even if NO_COLOR is set.
    if os.environ.get("FORCE_COLOR", ""):
        return True
    # NO_COLOR: variable present disables color regardless of value (https://no-color.org/).
    if "NO_COLOR" in os.environ:
        return False
    isatty = getattr(stream, "isatty", None)
    return bool(isatty and isatty())


def _wrap(text: str, prefix: str) -> str:
    """Wrap text in an ANSI prefix plus the shared reset code."""
    return f"{prefix}{text}{_RESET}"


def style_heading(text: str, color: bool) -> str:
    """Style an argparse section heading when color output is enabled."""
    if not color:
        return text
    return _wrap(text, f"{_BOLD}{_FG_CYAN}")


def style_usage_line(line: str, color: bool) -> str:
    """Style the ``usage:`` line emitted by argparse."""
    if not color:
        return line
    return _wrap(line, f"{_BOLD}{_FG_CYAN}")


def style_description(text: str, color: bool) -> str:
    """Style descriptive help text while leaving option columns untouched."""
    if not color:
        return text
    return _wrap(text, f"{_DIM}{_FG_CYAN}")


def style_error_message(text: str, color: bool) -> str:
    """Style parser error messages for stderr output."""
    if not color:
        return text
    return _wrap(text, _FG_RED)


class ColoredHelpFormatter(argparse.HelpFormatter):
    """Argparse formatter that colors headings and banner-friendly text blocks.

    The formatter intentionally leaves option columns plain so spacing and copy
    semantics remain identical to the standard library output.
    """

    def __init__(
        self,
        prog: str,
        indent_increment: int = 2,
        max_help_position: int = 24,
        width: int | None = None,
    ) -> None:
        """Initialize the formatter with TTY-aware color state.

        Args:
            prog: Program name reported by argparse.
            indent_increment: Indentation applied to nested help blocks.
            max_help_position: Column where help descriptions begin.
            width: Optional target line width.
        """
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
        """Start a help section, styling the heading when appropriate."""
        if heading and self._color:
            heading = style_heading(heading, True)
        super().start_section(heading)

    def add_text(self, text: str | None) -> None:
        """Add description or epilog text with optional styling."""
        if text and self._color:
            text = style_description(text, True)
        super().add_text(text)


class ColoredArgumentParser(argparse.ArgumentParser):
    """Argument parser that applies the custom formatter and banner output."""

    def __init__(self, *args, **kwargs) -> None:
        """Initialize the parser while disabling argparse's built-in color theme."""
        # Disable CPython 3.14+ built-in argparse theme so we do not double-style.
        if "color" in inspect.signature(argparse.ArgumentParser.__init__).parameters:
            kwargs["color"] = False
        super().__init__(*args, **kwargs)

    def print_help(self, file: TextIO | None = None) -> None:
        """Print the banner followed by argparse's standard help output."""
        if file is None:
            file = sys.stdout
        self._print_message(blauw_zwart_banner(color=use_color(file)), file)
        super().print_help(file)

    def error(self, message: str) -> None:
        """Print a styled usage block and exit with argparse's error code."""
        self.print_usage(sys.stderr)
        c = use_color(sys.stderr)
        msg = style_error_message(message, c)
        self.exit(2, _("%(prog)s: error: %(message)s\n") % {"prog": self.prog, "message": msg})
