-- Player statistics scraped from proleague.be.
-- Upserted by the proleague-scraper microservice; read by the llm_api service.
-- IMPORTANT: Operators must verify proleague.be Terms of Use before production use.

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

COMMENT ON TABLE player_stats IS
    'Player statistics scraped from proleague.be by the proleague-scraper service.';

COMMENT ON COLUMN player_stats.profile IS
    'JSON map: birth_date, birth_place, height_cm, weight_kg, preferred_foot, nationality, nationality_code.';

COMMENT ON COLUMN player_stats.stats IS
    'JSON array of {key, label, value} dicts from the main competition (Jupiler Pro League).';

-- Allow the read-only LLM API role to query this table.
GRANT SELECT ON player_stats TO llm_reader;
