-- Staging view over public.player_stats: typed casts for downstream JSON parsing and analytics.
select
    player_id::text as player_id,
    slug,
    name,
    position,
    field_position,
    shirt_number,
    image_url,
    profile::jsonb as profile,
    stats::jsonb as stats,
    competition,
    source_url,
    scraped_at::timestamptz as scraped_at
from {{ source('proleague_scraper', 'player_stats') }}
