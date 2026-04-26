"""Configure shared structured logging for all repository services.

This module centralizes the Loguru setup used by CLI entrypoints, Flask apps,
and background workers. It bridges standard-library ``logging`` into Loguru,
injects per-request context when available, and honors the ``LOG_LEVEL``
environment variable so operators can switch between quiet and debug-friendly
output without changing code.
"""

from __future__ import annotations

import logging
import os
import sys
from collections.abc import Callable

from loguru import logger

_REQ_ID_GETTER: Callable[[], str] | None = None
_ALLOWED_LEVELS = {"INFO", "DEBUG"}

_LOG_FORMAT = (
    "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
    "<level>{level: <5}</level> | "
    "<cyan>{extra[req_id]}</cyan> | "
    "<magenta>{extra[source]}</magenta> | "
    "<level>{message}</level>"
)


def register_request_id_getter(getter: Callable[[], str]) -> None:
    """Register a callback that returns the active request identifier.

    Args:
        getter: Zero-argument callable used to fetch the current request ID for
            log enrichment. The callback is invoked lazily for each record.
    """
    global _REQ_ID_GETTER
    _REQ_ID_GETTER = getter


def _normalize_level(level_name: str) -> str:
    """Collapse user-provided level names into the repo's supported set."""

    # Keep the contract intentionally narrow so all services emit comparable
    # logs even when callers pass arbitrary stdlib level names.
    if level_name.strip().upper() == "DEBUG":
        return "DEBUG"
    return "INFO"


def _current_req_id() -> str:
    """Return the current request ID, falling back to a placeholder."""
    if _REQ_ID_GETTER is None:
        return "-"
    try:
        value = _REQ_ID_GETTER()
    except Exception:  # noqa: BLE001
        return "-"
    return value or "-"


def _record_patcher(record: dict) -> None:
    """Populate default Loguru extras expected by the shared log format."""
    extra = record["extra"]
    extra.setdefault("req_id", _current_req_id())
    extra.setdefault("source", record["name"])


class _InterceptHandler(logging.Handler):
    """Route standard-library log records through the shared Loguru sink.

    The repo uses a single Loguru formatter for CLI apps, services, and worker
    processes. This handler lets libraries that still call ``logging`` join the
    same pipeline without each module configuring its own handlers.
    """

    def emit(self, record: logging.LogRecord) -> None:
        """Forward one stdlib log record into Loguru.

        Args:
            record: Standard-library log record produced by any library or
                service code using ``logging`` APIs.
        """
        level_name = record.levelname.upper()
        if level_name not in _ALLOWED_LEVELS:
            # Preserve unsupported level names in the message so operators do
            # not lose signal when third-party libraries log WARNING or ERROR.
            level_name = "INFO"
            message = f"[{record.levelname}] {record.getMessage()}"
        else:
            message = record.getMessage()
        logger.bind(source=record.name).opt(
            exception=record.exc_info, depth=6
        ).log(level_name, message)


def configure_logging(level: str | None = None, *, use_colors: bool = True) -> None:
    """Configure process-wide structured logging for one service instance.

    Args:
        level: Optional override for the effective log level. When omitted, the
            function falls back to ``LOG_LEVEL`` and then to ``INFO``.
        use_colors: Whether ANSI color codes should be included in the sink
            formatter, which is useful for interactive terminals but usually
            disabled in machine-collected logs.

    Note:
        This function resets existing standard-library logging handlers via
        ``logging.basicConfig(..., force=True)`` so entrypoints should call it
        once during startup rather than repeatedly throughout request handling.
    """
    resolved = _normalize_level(level or os.environ.get("LOG_LEVEL", "INFO"))

    logger.remove()
    logger.level("DEBUG", color="<blue>")
    logger.level("INFO", color="<green>")
    logger.configure(patcher=_record_patcher)
    logger.add(
        sys.stderr,
        level=resolved,
        colorize=use_colors,
        format=_LOG_FORMAT,
        backtrace=False,
        diagnose=False,
    )

    stdlib_level = logging.DEBUG if resolved == "DEBUG" else logging.INFO
    logging.basicConfig(
        handlers=[_InterceptHandler()],
        level=stdlib_level,
        force=True,
    )


def get_logger(name: str):
    """Return a Loguru logger pre-bound with a stable ``source`` field.

    Args:
        name: Source name to attach to emitted records, typically ``__name__``
            or a short subsystem label.

    Returns:
        A Loguru logger whose ``source`` extra field remains stable across all
        derived log records.
    """
    return logger.bind(source=name)


__all__ = ["configure_logging", "get_logger", "register_request_id_getter"]
