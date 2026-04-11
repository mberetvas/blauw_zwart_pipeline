"""Unit tests for IngestRuntime: commit semantics, parse-skip, worker-failure supervision."""

from __future__ import annotations

import asyncio
import threading
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from fan_ingest.runner import IngestRuntime


def _make_msg(
    *,
    topic: str = "fan_events",
    partition: int = 0,
    offset: int = 0,
    value: bytes | None = b'{"event":"ticket_scan","timestamp":"2024-01-01T00:00:00Z"}',
) -> MagicMock:
    msg = MagicMock()
    msg.error.return_value = None
    msg.topic.return_value = topic
    msg.partition.return_value = partition
    msg.offset.return_value = offset
    msg.value.return_value = value
    return msg


def _make_runtime(
    *,
    loop: asyncio.AbstractEventLoop,
    poll_side_effect: list,
) -> tuple[IngestRuntime, MagicMock, AsyncMock]:
    """Build an IngestRuntime with mocked Consumer + Pool."""
    consumer = MagicMock()
    # poll() returns items from poll_side_effect, then blocks forever (stops via _stop)
    poll_iter = iter(poll_side_effect)

    def _poll(timeout: float) -> MagicMock | None:
        try:
            return next(poll_iter)
        except StopIteration:
            time.sleep(timeout)
            return None

    consumer.poll.side_effect = _poll
    consumer.commit = MagicMock()

    pool = AsyncMock()
    pool.fetchval = AsyncMock(return_value=1)  # successful insert

    runtime = IngestRuntime(loop=loop, pool=pool, consumer=consumer, topic="fan_events")
    return runtime, consumer, pool


def _run_until_idle(
    runtime: IngestRuntime,
    *,
    idle_seconds: float = 0.5,
    timeout: float = 5.0,
) -> None:
    """Start runtime, let it drain messages, then stop it."""
    runtime.start()
    time.sleep(idle_seconds)
    runtime.stop()
    runtime.join(timeout=timeout)


# ──────────────────────────────────────────────────────────────────────────────
# commit-after-insert
# ──────────────────────────────────────────────────────────────────────────────


def test_commit_called_after_successful_insert() -> None:
    loop = asyncio.new_event_loop()
    loop_thread = threading.Thread(target=loop.run_forever, daemon=True)
    loop_thread.start()
    try:
        msg = _make_msg(offset=10)
        runtime, consumer, pool = _make_runtime(loop=loop, poll_side_effect=[msg])
        _run_until_idle(runtime)

        pool.fetchval.assert_awaited()
        consumer.commit.assert_called_once_with(msg, asynchronous=False)
    finally:
        loop.call_soon_threadsafe(loop.stop)
        loop_thread.join(timeout=3)
        loop.close()


# ──────────────────────────────────────────────────────────────────────────────
# commit-after-parse-skip
# ──────────────────────────────────────────────────────────────────────────────


def test_commit_called_after_parse_skip_no_insert() -> None:
    loop = asyncio.new_event_loop()
    loop_thread = threading.Thread(target=loop.run_forever, daemon=True)
    loop_thread.start()
    try:
        bad_msg = _make_msg(offset=7, value=b"{bad json")
        runtime, consumer, pool = _make_runtime(loop=loop, poll_side_effect=[bad_msg])
        _run_until_idle(runtime)

        # Offset must be committed (so consumption advances) even for bad messages.
        consumer.commit.assert_called_once_with(bad_msg, asynchronous=False)
        # No DB insert should have been attempted.
        pool.fetchval.assert_not_awaited()
    finally:
        loop.call_soon_threadsafe(loop.stop)
        loop_thread.join(timeout=3)
        loop.close()


def test_parse_skip_log_includes_error_detail(caplog: pytest.LogCaptureFixture) -> None:
    import logging

    loop = asyncio.new_event_loop()
    loop_thread = threading.Thread(target=loop.run_forever, daemon=True)
    loop_thread.start()
    try:
        bad_msg = _make_msg(value=b"[1,2,3]")
        runtime, consumer, pool = _make_runtime(loop=loop, poll_side_effect=[bad_msg])
        with caplog.at_level(logging.WARNING, logger="fan_ingest.runner"):
            _run_until_idle(runtime)

        assert any("ingest_parse_skip" in r.message and "error=" in r.message for r in caplog.records)
    finally:
        loop.call_soon_threadsafe(loop.stop)
        loop_thread.join(timeout=3)
        loop.close()


# ──────────────────────────────────────────────────────────────────────────────
# worker-failure supervision
# ──────────────────────────────────────────────────────────────────────────────


def test_worker_failure_sets_stop_flag(caplog: pytest.LogCaptureFixture) -> None:
    """If insert_fan_event_row raises, the worker task fails and _stop is set."""
    import logging

    loop = asyncio.new_event_loop()
    loop_thread = threading.Thread(target=loop.run_forever, daemon=True)
    loop_thread.start()
    try:
        msg = _make_msg(offset=5)
        consumer = MagicMock()
        # After the first message, always return None (no StopIteration)
        call_count = [0]

        def _poll(timeout: float) -> MagicMock | None:
            call_count[0] += 1
            if call_count[0] == 1:
                return msg
            time.sleep(timeout)
            return None

        consumer.poll.side_effect = _poll
        consumer.commit = MagicMock()

        pool = AsyncMock()
        pool.fetchval = AsyncMock(side_effect=RuntimeError("db down"))

        runtime = IngestRuntime(loop=loop, pool=pool, consumer=consumer, topic="fan_events")
        with caplog.at_level(logging.CRITICAL, logger="fan_ingest.runner"):
            runtime.start()
            # Allow time for the worker failure to propagate
            runtime.join(timeout=4.0)

        assert runtime._stop.is_set(), "_stop should be set after worker failure"
        assert any(
            "partition_worker_failed" in r.message for r in caplog.records
        ), "Expected critical log for worker failure"
    finally:
        loop.call_soon_threadsafe(loop.stop)
        loop_thread.join(timeout=3)
        loop.close()
