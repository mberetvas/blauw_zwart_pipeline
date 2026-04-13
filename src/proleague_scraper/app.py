"""Flask HTTP server for the Pro League scraper microservice.

Endpoints
---------
GET /health
    Returns {"status": "ok"}.

GET /squad?url=<optional>&refresh=<0|1>
    Returns Club Brugge squad + player stats.
    By default serves cached data from PostgreSQL (fast).
    Pass ``?refresh=1`` to force a live scrape and update the DB.
    Response: {"source_url", "fetched_at", "players": [...], "cached": true|false}

GET /player?url=<profile_url>
    Fetches and parses a single player page.
    Response: the normalised player dict.

IMPORTANT: Operators must verify robots.txt and Terms of Use at
https://www.proleague.be before running in production.
"""

from __future__ import annotations

import logging
import os

from flask import Flask, jsonify, request

from .scraper import DEFAULT_SQUAD_URL, scrape_player, scrape_squad

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)


def _try_db_save(players: list, source_url: str, fetched_at: str) -> None:
    """Best-effort: upsert players into Postgres. Logs warnings on failure."""
    try:
        from .db import get_connection, upsert_players

        conn = get_connection()
        try:
            upsert_players(conn, players, source_url, fetched_at)
        finally:
            conn.close()
    except Exception as exc:
        log.warning("DB save failed (non-fatal): %s", exc)


def _try_db_load(source_url: str) -> dict | None:
    """Return cached squad from Postgres, or None if unavailable / empty."""
    try:
        from .db import count_players, get_connection, get_players

        conn = get_connection()
        try:
            if count_players(conn) == 0:
                return None
            players = get_players(conn)
            # Use scraped_at from the most recent row as fetched_at.
            latest = max(
                (p["scraped_at"] for p in players if p.get("scraped_at")),
                default=None,
            )
            return {
                "source_url": source_url,
                "fetched_at": latest or "",
                "cached": True,
                "players": players,
            }
        finally:
            conn.close()
    except Exception as exc:
        log.warning("DB load failed (non-fatal): %s", exc)
        return None


@app.get("/health")
def health():
    return jsonify({"status": "ok"})


@app.get("/squad")
def squad():
    url = (request.args.get("url") or "").strip() or DEFAULT_SQUAD_URL
    refresh = request.args.get("refresh", "0").strip() == "1"

    # Serve from DB cache unless the caller explicitly requests a live scrape.
    if not refresh:
        cached = _try_db_load(url)
        if cached is not None:
            return jsonify(cached)

    # Live scrape — then persist to DB.
    try:
        data = scrape_squad(url)
    except Exception as exc:
        log.exception("Squad scrape failed")
        return jsonify({"error": str(exc)}), 502

    _try_db_save(data["players"], data["source_url"], data["fetched_at"])
    data["cached"] = False
    return jsonify(data)


@app.get("/player")
def player():
    url = (request.args.get("url") or "").strip()
    if not url:
        return jsonify({"error": "url query parameter is required"}), 400
    try:
        data = scrape_player(url)
    except Exception as exc:
        log.exception("Player scrape failed")
        return jsonify({"error": str(exc)}), 502
    return jsonify(data)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8001))
    app.run(host="0.0.0.0", port=port)
