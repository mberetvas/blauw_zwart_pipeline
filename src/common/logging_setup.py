"""Central Loguru-based logging configuration for all services."""

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
    """Register a callable that returns the current request ID."""
    global _REQ_ID_GETTER
    _REQ_ID_GETTER = getter


def _normalize_level(level_name: str) -> str:
    if level_name.strip().upper() == "DEBUG":
        return "DEBUG"
    return "INFO"


def _current_req_id() -> str:
    if _REQ_ID_GETTER is None:
        return "-"
    try:
        value = _REQ_ID_GETTER()
    except Exception:  # noqa: BLE001
        return "-"
    return value or "-"


def _record_patcher(record: dict) -> None:
    extra = record["extra"]
    extra.setdefault("req_id", _current_req_id())
    extra.setdefault("source", record["name"])


class _InterceptHandler(logging.Handler):
    """Route stdlib logging records through Loguru."""

    def emit(self, record: logging.LogRecord) -> None:
        level_name = record.levelname.upper()
        if level_name not in _ALLOWED_LEVELS:
            level_name = "INFO"
            message = f"[{record.levelname}] {record.getMessage()}"
        else:
            message = record.getMessage()
        logger.bind(source=record.name).opt(exception=record.exc_info, depth=6).log(
            level_name, message
        )


def configure_logging(level: str | None = None, *, use_colors: bool = True) -> None:
    """Configure Loguru once per process and intercept stdlib logging."""
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
    """Return a contextualized Loguru logger with a stable source field."""
    return logger.bind(source=name)


__all__ = ["configure_logging", "get_logger", "register_request_id_getter"]

