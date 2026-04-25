from __future__ import annotations

import logging

from common.logging_setup import configure_logging, get_logger, register_request_id_getter


def test_configure_logging_intercepts_stdlib_and_normalizes_level(capsys) -> None:
    configure_logging(level="INFO", use_colors=False)
    std_logger = logging.getLogger("tests.logging_setup")

    std_logger.warning("warning from stdlib")
    std_logger.debug("debug should be hidden at info level")

    output = capsys.readouterr().err
    assert "tests.logging_setup" in output
    assert "[WARNING] warning from stdlib" in output
    assert "debug should be hidden at info level" not in output


def test_configure_logging_injects_request_id(capsys) -> None:
    configure_logging(level="DEBUG", use_colors=False)
    register_request_id_getter(lambda: "req-1234")
    log = get_logger("tests.reqid")

    log.info("request scoped line")

    output = capsys.readouterr().err
    assert "req-1234" in output
    assert "tests.reqid" in output
    assert "request scoped line" in output
