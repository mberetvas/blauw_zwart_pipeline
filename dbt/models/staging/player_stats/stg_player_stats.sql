-- Staging view over public.player_stats; extend with column renames / casts as needed.
select
    player_id,
    slug,
    name,
    position,
    field_position,
    shirt_number,
    image_url,
    profile,
    stats,
    competition,
    source_url,
    scraped_at
from {{ source('proleague_scraper', 'player_stats') }}
