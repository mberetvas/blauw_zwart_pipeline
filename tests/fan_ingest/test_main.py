"""Unit tests for fan_ingest.main argparse + entrypoint wiring."""

from __future__ import annotations

import argparse
import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from fan_ingest import main as main_mod

# ---------------------------------------------------------------------------
# argument parser
# ---------------------------------------------------------------------------


def test_arg_parser_uses_defaults_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KAFKA_BOOTSTRAP_SERVERS", "broker:29092")
    monkeypatch.setenv("KAFKA_TOPIC", "fan_events")
    monkeypatch.setenv("KAFKA_CONSUMER_GROUP", "fan-ingest-local")
    monkeypatch.setenv("DATABASE_URL", "postgresql://x/y")

    args = main_mod._build_arg_parser().parse_args([])
    assert args.kafka_bootstrap_servers == "broker:29092"
    assert args.kafka_topic == "fan_events"
    assert args.kafka_consumer_group == "fan-ingest-local"
    assert args.database_url == "postgresql://x/y"


def test_arg_parser_cli_overrides_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KAFKA_TOPIC", "fan_events")
    args = main_mod._build_arg_parser().parse_args(["--kafka-topic", "alt"])
    assert args.kafka_topic == "alt"


def test_env_or_default_returns_default_when_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("__BOGUS_VAR__", raising=False)
    assert main_mod._env_or_default("__BOGUS_VAR__", "fallback") == "fallback"


def test_env_or_default_treats_empty_as_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("__BOGUS_VAR__", "")
    assert main_mod._env_or_default("__BOGUS_VAR__", "fallback") == "fallback"


def test_consumer_config_shape() -> None:
    args = argparse.Namespace(
        kafka_bootstrap_servers="b:1",
        kafka_consumer_group="g",
        kafka_topic="t",
        database_url="x",
    )
    conf = main_mod._consumer_config(args)
    assert conf["bootstrap.servers"] == "b:1"
    assert conf["group.id"] == "g"
    assert conf["enable.auto.commit"] is False
    assert conf["auto.offset.reset"] == "earliest"


# ---------------------------------------------------------------------------
# _async_main — DATABASE_URL guard
# ---------------------------------------------------------------------------


def test_async_main_requires_database_url() -> None:
    args = argparse.Namespace(
        kafka_bootstrap_servers="b:1",
        kafka_consumer_group="g",
        kafka_topic="t",
        database_url="",
    )
    with pytest.raises(SystemExit, match=r"DATABASE_URL"):
        asyncio.run(main_mod._async_main(args))


# ---------------------------------------------------------------------------
# _async_main — happy path with stop event signalled
# ---------------------------------------------------------------------------


def test_async_main_starts_runtime_and_stops_cleanly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pool = MagicMock()
    pool.close = AsyncMock()

    async def fake_create_pool(url: str) -> Any:
        return pool

    consumer = MagicMock()
    consumer.subscribe = MagicMock()
    monkeypatch.setattr(main_mod, "create_pool", fake_create_pool)
    monkeypatch.setattr(main_mod, "Consumer", lambda conf: consumer)

    runtime_instance = MagicMock()

    def make_runtime(*args: Any, **kwargs: Any) -> MagicMock:
        # Trigger stop as soon as the runtime starts so _async_main returns.
        runtime_instance.start.side_effect = lambda: None
        return runtime_instance

    monkeypatch.setattr(main_mod, "IngestRuntime", make_runtime)

    # Patch asyncio.Event so we can resolve it immediately.
    real_event = asyncio.Event

    class InstantEvent(real_event):
        async def wait(self) -> bool:
            self.set()
            return True

    monkeypatch.setattr(main_mod.asyncio, "Event", InstantEvent)

    args = argparse.Namespace(
        kafka_bootstrap_servers="b:1",
        kafka_consumer_group="g",
        kafka_topic="t",
        database_url="postgresql://x/y",
    )
    asyncio.run(main_mod._async_main(args))

    consumer.subscribe.assert_called_once_with(["t"])
    runtime_instance.start.assert_called_once()
    runtime_instance.stop.assert_called_once()
    runtime_instance.join.assert_called_once()
    pool.close.assert_awaited()


# ---------------------------------------------------------------------------
# main() — exit code on KeyboardInterrupt
# ---------------------------------------------------------------------------


def test_main_handles_keyboard_interrupt(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(main_mod, "_build_arg_parser", lambda: _ParserStub())

    def boom(coro: Any) -> None:
        # Drain coroutine to avoid "coroutine was never awaited" warning.
        coro.close()
        raise KeyboardInterrupt

    monkeypatch.setattr(main_mod.asyncio, "run", boom)

    with pytest.raises(SystemExit) as excinfo:
        main_mod.main()
    assert excinfo.value.code == 130


class _ParserStub:
    def parse_args(self) -> argparse.Namespace:
        return argparse.Namespace(
            kafka_bootstrap_servers="b:1",
            kafka_consumer_group="g",
            kafka_topic="t",
            database_url="postgresql://x/y",
        )
