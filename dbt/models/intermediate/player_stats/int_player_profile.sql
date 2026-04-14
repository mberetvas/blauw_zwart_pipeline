-- One row per player: roster fields plus biographical attributes from profile JSON.
select
    player_id::text as player_id,
    slug,
    name,
    position,
    field_position,
    shirt_number,
    image_url,
    competition,
    source_url,
    scraped_at::timestamptz as scraped_at,
    nullif(trim(profile->>'height_cm'), '')::integer as height_cm,
    nullif(trim(profile->>'weight_kg'), '')::integer as weight_kg,
    nullif(trim(profile->>'birth_date'), '')::date as birth_date,
    nullif(trim(profile->>'birth_place'), '') as birth_place,
    nullif(trim(profile->>'nationality'), '') as nationality,
    nullif(trim(profile->>'nationality_code'), '') as nationality_code,
    nullif(trim(profile->>'preferred_foot'), '') as preferred_foot
from {{ ref('stg_player_stats') }}
