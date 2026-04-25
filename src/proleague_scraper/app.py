"""Flask HTTP server for the Pro League scraper microservice.

Endpoints
---------
GET /health
    Returns {"status": "ok"}.

GET /squad?url=<optional>
    Reads squad data from the PostgreSQL ``player_stats`` table (populated by the
    ``proleague-ingest`` consumer after each daily scrape cycle).
    Returns an empty squad when no data has been persisted yet.
    Response: {"source_url", "fetched_at", "players": [...], "cached": true}

GET /player?url=<profile_url>
    Fetches and parses a single player page on demand (live HTTP call).
    Response: the normalised player dict.

NOTE: This service no longer triggers live scrapes for the /squad endpoint.
All squad data is written by the proleague-scheduler → Kafka → proleague-ingest
pipeline.  Use ``proleague-scheduler`` (SCRAPER_RUN_ON_STARTUP=1) or wait for
the next daily run to populate the database.

IMPORTANT: Operators must verify robots.txt and Terms of Use at
https://www.proleague.be before running in production.
"""

from __future__ import annotations

import os

from flask import Flask, jsonify, request

from common.logging_setup import configure_logging, get_logger

from .scraper import DEFAULT_SQUAD_URL, scrape_player

app = Flask(__name__)
configure_logging(level=os.environ.get("LOG_LEVEL", "INFO"))
log = get_logger(__name__)


def _db_load_squad(source_url: str) -> dict:
    """Read all players from Postgres ``player_stats``. Returns empty squad on any failure."""
    try:
        from .db import count_players, get_connection, get_players

        conn = get_connection()
        try:
            if count_players(conn) == 0:
                return {"source_url": source_url, "fetched_at": None, "cached": True, "players": []}
            players = get_players(conn)
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
        log.info("squad_cache_load_failed error={}", exc)
        return {"source_url": source_url, "fetched_at": None, "cached": True, "players": []}


@app.get("/health")
def health():
    return jsonify({"status": "ok"})


@app.get("/squad")
def squad():
    """Return squad data from the Postgres cache (read-only).

    Data is populated by the daily proleague-scheduler → Kafka → proleague-ingest pipeline.
    Returns an empty squad with ``players: []`` until the first scrape cycle completes.
    """
    url = (request.args.get("url") or "").strip() or DEFAULT_SQUAD_URL
    return jsonify(_db_load_squad(url))


@app.get("/player")
def player():
    """Fetch and parse a single player profile page (live HTTP request)."""
    url = (request.args.get("url") or "").strip()
    if not url:
        return jsonify({"error": "url query parameter is required"}), 400
    try:
        data = scrape_player(url)
    except Exception:
        log.info("player_scrape_failed url={}", url)
        return jsonify({"error": "Failed to fetch player data"}), 502
    return jsonify(data)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8001))
    app.run(host="0.0.0.0", port=port)
