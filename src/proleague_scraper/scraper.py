"""Pro League HTML scraper — squad listing + individual player pages.

Design principles
-----------------
* Primary data source: ``__NEXT_DATA__`` JSON embedded in every Next.js page.
  This is the most stable extraction target — it is a contract between the
  build and the SSR/SSG layer, not a CSS-module artifact.
* Fallback (squad listing only): ``a[href*="/spillere/"]`` anchor hrefs.
  These are based on a stable URL path pattern, not brittle hashed class names.
* Fragile class names (``sc-…``, hashed CSS modules) are **not** used as
  selectors anywhere in this file; the component library's BEM names
  (``Mk…__*``) are used only in comments for reference.

IMPORTANT: Before deploying in production verify robots.txt and Terms of Use at
https://www.proleague.be/robots.txt.  Operators are responsible for compliance.
"""

from __future__ import annotations

import json
import re
import time
from typing import Any
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from common.logging_setup import get_logger

log = get_logger(__name__)

BASE_URL = "https://www.proleague.be"
DEFAULT_SQUAD_URL = f"{BASE_URL}/teams/club-brugge-kv-182/squad"

# Polite scraping defaults — operators may override via environment variables.
REQUEST_TIMEOUT = 20  # seconds per HTTP request
RATE_LIMIT_DELAY = 1.5  # seconds between individual player fetches
MAX_RETRIES = 3
BACKOFF_FACTOR = 2.0

# User-Agent identifies this bot clearly; do not impersonate a browser.
USER_AGENT = "ClubBruggeAI-FanSim/1.0 (fan data pipeline; https://github.com/your-org/blauw_zwart_fan_sim_pipeline)"

_SESSION: requests.Session | None = None


def _get_session() -> requests.Session:
    """Return a shared requests session configured for polite scraping."""
    global _SESSION
    if _SESSION is None:
        _SESSION = requests.Session()
        _SESSION.headers.update(
            {
                "User-Agent": USER_AGENT,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "nl,en;q=0.5",
            }
        )
    return _SESSION


def _fetch_html(url: str) -> str:
    """Fetch a URL with retries and polite backoff.

    Args:
        url: Absolute page URL to fetch.

    Returns:
        Raw HTML response body.

    Raises:
        RuntimeError: If all retry attempts fail.
    """
    session = _get_session()
    delay = BACKOFF_FACTOR
    last_exc: Exception | None = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = session.get(url, timeout=REQUEST_TIMEOUT)
            resp.raise_for_status()
            return resp.text
        except requests.RequestException as exc:
            last_exc = exc
            log.info(
                "fetch_attempt_failed attempt={} max_attempts={} url={} error={}",
                attempt,
                MAX_RETRIES,
                url,
                exc,
            )
            if attempt < MAX_RETRIES:
                time.sleep(delay)
                delay *= BACKOFF_FACTOR
    raise RuntimeError(f"Failed to fetch {url} after {MAX_RETRIES} attempts: {last_exc}")


def _extract_next_data(html: str) -> dict[str, Any] | None:
    """Parse the ``__NEXT_DATA__`` JSON injected by Next.js SSR/SSG.

    Args:
        html: Raw HTML document.

    Returns:
        Parsed JSON object, or ``None`` when the page does not expose the
        expected Next.js bootstrap payload.
    """
    soup = BeautifulSoup(html, "lxml")
    tag = soup.find("script", id="__NEXT_DATA__", type="application/json")
    if tag is None:
        return None
    try:
        return json.loads(tag.string or "")
    except (json.JSONDecodeError, TypeError) as exc:
        log.info("next_data_parse_failed error={}", exc)
        return None


# ---------------------------------------------------------------------------
# Squad-page parsing
# ---------------------------------------------------------------------------


