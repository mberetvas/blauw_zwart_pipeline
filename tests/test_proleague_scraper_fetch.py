"""Phase 3 branch-fill tests for proleague_scraper._fetch_html and _extract_next_data."""

from __future__ import annotations

import pytest
import requests

from proleague_scraper import scraper as scraper_mod


@pytest.fixture(autouse=True)
def _reset_session(monkeypatch: pytest.MonkeyPatch):
    """Force a fresh session per test (avoids state carrying between tests)."""
    monkeypatch.setattr(scraper_mod, "_SESSION", None)
    # Skip actual sleeps in retry backoff.
    monkeypatch.setattr(scraper_mod.time, "sleep", lambda _s: None)
    yield


class _Resp:
    def __init__(self, text: str = "<html></html>", status: int = 200) -> None:
        self.text = text
        self.status_code = status

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")


def test_fetch_html_succeeds_first_try(monkeypatch: pytest.MonkeyPatch) -> None:
    session = scraper_mod._get_session()
    monkeypatch.setattr(session, "get", lambda url, timeout: _Resp("<p>ok</p>"))
    assert scraper_mod._fetch_html("https://example.test") == "<p>ok</p>"


def test_fetch_html_retries_then_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    session = scraper_mod._get_session()
    calls = {"n": 0}

    def get(url, timeout):
        calls["n"] += 1
        if calls["n"] < 2:
            raise requests.exceptions.Timeout("first attempt")
        return _Resp("<p>ok</p>")

    monkeypatch.setattr(session, "get", get)
    assert scraper_mod._fetch_html("https://example.test") == "<p>ok</p>"
    assert calls["n"] == 2


def test_fetch_html_raises_after_all_retries(monkeypatch: pytest.MonkeyPatch) -> None:
    session = scraper_mod._get_session()
    monkeypatch.setattr(scraper_mod, "MAX_RETRIES", 2)

    def boom(url, timeout):
        raise requests.exceptions.ConnectionError("down")

    monkeypatch.setattr(session, "get", boom)
    with pytest.raises(RuntimeError, match=r"Failed to fetch.*after 2 attempts"):
        scraper_mod._fetch_html("https://example.test")


def test_fetch_html_raises_on_http_error_after_retries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = scraper_mod._get_session()
    monkeypatch.setattr(scraper_mod, "MAX_RETRIES", 2)
    monkeypatch.setattr(session, "get", lambda url, timeout: _Resp(status=503))
    with pytest.raises(RuntimeError, match=r"Failed to fetch"):
        scraper_mod._fetch_html("https://example.test")


# ---------------------------------------------------------------------------
# _extract_next_data
# ---------------------------------------------------------------------------


def test_extract_next_data_returns_none_when_tag_missing() -> None:
    assert scraper_mod._extract_next_data("<html><body>no script</body></html>") is None


def test_extract_next_data_returns_none_on_invalid_json() -> None:
    html = (
        '<html><head><script id="__NEXT_DATA__" type="application/json">'
        "{not json}</script></head></html>"
    )
    assert scraper_mod._extract_next_data(html) is None


def test_extract_next_data_returns_parsed_json() -> None:
    html = (
        '<html><head><script id="__NEXT_DATA__" type="application/json">'
        '{"props": {"pageProps": {"x": 1}}}'
        "</script></head></html>"
    )
    out = scraper_mod._extract_next_data(html)
    assert out == {"props": {"pageProps": {"x": 1}}}


def test_get_session_reuses_same_instance(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(scraper_mod, "_SESSION", None)
    s1 = scraper_mod._get_session()
    s2 = scraper_mod._get_session()
    assert s1 is s2
    assert "User-Agent" in s1.headers
