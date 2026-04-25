"""Phase 3 branch-fill tests for run_consumer (proleague_ingest)."""

from __future__ import annotations

import json
import signal
from typing import Any
from unittest.mock import MagicMock

import pytest

from proleague_ingest import consumer as consumer_mod


def _envelope_bytes(player_id: str = "p1") -> bytes:
    return json.dumps(
        {
            "_schema_version": 1,
            "event_type": "player_stats_scraped",
            "source_url": "https://example.test/squad",
            "scraped_at": "2026-04-25T00:00:00Z",
            "player": {"player_id": player_id, "name": "Alice"},
        }
    ).encode("utf-8")


def _msg(value: bytes | None = None, error=None) -> MagicMock:
    m = MagicMock()
    m.error.return_value = error
    m.topic.return_value = "player_stats"
    m.partition.return_value = 0
    m.offset.return_value = 7
    m.value.return_value = value
    return m


@pytest.fixture()
def patched_consumer(monkeypatch: pytest.MonkeyPatch):
    """Stub Consumer factory + signal.signal + psycopg2.connect."""
    fake_consumer = MagicMock()
    fake_consumer.subscribe = MagicMock()
    fake_consumer.commit = MagicMock()
    fake_consumer.close = MagicMock()

    monkeypatch.setattr(consumer_mod, "Consumer", lambda conf: fake_consumer)
    # No-op signal handlers so test runner doesn't trap them.
    monkeypatch.setattr(consumer_mod.signal, "signal", lambda *_a, **_kw: None)

    # Fake DB connection.
    fake_conn = MagicMock()
    fake_conn.closed = False
    fake_conn.close = MagicMock()
    monkeypatch.setattr(consumer_mod, "_connect", lambda url: fake_conn)

    return fake_consumer, fake_conn


def test_run_consumer_processes_one_message_and_commits(
    patched_consumer, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_consumer, fake_conn = patched_consumer
    upserts: list[Any] = []
    monkeypatch.setattr(
        consumer_mod, "upsert_players", lambda conn, players, src, ts: upserts.append(players)
    )

    # poll() returns: a real msg, then None to drain — but we'll trigger stop after first commit.
    poll_seq: list = [_msg(_envelope_bytes("alice"))]
    # poll() returns the queued message once; after commit we explicitly stop
    # the consumer by swapping poll.side_effect to raise KafkaException.
    poll_seq: list = [_msg(_envelope_bytes("alice"))]

    def poll(timeout: float):
        return poll_seq.pop(0)

    fake_consumer.poll.side_effect = poll

    # Break the loop after the first successful commit by making the next poll
    # raise, which exercises the consumer's shutdown path explicitly.
    def commit(msg, asynchronous):
        from confluent_kafka import KafkaException

        fake_consumer.poll.side_effect = KafkaException("stop")

    fake_consumer.commit.side_effect = commit

    consumer_mod.run_consumer(
        bootstrap_servers="b:1",
        topic="player_stats",
        consumer_group="g",
        database_url="postgresql://x/y",
    )

    assert upserts and upserts[0][0]["player_id"] == "alice"
    fake_consumer.subscribe.assert_called_once_with(["player_stats"])
    fake_consumer.close.assert_called_once()
    fake_conn.close.assert_called()


def test_run_consumer_skips_invalid_message_and_commits(
    patched_consumer, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_consumer, _ = patched_consumer
    monkeypatch.setattr(
        consumer_mod, "upsert_players", lambda *a, **kw: pytest.fail("must not upsert")
    )

    fake_consumer.poll.side_effect = [_msg(b"not json")]

    def commit(msg, asynchronous):
        from confluent_kafka import KafkaException

        fake_consumer.poll.side_effect = KafkaException("stop")

    fake_consumer.commit.side_effect = commit

    consumer_mod.run_consumer(
        bootstrap_servers="b:1",
        topic="player_stats",
        consumer_group="g",
        database_url="postgresql://x/y",
    )

    fake_consumer.commit.assert_called_once()


def test_run_consumer_skips_partition_eof_silently(
    patched_consumer, monkeypatch: pytest.MonkeyPatch
) -> None:
    from confluent_kafka import KafkaError, KafkaException

    fake_consumer, _ = patched_consumer
    monkeypatch.setattr(consumer_mod, "upsert_players", lambda *a, **kw: None)

    eof_err = MagicMock()
    eof_err.code.return_value = KafkaError._PARTITION_EOF
    eof_msg = _msg(error=eof_err)

    fake_consumer.poll.side_effect = [eof_msg, KafkaException("stop")]

    consumer_mod.run_consumer(
        bootstrap_servers="b:1",
        topic="player_stats",
        consumer_group="g",
        database_url="postgresql://x/y",
    )

    fake_consumer.commit.assert_not_called()


def test_run_consumer_logs_other_consumer_errors(
    patched_consumer, monkeypatch: pytest.MonkeyPatch
) -> None:
    from confluent_kafka import KafkaException

    fake_consumer, _ = patched_consumer

    other_err = MagicMock()
    other_err.code.return_value = -42  # not _PARTITION_EOF
    err_msg = _msg(error=other_err)

    fake_consumer.poll.side_effect = [err_msg, KafkaException("stop")]

    consumer_mod.run_consumer(
        bootstrap_servers="b:1",
        topic="player_stats",
        consumer_group="g",
        database_url="postgresql://x/y",
    )

    fake_consumer.close.assert_called_once()


def test_run_consumer_handles_db_failure_resets_connection(
    patched_consumer, monkeypatch: pytest.MonkeyPatch
) -> None:
    from confluent_kafka import KafkaException

    fake_consumer, _ = patched_consumer
    monkeypatch.setattr(consumer_mod, "time", MagicMock())  # no real sleep

    def boom(conn, players, source_url, scraped_at):
        # First (and only) upsert raises.
        raise RuntimeError("db down")

    monkeypatch.setattr(consumer_mod, "upsert_players", boom)

    fake_consumer.poll.side_effect = [_msg(_envelope_bytes("p1")), KafkaException("stop")]

    consumer_mod.run_consumer(
        bootstrap_servers="b:1",
        topic="player_stats",
        consumer_group="g",
        database_url="postgresql://x/y",
    )

    fake_consumer.close.assert_called_once()


def test_run_consumer_registers_signal_handlers(
    patched_consumer, monkeypatch: pytest.MonkeyPatch
) -> None:
    from confluent_kafka import KafkaException

    fake_consumer, _ = patched_consumer
    monkeypatch.setattr(consumer_mod, "upsert_players", lambda *a, **kw: None)

    registered: list[int] = []

    def fake_signal(signum, handler):
        registered.append(signum)

    monkeypatch.setattr(consumer_mod.signal, "signal", fake_signal)

    fake_consumer.poll.side_effect = [KafkaException("stop")]

    consumer_mod.run_consumer(
        bootstrap_servers="b:1",
        topic="player_stats",
        consumer_group="g",
        database_url="postgresql://x/y",
    )

    assert signal.SIGINT in registered
    assert signal.SIGTERM in registered
