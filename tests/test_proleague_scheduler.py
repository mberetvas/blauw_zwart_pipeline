"""Unit tests for proleague_scraper.scheduler — no network, no Kafka broker required."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from proleague_scraper.scheduler import _EVENT_TYPE, _SCHEMA_VERSION, build_envelope, run_once

# ---------------------------------------------------------------------------
# build_envelope
# ---------------------------------------------------------------------------


def _sample_player(player_id: str = "3219") -> dict:
    return {
        "player_id": player_id,
        "slug": f"simon-mignolet-{player_id}",
        "name": "Simon Mignolet",
        "position": "Goalkeeper",
        "field_position": "GK",
        "shirt_number": 1,
        "image_url": "https://imagecache.proleague.be/mignolet.jpg",
        "profile": {"height_cm": 193, "preferred_foot": "Right"},
        "stats": [{"key": "savesMade", "label": "Saves", "value": 72}],
        "competition": "Jupiler Pro League",
    }


class TestBuildEnvelope:
    def test_returns_bytes(self):
        raw = build_envelope(
            _sample_player(),
            source_url="https://example.com",
            scraped_at="2026-01-01T00:00:00Z",
        )
        assert isinstance(raw, bytes)

    def test_valid_json(self):
        raw = build_envelope(
            _sample_player(),
            source_url="https://x.be",
            scraped_at="2026-01-01T00:00:00Z",
        )
        obj = json.loads(raw.decode())
        assert isinstance(obj, dict)

    def test_schema_version(self):
        raw = build_envelope(
            _sample_player(),
            source_url="https://x.be",
            scraped_at="2026-01-01T00:00:00Z",
        )
        obj = json.loads(raw)
        assert obj["_schema_version"] == _SCHEMA_VERSION

    def test_event_type(self):
        raw = build_envelope(
            _sample_player(),
            source_url="https://x.be",
            scraped_at="2026-01-01T00:00:00Z",
        )
        obj = json.loads(raw)
        assert obj["event_type"] == _EVENT_TYPE

    def test_player_embedded(self):
        player = _sample_player("9999")
        raw = build_envelope(player, source_url="https://x.be", scraped_at="2026-01-01T00:00:00Z")
        obj = json.loads(raw)
        assert obj["player"]["player_id"] == "9999"
        assert obj["player"]["name"] == "Simon Mignolet"

    def test_source_url_and_scraped_at_preserved(self):
        raw = build_envelope(
            _sample_player(),
            source_url="https://www.proleague.be/teams/club-brugge-kv-182/squad",
            scraped_at="2026-04-13T21:00:00Z",
        )
        obj = json.loads(raw)
        assert obj["source_url"] == "https://www.proleague.be/teams/club-brugge-kv-182/squad"
        assert obj["scraped_at"] == "2026-04-13T21:00:00Z"

    def test_utf8_name_round_trips(self):
        player = _sample_player()
        player["name"] = "Cédric Bruneel"
        raw = build_envelope(player, source_url="", scraped_at="")
        obj = json.loads(raw.decode("utf-8"))
        assert obj["player"]["name"] == "Cédric Bruneel"


# ---------------------------------------------------------------------------
# run_once
# ---------------------------------------------------------------------------


def _make_squad_result(players: list[dict]) -> dict:
    return {
        "source_url": "https://www.proleague.be/teams/club-brugge-kv-182/squad",
        "fetched_at": "2026-04-13T21:00:00Z",
        "players": players,
    }


class TestRunOnce:
    def _run(self, players: list[dict]) -> tuple[int, MagicMock]:
        """Helper: call run_once with mocked scrape + producer; return (count, producer_mock)."""
        squad_result = _make_squad_result(players)
        mock_producer = MagicMock()
        mock_producer.flush.return_value = 0

        with (
            patch("proleague_scraper.scheduler.scrape_squad", return_value=squad_result),
            patch("proleague_scraper.scheduler.Producer", return_value=mock_producer),
        ):
            count = run_once(
                squad_url="https://www.proleague.be/teams/club-brugge-kv-182/squad",
                bootstrap_servers="broker:29092",
                topic="player_stats",
            )
        return count, mock_producer

    def test_produces_one_message_per_valid_player(self):
        players = [_sample_player("1"), _sample_player("2"), _sample_player("3")]
        count, producer = self._run(players)
        assert count == 3
        assert producer.produce.call_count == 3

    def test_skips_players_without_player_id(self):
        players = [_sample_player("1"), {"name": "Unknown", "slug": "x"}]
        count, _ = self._run(players)
        assert count == 1

    def test_skips_error_players(self):
        players = [_sample_player("1"), {"player_id": "2", "error": "fetch failed"}]
        count, _ = self._run(players)
        assert count == 1

    def test_produce_key_is_player_id(self):
        players = [_sample_player("3219")]
        _, producer = self._run(players)
        _, kwargs = producer.produce.call_args
        assert kwargs["key"] == b"3219"

    def test_produce_topic_correct(self):
        _, producer = self._run([_sample_player("1")])
        _, kwargs = producer.produce.call_args
        assert kwargs["topic"] == "player_stats"

    def test_produce_value_is_valid_envelope(self):
        _, producer = self._run([_sample_player("1")])
        _, kwargs = producer.produce.call_args
        value = kwargs["value"]
        obj = json.loads(value.decode())
        assert obj["_schema_version"] == _SCHEMA_VERSION
        assert obj["player"]["player_id"] == "1"

    def test_flush_called(self):
        _, producer = self._run([_sample_player("1")])
        producer.flush.assert_called_once()

    def test_produce_error_does_not_raise(self):
        from confluent_kafka import KafkaException

        players = [_sample_player("1")]
        squad_result = _make_squad_result(players)
        mock_producer = MagicMock()
        mock_producer.produce.side_effect = KafkaException("simulated error")
        mock_producer.flush.return_value = 0

        with (
            patch("proleague_scraper.scheduler.scrape_squad", return_value=squad_result),
            patch("proleague_scraper.scheduler.Producer", return_value=mock_producer),
        ):
            count = run_once(
                squad_url="https://x.be",
                bootstrap_servers="broker:29092",
                topic="player_stats",
            )
        assert count == 0  # failed to enqueue but no exception raised

    def test_scrape_failure_propagates(self):
        with (
            patch("proleague_scraper.scheduler.scrape_squad", side_effect=RuntimeError("timeout")),
            patch("proleague_scraper.scheduler.Producer"),
        ):
            with pytest.raises(RuntimeError, match="timeout"):
                run_once(
                    squad_url="https://x.be",
                    bootstrap_servers="broker:29092",
                    topic="player_stats",
                )

    def test_empty_squad_produces_zero_messages(self):
        count, producer = self._run([])
        assert count == 0
        producer.produce.assert_not_called()
