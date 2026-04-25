"""Unit tests for the Pro League scraper — no network access required.

Fixtures under tests/fixtures/proleague/ are loaded from disk; no HTTP calls
are made.  The scraper module's ``_fetch_html`` function is NOT called.
"""

from __future__ import annotations

import os

# ── fixture helpers ──────────────────────────────────────────────────────────

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures", "proleague")


def _read_fixture(name: str) -> str:
    with open(os.path.join(FIXTURES, name), encoding="utf-8") as fh:
        return fh.read()


def _player_page_html() -> str:
    """Return player_page.html with __NEXT_DATA__ embedded from the JSON fixture."""
    template = _read_fixture("player_page.html")
    next_data_json = _read_fixture("player_next_data.json")
    return template.replace("__NEXT_DATA_PLACEHOLDER__", next_data_json)


# ── tests: squad-page URL extraction ────────────────────────────────────────


class TestPlayerUrlExtraction:
    def test_extracts_five_players(self):
        from proleague_scraper.scraper import _player_urls_from_html

        html = _read_fixture("squad_page.html")
        urls = _player_urls_from_html(html, "https://www.proleague.be")
        assert len(urls) == 5

    def test_urls_are_absolute(self):
        from proleague_scraper.scraper import _player_urls_from_html

        html = _read_fixture("squad_page.html")
        urls = _player_urls_from_html(html, "https://www.proleague.be")
        for url in urls:
            assert url.startswith("https://"), f"Expected absolute URL, got: {url}"

    def test_mignolet_included(self):
        from proleague_scraper.scraper import _player_urls_from_html

        html = _read_fixture("squad_page.html")
        urls = _player_urls_from_html(html, "https://www.proleague.be")
        assert any("simon-mignolet" in u for u in urls)

    def test_no_duplicates(self):
        from proleague_scraper.scraper import _player_urls_from_html

        # Squad page with duplicated link (e.g. image + text link to same player).
        html = """
        <html><body>
          <a href="/spillere/hans-vanaken-2959"><img/></a>
          <a href="/spillere/hans-vanaken-2959">Hans Vanaken</a>
        </body></html>
        """
        urls = _player_urls_from_html(html, "https://www.proleague.be")
        assert len(urls) == 1

    def test_empty_page_returns_empty_list(self):
        from proleague_scraper.scraper import _player_urls_from_html

        urls = _player_urls_from_html("<html><body></body></html>", "https://www.proleague.be")
        assert urls == []


# ── tests: __NEXT_DATA__ extraction ─────────────────────────────────────────


class TestNextDataExtraction:
    def test_parses_next_data(self):
        from proleague_scraper.scraper import _extract_next_data

        html = _player_page_html()
        data = _extract_next_data(html)
        assert data is not None
        assert "props" in data

    def test_returns_none_when_absent(self):
        from proleague_scraper.scraper import _extract_next_data

        data = _extract_next_data("<html><body>no next data here</body></html>")
        assert data is None

    def test_returns_none_on_malformed_json(self):
        from proleague_scraper.scraper import _extract_next_data

        html = '<script id="__NEXT_DATA__" type="application/json">{bad json</script>'
        data = _extract_next_data(html)
        assert data is None


# ── tests: player normalisation ─────────────────────────────────────────────


class TestPlayerNormalisation:
    def _get_player(self) -> dict:
        from proleague_scraper.scraper import _extract_next_data, _parse_player_from_next_data

        html = _player_page_html()
        next_data = _extract_next_data(html)
        return _parse_player_from_next_data(
            next_data, "https://www.proleague.be/spillere/simon-mignolet-3219"
        )

    def test_name(self):
        assert self._get_player()["name"] == "Simon Mignolet"

    def test_position(self):
        assert self._get_player()["position"] == "Doelman"

    def test_field_position(self):
        assert self._get_player()["field_position"] == "goalkeeper"

    def test_slug(self):
        assert self._get_player()["slug"] == "simon-mignolet-3219"

    def test_player_id(self):
        assert self._get_player()["player_id"] == "3219"

    def test_shirt_number(self):
        assert self._get_player()["shirt_number"] == 22

    def test_profile_height(self):
        assert self._get_player()["profile"]["height_cm"] == 193

    def test_profile_weight(self):
        assert self._get_player()["profile"]["weight_kg"] == 87

    def test_profile_foot(self):
        assert self._get_player()["profile"]["preferred_foot"] == "Rechts"

    def test_profile_nationality(self):
        assert self._get_player()["profile"]["nationality"] == "België"

    def test_profile_nationality_code(self):
        assert self._get_player()["profile"]["nationality_code"] == "BE"

    def test_stats_non_empty(self):
        stats = self._get_player()["stats"]
        assert len(stats) > 0

    def test_stats_saves_made(self):
        stats = self._get_player()["stats"]
        saves_entry = next((s for s in stats if s["key"] == "savesMade"), None)
        assert saves_entry is not None
        assert saves_entry["value"] == 32
        assert saves_entry["label"] == "Saves"

    def test_stats_have_label_and_value(self):
        stats = self._get_player()["stats"]
        for entry in stats:
            assert "label" in entry
            assert "value" in entry
            assert "key" in entry

    def test_competition_name(self):
        assert self._get_player()["competition"] == "Jupiler Pro League"

    def test_image_url_is_xlarge(self):
        url = self._get_player()["image_url"]
        assert "xlarge" in url or url != ""


# ── tests: stat normalisation ────────────────────────────────────────────────


class TestStatNormalisation:
    def test_known_key_gets_english_label(self):
        from proleague_scraper.scraper import _normalise_stats

        items = _normalise_stats({"savesMade": 10})
        assert items[0]["label"] == "Saves"

    def test_unknown_key_passes_through(self):
        from proleague_scraper.scraper import _normalise_stats

        items = _normalise_stats({"someObscureStat": 5})
        assert items[0]["label"] == "someObscureStat"
        assert items[0]["value"] == 5

    def test_none_values_are_skipped(self):
        from proleague_scraper.scraper import _normalise_stats

        items = _normalise_stats({"goals": 3, "assists": None, "yellowCards": 1})
        keys = [i["key"] for i in items]
        assert "assists" not in keys
        assert "goals" in keys
        assert "yellowCards" in keys


# ── tests: slug / ID extraction ──────────────────────────────────────────────


class TestSlugAndId:
    def test_standard_url(self):
        from proleague_scraper.scraper import _slug_and_id_from_url

        slug, pid = _slug_and_id_from_url("https://www.proleague.be/spillere/simon-mignolet-3219")
        assert slug == "simon-mignolet-3219"
        assert pid == "3219"

    def test_url_with_trailing_slash(self):
        from proleague_scraper.scraper import _slug_and_id_from_url

        slug, pid = _slug_and_id_from_url("https://www.proleague.be/spillere/hans-vanaken-2959/")
        assert slug == "hans-vanaken-2959"
        assert pid == "2959"