def _player_urls_from_html(html: str, base_url: str) -> list[str]:
    """Extract absolute player profile URLs from the squad listing HTML.

    Args:
        html: Raw squad listing HTML.
        base_url: Base URL used to resolve relative player links.

    Returns:
        De-duplicated list of absolute player profile URLs.
    """
    soup = BeautifulSoup(html, "lxml")
    seen: set[str] = set()
    urls: list[str] = []
    for tag in soup.find_all("a", href=re.compile(r"/spillere/")):
        href: str = tag.get("href", "")
        absolute = urljoin(base_url, href)
        # Normalise: drop query string / fragment; keep path only up to slug.
        parsed = urlparse(absolute)
        clean = parsed._replace(query="", fragment="").geturl()
        if clean not in seen:
            seen.add(clean)
            urls.append(clean)
    return urls


def _slug_and_id_from_url(url: str) -> tuple[str, str]:
    """Return ``(slug, player_id)`` from a player profile URL."""
    path = urlparse(url).path.rstrip("/")
    slug = path.split("/")[-1]
    # The numeric suffix at the end of the slug is the Pro League player ID.
    match = re.search(r"-(\d+)$", slug)
    player_id = match.group(1) if match else ""
    return slug, player_id


# ---------------------------------------------------------------------------
# Player-page parsing
# ---------------------------------------------------------------------------

# Mapping from __NEXT_DATA__ stats keys to human-readable labels (English).
# Only the most common keys are listed; unknown keys pass through as-is.
_STAT_LABELS: dict[str, str] = {
    "appearances": "Appearances",
    "gamesPlayed": "Games Played",
    "starts": "Starts",
    "timePlayed": "Minutes Played",
    "goals": "Goals",
    "winningGoal": "Winning Goals",
    "assists": "Assists",
    "yellowCards": "Yellow Cards",
    "redCards": "Red Cards",
    "savesMade": "Saves",
    "cleansheets": "Clean Sheets",
    "goalsConceded": "Goals Conceded",
    "totalSuccessfulPasses": "Successful Passes",
    "totalUnsuccessfulPasses": "Unsuccessful Passes",
    "successfulLongPasses": "Successful Long Passes",
    "unsuccessfulLongPasses": "Unsuccessful Long Passes",
    "totalClearances": "Clearances",
    "aerialDuelsWon": "Aerial Duels Won",
    "aerialDuels": "Aerial Duels",
    "duels": "Duels",
    "duelsWon": "Duels Won",
    "touches": "Touches",
    "recoveries": "Recoveries",
    "penaltiesFaced": "Penalties Faced",
    "penaltiesSaved": "Penalties Saved",
}


def _normalise_stats(raw_stats: dict[str, Any]) -> list[dict[str, Any]]:
    """Convert a raw stats mapping into labelled API-friendly items."""
    result: list[dict[str, Any]] = []
    for key, value in raw_stats.items():
        if value is None:
            continue
        label = _STAT_LABELS.get(key, key)
        result.append({"key": key, "label": label, "value": value})
    return result


def _parse_player_from_next_data(next_data: dict[str, Any], url: str) -> dict[str, Any]:
    """Build a normalised player dict from the ``__NEXT_DATA__`` payload.

    Args:
        next_data: Parsed Next.js bootstrap payload.
        url: Player profile URL used for slug and id fallback parsing.

    Returns:
        Normalised player dictionary suitable for Kafka publishing and DB upsert.
    """
    page_props = next_data.get("props", {}).get("pageProps", {})
    raw = page_props.get("data", {}).get("player", {})

    slug, player_id = _slug_and_id_from_url(url)

    # Phase 1: extract the profile header facts from stable JSON fields.
    position_obj = raw.get("position") or {}
    position_name = position_obj.get("singularName") or position_obj.get("name", "")
    field_position = position_obj.get("fieldPosition", "")
    nationality_obj = raw.get("nationality") or {}
    foot_obj = raw.get("preferredFoot") or {}

    # Phase 2: enrich with squad-level attributes not duplicated everywhere.
    shirt_number: int | None = None
    squads = raw.get("squads") or []
    if squads:
        shirt_number = squads[0].get("shirtNumber")

    # Phase 3: prefer the highest-quality image URL exposed by the payload.
    image_obj = raw.get("image") or {}
    thumbnails = image_obj.get("thumbnails") or {}
    image_url = thumbnails.get("xlarge") or image_obj.get("url") or ""

    # Phase 4: choose the main competition stats when present; otherwise fall
    # back to the first available stat bundle.
    stats_list: list[dict[str, Any]] = []
    competition_name: str = ""
    raw_stats_entries = raw.get("stats") or []
    chosen_entry: dict[str, Any] | None = None
    for entry in raw_stats_entries:
        comp = entry.get("competition") or {}
        if comp.get("main"):
            chosen_entry = entry
            break
    if chosen_entry is None and raw_stats_entries:
        chosen_entry = raw_stats_entries[0]
    if chosen_entry:
        competition_name = (chosen_entry.get("competition") or {}).get("name", "")
        stats_list = _normalise_stats(chosen_entry.get("stats") or {})

    return {
        "player_id": player_id,
        "slug": slug,
        "url": url,
        "name": raw.get("name") or raw.get("nickname") or slug,
        "position": position_name,
        "field_position": field_position,
        "shirt_number": shirt_number,
        "image_url": image_url,
        "profile": {
            "birth_date": raw.get("birthDate"),
            "birth_place": raw.get("birthPlace"),
            "height_cm": raw.get("height"),
            "weight_kg": raw.get("weight"),
            "preferred_foot": foot_obj.get("name"),
            "nationality": nationality_obj.get("name"),
            "nationality_code": nationality_obj.get("code"),
        },
        "competition": competition_name,
        "stats": stats_list,
    }


