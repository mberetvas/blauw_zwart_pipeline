-- One row per player: season totals and a focused set of pivoted metrics for analysis and Text-to-SQL.
{{
    config(
        materialized='table',
        tags=['mart', 'player_stats', 'proleague']
    )
}}

with lines as (
    select * from {{ ref('int_player_stat_lines') }}
),

pivot as (
    select
        player_id,
        max(case when stat_key = 'goals' then stat_value end) as goals,
        max(case when stat_key = 'assists' then stat_value end) as assists,
        max(case when stat_key = 'goalAssists' then stat_value end) as goal_assists,
        max(case when stat_key = 'appearances' then stat_value end) as appearances,
        max(case when stat_key = 'gamesPlayed' then stat_value end) as games_played,
        max(case when stat_key = 'starts' then stat_value end) as starts,
        max(case when stat_key = 'timePlayed' then stat_value end) as minutes_played,
        max(case when stat_key = 'realTimePlayed' then stat_value end) as real_minutes_played,
        max(case when stat_key = 'gamesNotCalled' then stat_value end) as games_not_called,
        max(case when stat_key = 'substituteOn' then stat_value end) as substitute_on,
        max(case when stat_key = 'substituteOff' then stat_value end) as substitute_off,
        max(case when stat_key = 'totalPasses' then stat_value end) as total_passes,
        max(case when stat_key = 'totalSuccessfulPasses' then stat_value end) as successful_passes,
        max(case when stat_key = 'totalUnsuccessfulPasses' then stat_value end) as unsuccessful_passes,
        max(case when stat_key = 'keyPasses' then stat_value end) as key_passes,
        max(case when stat_key = 'forwardPasses' then stat_value end) as forward_passes,
        max(case when stat_key = 'totalShots' then stat_value end) as total_shots,
        max(case when stat_key = 'shotsOnTarget' then stat_value end) as shots_on_target,
        max(case when stat_key = 'shotsOffTarget' then stat_value end) as shots_off_target,
        max(case when stat_key = 'duels' then stat_value end) as duels,
        max(case when stat_key = 'duelsWon' then stat_value end) as duels_won,
        max(case when stat_key = 'duelsLost' then stat_value end) as duels_lost,
        max(case when stat_key = 'aerialDuels' then stat_value end) as aerial_duels,
        max(case when stat_key = 'aerialDuelsWon' then stat_value end) as aerial_duels_won,
        max(case when stat_key = 'groundDuels' then stat_value end) as ground_duels,
        max(case when stat_key = 'groundDuelsWon' then stat_value end) as ground_duels_won,
        max(case when stat_key = 'recoveries' then stat_value end) as recoveries,
        max(case when stat_key = 'tacklesWon' then stat_value end) as tackles_won,
        max(case when stat_key = 'tacklesLost' then stat_value end) as tackles_lost,
        max(case when stat_key = 'totalTackles' then stat_value end) as total_tackles,
        max(case when stat_key = 'goalsConceded' then stat_value end) as goals_conceded,
        max(case when stat_key = 'cleansheets' then stat_value end) as clean_sheets,
        max(case when stat_key = 'gamesZeroGoalsConceded' then stat_value end) as games_zero_goals_conceded,
        max(case when stat_key = 'yellowCards' then stat_value end) as yellow_cards,
        max(case when stat_key = 'totalRedCards' then stat_value end) as total_red_cards,
        max(case when stat_key = 'offsides' then stat_value end) as offsides,
        max(case when stat_key = 'successfulDribbles' then stat_value end) as successful_dribbles,
        max(case when stat_key = 'unsuccessfulDribbles' then stat_value end) as unsuccessful_dribbles,
        max(case when stat_key = 'totalTouchesInOppositionBox' then stat_value end) as touches_opposition_box,
        max(case when stat_key = 'blocks' then stat_value end) as blocks,
        max(case when stat_key = 'totalClearances' then stat_value end) as clearances,
        max(case when stat_key = 'totalFoulsWon' then stat_value end) as fouls_won,
        max(case when stat_key = 'totalFoulsConceded' then stat_value end) as fouls_conceded,
        max(case when stat_key = 'savesMade' then stat_value end) as saves_made,
        max(case when stat_key = 'penaltiesSaved' then stat_value end) as penalties_saved,
        max(case when stat_key = 'goalKicks' then stat_value end) as goal_kicks,
        max(case when stat_key = 'touches' then stat_value end) as touches
    from lines
    group by player_id
)

select
    pr.player_id,
    pr.slug,
    pr.name,
    pr.position,
    pr.field_position,
    pr.shirt_number,
    pr.image_url,
    pr.competition,
    pr.source_url,
    pr.scraped_at,
    pr.height_cm,
    pr.weight_kg,
    pr.birth_date,
    pr.birth_place,
    pr.nationality,
    pr.nationality_code,
    pr.preferred_foot,

    p.goals,
    p.assists,
    p.goal_assists,
    p.appearances,
    p.games_played,
    p.starts,
    p.minutes_played,
    p.real_minutes_played,
    p.games_not_called,
    p.substitute_on,
    p.substitute_off,
    p.total_passes,
    p.successful_passes,
    p.unsuccessful_passes,
    p.key_passes,
    p.forward_passes,
    p.total_shots,
    p.shots_on_target,
    p.shots_off_target,
    p.duels,
    p.duels_won,
    p.duels_lost,
    p.aerial_duels,
    p.aerial_duels_won,
    p.ground_duels,
    p.ground_duels_won,
    p.recoveries,
    p.tackles_won,
    p.tackles_lost,
    p.total_tackles,
    p.goals_conceded,
    p.clean_sheets,
    p.games_zero_goals_conceded,
    p.yellow_cards,
    p.total_red_cards,
    p.offsides,
    p.successful_dribbles,
    p.unsuccessful_dribbles,
    p.touches_opposition_box,
    p.blocks,
    p.clearances,
    p.fouls_won,
    p.fouls_conceded,
    p.saves_made,
    p.penalties_saved,
    p.goal_kicks,
    p.touches,

    case
        when p.total_passes is not null and p.total_passes > 0 and p.successful_passes is not null
            then round(100.0 * p.successful_passes / p.total_passes, 2)
    end as pass_accuracy_pct,

    case
        when p.minutes_played is not null and p.minutes_played > 0 and p.goals is not null
            then round(90.0 * p.goals / p.minutes_played, 3)
    end as goals_per_90,

    case
        when p.minutes_played is not null and p.minutes_played > 0 and p.assists is not null
            then round(90.0 * p.assists / p.minutes_played, 3)
    end as assists_per_90,

    case
        when p.duels is not null and p.duels > 0 and p.duels_won is not null
            then round(100.0 * p.duels_won / p.duels, 2)
    end as duel_win_pct,

    case
        when p.total_shots is not null and p.total_shots > 0 and p.shots_on_target is not null
            then round(100.0 * p.shots_on_target / p.total_shots, 2)
    end as shot_on_target_pct

from {{ ref('int_player_profile') }} as pr
left join pivot as p on pr.player_id = p.player_id
