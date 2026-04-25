-- Player statistics scraped from proleague.be.
-- Upserted by the proleague-scraper microservice; read by the frontend-app service.
-- IMPORTANT: Operators must verify proleague.be Terms of Use before production use.

CREATE SCHEMA IF NOT EXISTS raw_data;

CREATE TABLE IF NOT EXISTS raw_data.player_stats (
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

COMMENT ON TABLE raw_data.player_stats IS
    'Player statistics scraped from proleague.be by the proleague-scraper service.';

COMMENT ON COLUMN raw_data.player_stats.profile IS
    'JSON map: birth_date, birth_place, height_cm, weight_kg, preferred_foot, nationality, nationality_code.';

COMMENT ON COLUMN raw_data.player_stats.stats IS
    'JSON array of {key, label, value} dicts from the main competition (Jupiler Pro League).';

-- Allow the read-only LLM API role to query this table.
-- USAGE on raw_data is explicit because llm_reader has search_path=dbt_dev (002_llm_reader.sql).
GRANT USAGE ON SCHEMA raw_data TO llm_reader;
GRANT SELECT ON raw_data.player_stats TO llm_reader;
