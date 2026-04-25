"""Unit tests for proleague_ingest.main entrypoint."""

from __future__ import annotations

from typing import Any

import pytest

from proleague_ingest import main as main_mod


def test_env_returns_default_when_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("__BOGUS__", raising=False)
    assert main_mod._env("__BOGUS__", "fallback") == "fallback"


def test_env_treats_empty_as_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("__BOGUS__", "")
    assert main_mod._env("__BOGUS__", "fallback") == "fallback"


def test_env_returns_set_value(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("__BOGUS__", "value")
    assert main_mod._env("__BOGUS__", "fallback") == "value"


def test_main_exits_when_database_url_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr(main_mod, "run_consumer", lambda **_: pytest.fail("must not run"))

    with pytest.raises(SystemExit) as excinfo:
        main_mod.main()
    assert excinfo.value.code == 1


def test_main_invokes_run_consumer_with_env_config(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql://w/x")
    monkeypatch.setenv("KAFKA_BOOTSTRAP_SERVERS", "broker:29092")
    monkeypatch.setenv("SCRAPER_KAFKA_TOPIC", "player_stats")
    monkeypatch.setenv("SCRAPER_KAFKA_CONSUMER_GROUP", "scraper-ingest-local")

    captured: dict[str, Any] = {}

    def fake_run(**kwargs: Any) -> None:
        captured.update(kwargs)

    monkeypatch.setattr(main_mod, "run_consumer", fake_run)
    main_mod.main()

    assert captured == {
        "bootstrap_servers": "broker:29092",
        "topic": "player_stats",
        "consumer_group": "scraper-ingest-local",
        "database_url": "postgresql://w/x",
    }


def test_main_falls_back_to_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql://w/x")
    monkeypatch.delenv("KAFKA_BOOTSTRAP_SERVERS", raising=False)
    monkeypatch.delenv("SCRAPER_KAFKA_TOPIC", raising=False)
    monkeypatch.delenv("SCRAPER_KAFKA_CONSUMER_GROUP", raising=False)

    captured: dict[str, Any] = {}
    monkeypatch.setattr(main_mod, "run_consumer", lambda **kw: captured.update(kw))

    main_mod.main()
    assert captured["bootstrap_servers"] == "broker:29092"
    assert captured["topic"] == "player_stats"
    assert captured["consumer_group"] == "scraper-ingest-local"
