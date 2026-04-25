-- One row per player: roster and biographical fields joined with pivoted season stats and derived rates.
{{ config(materialized='table', tags=['mart', 'player_stats', 'proleague']) }}

select *
from {{ ref('int_player_profile') }}
left join {{ ref('int_player_stats_pivoted') }} using (player_id)