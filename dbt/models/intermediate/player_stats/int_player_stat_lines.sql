-- Long-format stat lines: one row per (player, stat_key) from the scraper stats JSON array.
select
    p.player_id::text as player_id,
    p.slug,
    p.name,
    p.competition,
    p.field_position,
    coalesce(elem->>'key', '') as stat_key,
    coalesce(elem->>'label', '') as stat_label,
    nullif(trim(elem->>'value'), '')::numeric as stat_value
from {{ ref('stg_player_stats') }} as p
cross join lateral jsonb_array_elements(p.stats) as elem
