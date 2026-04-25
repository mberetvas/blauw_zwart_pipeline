"""Unit tests for proleague_scraper.app Flask endpoints."""

from __future__ import annotations

from typing import Any

import pytest

from proleague_scraper import app as app_module


@pytest.fixture()
def client():
    app_module.app.config.update(TESTING=True)
    return app_module.app.test_client()


# ---------------------------------------------------------------------------
# /health
# ---------------------------------------------------------------------------


def test_health_endpoint(client) -> None:
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.get_json() == {"status": "ok"}


# ---------------------------------------------------------------------------
# /squad
# ---------------------------------------------------------------------------


def test_squad_uses_default_url(monkeypatch: pytest.MonkeyPatch, client) -> None:
    captured: dict[str, Any] = {}

    def fake_load(url: str) -> dict[str, Any]:
        captured["url"] = url
        return {"source_url": url, "fetched_at": None, "cached": True, "players": []}

    monkeypatch.setattr(app_module, "_db_load_squad", fake_load)
    resp = client.get("/squad")
    assert resp.status_code == 200
    assert captured["url"] == app_module.DEFAULT_SQUAD_URL
    assert resp.get_json()["players"] == []


def test_squad_passes_through_url_param(monkeypatch: pytest.MonkeyPatch, client) -> None:
    monkeypatch.setattr(
        app_module,
        "_db_load_squad",
        lambda url: {"source_url": url, "fetched_at": "ts", "cached": True, "players": [{"x": 1}]},
    )
    resp = client.get("/squad?url=https://example.test/squad")
    body = resp.get_json()
    assert body["source_url"] == "https://example.test/squad"
    assert body["players"] == [{"x": 1}]


# ---------------------------------------------------------------------------
# /player
# ---------------------------------------------------------------------------


def test_player_requires_url_param(client) -> None:
    resp = client.get("/player")
    assert resp.status_code == 400
    assert "url query parameter" in resp.get_json()["error"]


def test_player_calls_scraper(monkeypatch: pytest.MonkeyPatch, client) -> None:
    monkeypatch.setattr(
        app_module,
        "scrape_player",
        lambda url: {"player_id": "p1", "name": "Alice", "source_url": url},
    )
    resp = client.get("/player?url=https://example.test/p/alice")
    assert resp.status_code == 200
    assert resp.get_json()["player_id"] == "p1"


def test_player_returns_502_on_scrape_failure(monkeypatch: pytest.MonkeyPatch, client) -> None:
    def boom(url: str) -> dict[str, Any]:
        raise RuntimeError("network down")

    monkeypatch.setattr(app_module, "scrape_player", boom)
    resp = client.get("/player?url=https://example.test/p/alice")
    assert resp.status_code == 502
    assert "Failed to fetch" in resp.get_json()["error"]


# ---------------------------------------------------------------------------
# _db_load_squad — DB failure path returns empty squad
# ---------------------------------------------------------------------------


def test_db_load_squad_handles_db_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_get_connection() -> Any:
        raise RuntimeError("DB unreachable")

    # The function imports lazily inside the body, so patch the source module.
    from proleague_scraper import db as scraper_db

    monkeypatch.setattr(scraper_db, "get_connection", fake_get_connection)
    out = app_module._db_load_squad("https://example.test/squad")
    assert out == {
        "source_url": "https://example.test/squad",
        "fetched_at": None,
        "cached": True,
        "players": [],
    }


def test_db_load_squad_returns_empty_when_count_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    from proleague_scraper import db as scraper_db

    class _Conn:
        def close(self) -> None:
            pass

    monkeypatch.setattr(scraper_db, "get_connection", lambda: _Conn())
    monkeypatch.setattr(scraper_db, "count_players", lambda conn: 0)
    monkeypatch.setattr(scraper_db, "get_players", lambda conn: [])

    out = app_module._db_load_squad("https://example.test/squad")
    assert out["players"] == []
    assert out["fetched_at"] is None


def test_db_load_squad_returns_players_with_latest_timestamp(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from proleague_scraper import db as scraper_db

    class _Conn:
        def close(self) -> None:
            pass

    players = [
        {"player_id": "p1", "scraped_at": "2026-04-24T10:00:00"},
        {"player_id": "p2", "scraped_at": "2026-04-25T12:00:00"},
    ]
    monkeypatch.setattr(scraper_db, "get_connection", lambda: _Conn())
    monkeypatch.setattr(scraper_db, "count_players", lambda conn: 2)
    monkeypatch.setattr(scraper_db, "get_players", lambda conn: players)

    out = app_module._db_load_squad("https://example.test/squad")
    assert out["fetched_at"] == "2026-04-25T12:00:00"
    assert len(out["players"]) == 2
