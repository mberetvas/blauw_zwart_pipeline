"""Unit tests for proleague_ingest.consumer.parse_envelope — no Kafka broker required."""

from __future__ import annotations

import json

import pytest

from proleague_ingest.consumer import parse_envelope


def _make_raw(overrides: dict | None = None) -> bytes:
    """Build a minimal valid v1 envelope as raw bytes."""
    base = {
        "_schema_version": 1,
        "event_type": "player_stats_scraped",
        "source_url": "https://www.proleague.be/teams/club-brugge-kv-182/squad",
        "scraped_at": "2026-04-13T21:00:00Z",
        "player": {
            "player_id": "3219",
            "slug": "simon-mignolet-3219",
            "name": "Simon Mignolet",
            "position": "Goalkeeper",
            "field_position": "GK",
            "shirt_number": 1,
            "image_url": "https://imagecache.proleague.be/mignolet.jpg",
            "profile": {"height_cm": 193},
            "stats": [{"key": "savesMade", "label": "Saves", "value": 72}],
            "competition": "Jupiler Pro League",
        },
    }
    if overrides:
        base.update(overrides)
    return json.dumps(base).encode("utf-8")


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


class TestParseEnvelopeHappyPath:
    def test_returns_dict(self):
        result = parse_envelope(_make_raw())
        assert isinstance(result, dict)

    def test_schema_version_present(self):
        result = parse_envelope(_make_raw())
        assert result["_schema_version"] == 1

    def test_player_id_accessible(self):
        result = parse_envelope(_make_raw())
        assert result["player"]["player_id"] == "3219"

    def test_player_name_accessible(self):
        result = parse_envelope(_make_raw())
        assert result["player"]["name"] == "Simon Mignolet"

    def test_source_url_preserved(self):
        result = parse_envelope(_make_raw())
        assert "proleague.be" in result["source_url"]

    def test_scraped_at_preserved(self):
        result = parse_envelope(_make_raw())
        assert result["scraped_at"] == "2026-04-13T21:00:00Z"


# ---------------------------------------------------------------------------
# Validation failures — all must raise ValueError
# ---------------------------------------------------------------------------


class TestParseEnvelopeValidation:
    def test_empty_bytes_raises(self):
        with pytest.raises(ValueError, match="JSON decode error"):
            parse_envelope(b"")

    def test_invalid_utf8_raises(self):
        with pytest.raises(ValueError, match="JSON decode error"):
            parse_envelope(b"\xff\xfe{bad}")

    def test_non_json_raises(self):
        with pytest.raises(ValueError, match="JSON decode error"):
            parse_envelope(b"not json at all")

    def test_json_array_raises(self):
        with pytest.raises(ValueError, match="expected JSON object"):
            parse_envelope(b"[1, 2, 3]")

    def test_wrong_schema_version_raises(self):
        raw = _make_raw({"_schema_version": 99})
        with pytest.raises(ValueError, match="unsupported _schema_version"):
            parse_envelope(raw)

    def test_missing_schema_version_raises(self):
        obj = json.loads(_make_raw())
        del obj["_schema_version"]
        with pytest.raises(ValueError, match="unsupported _schema_version"):
            parse_envelope(json.dumps(obj).encode())

    def test_wrong_event_type_raises(self):
        raw = _make_raw({"event_type": "fan_purchase"})
        with pytest.raises(ValueError, match="unexpected event_type"):
            parse_envelope(raw)

    def test_missing_player_raises(self):
        obj = json.loads(_make_raw())
        del obj["player"]
        with pytest.raises(ValueError, match="missing or invalid 'player'"):
            parse_envelope(json.dumps(obj).encode())

    def test_player_without_player_id_raises(self):
        obj = json.loads(_make_raw())
        del obj["player"]["player_id"]
        with pytest.raises(ValueError, match="missing or invalid 'player'"):
            parse_envelope(json.dumps(obj).encode())

    def test_player_with_empty_player_id_raises(self):
        obj = json.loads(_make_raw())
        obj["player"]["player_id"] = ""
        with pytest.raises(ValueError, match="missing or invalid 'player'"):
            parse_envelope(json.dumps(obj).encode())

    def test_player_not_a_dict_raises(self):
        obj = json.loads(_make_raw())
        obj["player"] = "just-a-string"
        with pytest.raises(ValueError, match="missing or invalid 'player'"):
            parse_envelope(json.dumps(obj).encode())


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestParseEnvelopeEdgeCases:
    def test_unicode_name_round_trips(self):
        obj = json.loads(_make_raw())
        obj["player"]["name"] = "Cédric Bruneel"
        result = parse_envelope(json.dumps(obj, ensure_ascii=False).encode("utf-8"))
        assert result["player"]["name"] == "Cédric Bruneel"

    def test_extra_fields_ignored(self):
        obj = json.loads(_make_raw())
        obj["unexpected_field"] = "ignored"
        result = parse_envelope(json.dumps(obj).encode())
        assert result["_schema_version"] == 1

    def test_optional_source_url_missing_ok(self):
        obj = json.loads(_make_raw())
        del obj["source_url"]
        result = parse_envelope(json.dumps(obj).encode())
        assert result.get("source_url") is None
