"""PostgreSQL persistence for scraped player data.

The scraper writes here after every squad fetch; the Flask app serves the
cached rows to avoid re-scraping on every request.

Table: ``player_stats`` (docker/postgres/init/003_player_stats.sql on first boot;
``ensure_player_stats_table`` creates it at runtime if the volume predates that script).
Upserts are keyed on ``player_id`` so re-runs overwrite stale rows.
"""

from __future__ import annotations

import json
import logging
import os
import weakref
from typing import Any

import psycopg2
import psycopg2.extras

log = logging.getLogger(__name__)

# One-time ensure per live connection (psycopg2 C objects may not allow custom attrs).
_conn_player_stats_ready: weakref.WeakKeyDictionary = weakref.WeakKeyDictionary()

# Same DDL as docker/postgres/init/003_player_stats.sql — run at runtime so existing
# DB volumes (created before that init script existed) get the table without a manual migration.
_ENSURE_PLAYER_STATS_SQL = """
CREATE TABLE IF NOT EXISTS player_stats (
    player_id       TEXT        PRIMARY KEY,
    slug            TEXT        NOT NULL,
    name            TEXT        NOT NULL,
    position        TEXT,
    field_position  TEXT,
    shirt_number    INTEGER,
    image_url       TEXT,
    profile         JSONB       NOT NULL DEFAULT '{}',
    stats           JSONB       NOT NULL DEFAULT '[]',
    competition     TEXT,
    source_url      TEXT,
    scraped_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""

# Same as docker/postgres/init/003_player_stats.sql — llm-api reads via role llm_reader.
# One statement per execute (psycopg2 protocol).
_GRANT_LLM_READER_ON_PLAYER_STATS = (
    "GRANT USAGE ON SCHEMA public TO llm_reader",
    "GRANT SELECT ON player_stats TO llm_reader",
)

_UPSERT_SQL = """
INSERT INTO player_stats (
    player_id, slug, name, position, field_position, shirt_number,
    image_url, profile, stats, competition, source_url, scraped_at
) VALUES (
    %(player_id)s, %(slug)s, %(name)s, %(position)s, %(field_position)s,
    %(shirt_number)s, %(image_url)s, %(profile)s::jsonb, %(stats)s::jsonb,
    %(competition)s, %(source_url)s, %(scraped_at)s
)
ON CONFLICT (player_id) DO UPDATE SET
    slug           = EXCLUDED.slug,
    name           = EXCLUDED.name,
    position       = EXCLUDED.position,
    field_position = EXCLUDED.field_position,
    shirt_number   = EXCLUDED.shirt_number,
    image_url      = EXCLUDED.image_url,
    profile        = EXCLUDED.profile,
    stats          = EXCLUDED.stats,
    competition    = EXCLUDED.competition,
    source_url     = EXCLUDED.source_url,
    scraped_at     = EXCLUDED.scraped_at
"""

_SELECT_SQL = """
SELECT player_id, slug, name, position, field_position, shirt_number,
       image_url, profile, stats, competition, source_url, scraped_at
FROM player_stats
ORDER BY name
"""


def get_connection() -> psycopg2.extensions.connection:
    """Open a new database connection using DATABASE_URL env var."""
    url = os.environ.get("DATABASE_URL", "").strip()
    if not url:
        raise RuntimeError("DATABASE_URL environment variable is not set")
    return psycopg2.connect(url)


def ensure_player_stats_table(conn: psycopg2.extensions.connection) -> None:
    """Create ``player_stats`` if missing (idempotent).

    Docker init only runs on an empty data directory; this covers upgraded volumes.
    When the table is created here (not by init SQL), apply the same grants as
    ``003_player_stats.sql`` so ``llm_reader`` can SELECT for the LLM API.
    """
    with conn.cursor() as cur:
        cur.execute(_ENSURE_PLAYER_STATS_SQL)
        cur.execute("SAVEPOINT grant_llm_reader_player_stats")
        try:
            for stmt in _GRANT_LLM_READER_ON_PLAYER_STATS:
                cur.execute(stmt)
        except psycopg2.Error as exc:
            cur.execute("ROLLBACK TO SAVEPOINT grant_llm_reader_player_stats")
            # Role missing (e.g. minimal local DB): table still usable for writers.
            if getattr(exc, "pgcode", None) != psycopg2.errorcodes.UNDEFINED_OBJECT:
                raise
            log.debug("Skipped llm_reader grants on player_stats: %s", exc)
    conn.commit()


def _ensure_player_stats_once(conn: psycopg2.extensions.connection) -> None:
    if _conn_player_stats_ready.get(conn) is not True:
        ensure_player_stats_table(conn)
        _conn_player_stats_ready[conn] = True


def upsert_players(
    conn: psycopg2.extensions.connection,
    players: list[dict[str, Any]],
    source_url: str,
    scraped_at: str,
) -> int:
    """Upsert a list of normalised player dicts into ``player_stats``.

    Players that carry an ``error`` key or have an empty ``player_id`` are skipped.
    Returns the number of rows actually written.
    """
    _ensure_player_stats_once(conn)

    count = 0
    with conn.cursor() as cur:
        for p in players:
            if p.get("error") or not p.get("player_id"):
                continue
            cur.execute(
                _UPSERT_SQL,
                {
                    "player_id": p["player_id"],
                    "slug": p.get("slug", ""),
                    "name": p.get("name", ""),
                    "position": p.get("position"),
                    "field_position": p.get("field_position"),
                    "shirt_number": p.get("shirt_number"),
                    "image_url": p.get("image_url") or None,
                    "profile": json.dumps(p.get("profile") or {}),
                    "stats": json.dumps(p.get("stats") or []),
                    "competition": p.get("competition"),
                    "source_url": source_url,
                    "scraped_at": scraped_at,
                },
            )
            count += 1
    conn.commit()
    log.info("Upserted %d player rows into player_stats", count)
    return count


def get_players(
    conn: psycopg2.extensions.connection,
) -> list[dict[str, Any]]:
    """Return all rows from ``player_stats`` as normalised player dicts."""
    _ensure_player_stats_once(conn)
    with conn.cursor() as cur:
        cur.execute(_SELECT_SQL)
        rows = cur.fetchall()

    players: list[dict[str, Any]] = []
    for row in rows:
        (
            player_id, slug, name, position, field_position, shirt_number,
            image_url, profile, stats, competition, source_url, scraped_at,
        ) = row
        # psycopg2 returns JSONB columns as Python dicts/lists already.
        players.append(
            {
                "player_id": player_id,
                "slug": slug,
                "name": name,
                "position": position or "",
                "field_position": field_position or "",
                "shirt_number": shirt_number,
                "image_url": image_url or "",
                "profile": profile if isinstance(profile, dict) else json.loads(profile or "{}"),
                "stats": stats if isinstance(stats, list) else json.loads(stats or "[]"),
                "competition": competition or "",
                "source_url": source_url or "",
                "scraped_at": scraped_at.isoformat() if scraped_at else None,
            }
        )
    return players


def count_players(conn: psycopg2.extensions.connection) -> int:
    """Return the number of rows currently in ``player_stats``."""
    _ensure_player_stats_once(conn)
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM player_stats")
        return cur.fetchone()[0]