def scrape_player(url: str) -> dict[str, Any]:
    """Fetch and parse a single player profile page.

    Args:
        url: Absolute player profile URL.

    Returns:
        Normalised player dictionary.

    Raises:
        RuntimeError: If the page fetch fails after retries.
        ValueError: If the page does not expose a usable ``__NEXT_DATA__`` payload.
    """
    html = _fetch_html(url)
    next_data = _extract_next_data(html)
    if next_data is None:
        raise ValueError(f"No __NEXT_DATA__ found on player page: {url}")
    return _parse_player_from_next_data(next_data, url)


def scrape_squad(
    squad_url: str = DEFAULT_SQUAD_URL,
    *,
    concurrency_delay: float = RATE_LIMIT_DELAY,
) -> dict[str, Any]:
    """Fetch the squad listing and all linked player profiles.

    Args:
        squad_url: Full URL of the squad listing page.
        concurrency_delay: Seconds to wait between consecutive player-page
            fetches as a polite rate limit.

    Returns:
        Dictionary with ``source_url``, ``fetched_at``, and ``players``.
    """
    import datetime

    log.info("scrape_squad_start squad_url={}", squad_url)
    log.debug(
        "task=fetch_squad_listing previous=scrape_requested next=parse_player_urls url={}",
        squad_url,
    )
    squad_html = _fetch_html(squad_url)
    player_urls = _player_urls_from_html(squad_html, squad_url)
    log.info("scrape_squad_urls_discovered count={}", len(player_urls))

    players: list[dict[str, Any]] = []
    # Phase 2: walk each player profile sequentially so rate limiting stays explicit.
    for idx, player_url in enumerate(player_urls):
        if idx > 0:
            time.sleep(concurrency_delay)
        try:
            log.debug(
                "task=scrape_player previous=player_url_discovered"
                " next=normalize_player_data index={} total={} url={}",
                idx + 1,
                len(player_urls),
                player_url,
            )
            player = scrape_player(player_url)
            players.append(player)
            log.debug(
                "task=scrape_player_complete previous=player_fetched next=continue_iteration "
                "index={} total={} player={}",
                idx + 1,
                len(player_urls),
                player["name"],
            )
        except Exception as exc:
            log.info("scrape_player_skipped url={} error={}", player_url, exc)
            players.append(
                {
                    "player_id": "",
                    "slug": player_url.rstrip("/").split("/")[-1],
                    "url": player_url,
                    "name": player_url.rstrip("/").split("/")[-1],
                    "error": str(exc),
                }
            )

    # Phase 3: stamp the batch with one scrape timestamp for downstream Kafka and DB consumers.
    fetched_at = datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z")
    log.info("scrape_squad_complete players_total={} source_url={}", len(players), squad_url)
    return {
        "source_url": squad_url,
        "fetched_at": fetched_at,
        "players": players,
    }
