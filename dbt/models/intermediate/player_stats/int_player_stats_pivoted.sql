-- One row per player: pivots every tracked stat key from int_player_stat_lines into wide columns,
-- coalesces missing stats to 0, and derives per-90 / accuracy rates. Feeds mart_player_season_summary.
with lines as (
    select * from {{ ref('int_player_stat_lines') }}
),

pivot as (
    select
        player_id,
        coalesce(max(case when stat_key = 'goals' then stat_value end), 0) as goals,
        coalesce(max(case when stat_key = 'assists' then stat_value end), 0) as assists,
        coalesce(max(case when stat_key = 'goalAssists' then stat_value end), 0) as goal_assists,
        coalesce(max(case when stat_key = 'appearances' then stat_value end), 0) as appearances,
        coalesce(max(case when stat_key = 'gamesPlayed' then stat_value end), 0) as games_played,
        coalesce(max(case when stat_key = 'starts' then stat_value end), 0) as starts,
        coalesce(max(case when stat_key = 'timePlayed' then stat_value end), 0) as minutes_played,
        coalesce(max(case when stat_key = 'realTimePlayed' then stat_value end), 0) as real_minutes_played,
        coalesce(max(case when stat_key = 'gamesNotCalled' then stat_value end), 0) as games_not_called,
        coalesce(max(case when stat_key = 'substituteOn' then stat_value end), 0) as substitute_on,
        coalesce(max(case when stat_key = 'substituteOff' then stat_value end), 0) as substitute_off,
        coalesce(max(case when stat_key = 'totalPasses' then stat_value end), 0) as total_passes,
        coalesce(max(case when stat_key = 'totalSuccessfulPasses' then stat_value end), 0) as successful_passes,
        coalesce(max(case when stat_key = 'totalUnsuccessfulPasses' then stat_value end), 0) as unsuccessful_passes,
        coalesce(max(case when stat_key = 'keyPasses' then stat_value end), 0) as key_passes,
        coalesce(max(case when stat_key = 'forwardPasses' then stat_value end), 0) as forward_passes,
        coalesce(max(case when stat_key = 'totalShots' then stat_value end), 0) as total_shots,
        coalesce(max(case when stat_key = 'shotsOnTarget' then stat_value end), 0) as shots_on_target,
        coalesce(max(case when stat_key = 'shotsOffTarget' then stat_value end), 0) as shots_off_target,
        coalesce(max(case when stat_key = 'duels' then stat_value end), 0) as duels,
        coalesce(max(case when stat_key = 'duelsWon' then stat_value end), 0) as duels_won,
        coalesce(max(case when stat_key = 'duelsLost' then stat_value end), 0) as duels_lost,
        coalesce(max(case when stat_key = 'aerialDuels' then stat_value end), 0) as aerial_duels,
        coalesce(max(case when stat_key = 'aerialDuelsWon' then stat_value end), 0) as aerial_duels_won,
        coalesce(max(case when stat_key = 'groundDuels' then stat_value end), 0) as ground_duels,
        coalesce(max(case when stat_key = 'groundDuelsWon' then stat_value end), 0) as ground_duels_won,
        coalesce(max(case when stat_key = 'recoveries' then stat_value end), 0) as recoveries,
        coalesce(max(case when stat_key = 'tacklesWon' then stat_value end), 0) as tackles_won,
        coalesce(max(case when stat_key = 'tacklesLost' then stat_value end), 0) as tackles_lost,
        coalesce(max(case when stat_key = 'totalTackles' then stat_value end), 0) as total_tackles,
        coalesce(max(case when stat_key = 'goalsConceded' then stat_value end), 0) as goals_conceded,
        coalesce(max(case when stat_key = 'cleansheets' then stat_value end), 0) as clean_sheets,
        coalesce(max(case when stat_key = 'gamesZeroGoalsConceded' then stat_value end), 0) as games_zero_goals_conceded,
        coalesce(max(case when stat_key = 'yellowCards' then stat_value end), 0) as yellow_cards,
        coalesce(max(case when stat_key = 'totalRedCards' then stat_value end), 0) as total_red_cards,
        coalesce(max(case when stat_key = 'offsides' then stat_value end), 0) as offsides,
        coalesce(max(case when stat_key = 'successfulDribbles' then stat_value end), 0) as successful_dribbles,
        coalesce(max(case when stat_key = 'unsuccessfulDribbles' then stat_value end), 0) as unsuccessful_dribbles,
        coalesce(max(case when stat_key = 'totalTouchesInOppositionBox' then stat_value end), 0) as touches_opposition_box,
        coalesce(max(case when stat_key = 'blocks' then stat_value end), 0) as blocks,
        coalesce(max(case when stat_key = 'totalClearances' then stat_value end), 0) as clearances,
        coalesce(max(case when stat_key = 'totalFoulsWon' then stat_value end), 0) as fouls_won,
        coalesce(max(case when stat_key = 'totalFoulsConceded' then stat_value end), 0) as fouls_conceded,
        coalesce(max(case when stat_key = 'savesMade' then stat_value end), 0) as saves_made,
        coalesce(max(case when stat_key = 'penaltiesSaved' then stat_value end), 0) as penalties_saved,
        coalesce(max(case when stat_key = 'goalKicks' then stat_value end), 0) as goal_kicks,
        coalesce(max(case when stat_key = 'touches' then stat_value end), 0) as touches,

        -- Participation
        coalesce(max(case when stat_key = 'gamesOver45Minutes' then stat_value end), 0) as games_over_45_minutes,
        coalesce(max(case when stat_key = 'gamesUnder45Minutes' then stat_value end), 0) as games_under_45_minutes,

        -- Defensive
        coalesce(max(case when stat_key = 'goalsConcededInsideBox' then stat_value end), 0) as goals_conceded_inside_box,
        coalesce(max(case when stat_key = 'goalsConcededOutsideBox' then stat_value end), 0) as goals_conceded_outside_box,
        coalesce(max(case when stat_key = 'timesTackled' then stat_value end), 0) as times_tackled,

        -- Goalkeeper
        coalesce(max(case when stat_key = 'catches' then stat_value end), 0) as catches,
        coalesce(max(case when stat_key = 'punches' then stat_value end), 0) as punches,
        coalesce(max(case when stat_key = 'drops' then stat_value end), 0) as drops,
        coalesce(max(case when stat_key = 'penaltiesFaced' then stat_value end), 0) as penalties_faced,

        -- Attacking
        coalesce(max(case when stat_key = 'goalsFromInsideBox' then stat_value end), 0) as goals_from_inside_box,
        coalesce(max(case when stat_key = 'goalsFromOutsideBox' then stat_value end), 0) as goals_from_outside_box,
        coalesce(max(case when stat_key = 'headedGoals' then stat_value end), 0) as headed_goals,
        coalesce(max(case when stat_key = 'leftFootGoals' then stat_value end), 0) as left_foot_goals,
        coalesce(max(case when stat_key = 'rightFootGoals' then stat_value end), 0) as right_foot_goals,
        coalesce(max(case when stat_key = 'penaltyGoals' then stat_value end), 0) as penalty_goals,
        coalesce(max(case when stat_key = 'winningGoal' then stat_value end), 0) as winning_goal,

        -- Passing & Ball Control
        coalesce(max(case when stat_key = 'backwardPasses' then stat_value end), 0) as backward_passes,
        coalesce(max(case when stat_key = 'throughBalls' then stat_value end), 0) as through_balls,
        coalesce(max(case when stat_key = 'successfulLongPasses' then stat_value end), 0) as successful_long_passes,
        coalesce(max(case when stat_key = 'unsuccessfulLongPasses' then stat_value end), 0) as unsuccessful_long_passes,
        coalesce(max(case when stat_key = 'successfulShortPasses' then stat_value end), 0) as successful_short_passes,
        coalesce(max(case when stat_key = 'unsuccessfulShortPasses' then stat_value end), 0) as unsuccessful_short_passes,
        coalesce(max(case when stat_key = 'totalLossesofPossession' then stat_value end), 0) as total_losses_of_possession,

        -- Duels
        coalesce(max(case when stat_key = 'aerialDuelsLost' then stat_value end), 0) as aerial_duels_lost,
        coalesce(max(case when stat_key = 'groundDuelsLost' then stat_value end), 0) as ground_duels_lost,

        -- Discipline
        coalesce(max(case when stat_key = 'straightRedCards' then stat_value end), 0) as straight_red_cards,
        coalesce(max(case when stat_key = 'foulAttemptedTackle' then stat_value end), 0) as foul_attempted_tackle,

        -- Crossing & Corners
        coalesce(max(case when stat_key = 'cornersWon' then stat_value end), 0) as corners_won,
        coalesce(max(case when stat_key = 'cornersTaken' then stat_value end), 0) as corners_taken,
        coalesce(max(case when stat_key = 'successfulCrossesCorners' then stat_value end), 0) as successful_crosses_corners,
        coalesce(max(case when stat_key = 'unsuccessfulCrossesCorners' then stat_value end), 0) as unsuccessful_crosses_corners,
        coalesce(max(case when stat_key = 'successfulCrossesopenplay' then stat_value end), 0) as successful_crosses_open_play,
        coalesce(max(case when stat_key = 'unsuccessfulCrossesopenplay' then stat_value end), 0) as unsuccessful_crosses_open_play,

        -- Recovery & Clearance
        coalesce(max(case when stat_key = 'blockedShots' then stat_value end), 0) as blocked_shots,

        -- Possession & Territory
        coalesce(max(case when stat_key = 'successfulPassesOwnHalf' then stat_value end), 0) as successful_passes_own_half,
        coalesce(max(case when stat_key = 'unsuccessfulPassesOwnHalf' then stat_value end), 0) as unsuccessful_passes_own_half,
        coalesce(max(case when stat_key = 'successfulPassesOppositionHalf' then stat_value end), 0) as successful_passes_opposition_half,
        coalesce(max(case when stat_key = 'unsuccessfulPassesOppositionHalf' then stat_value end), 0) as unsuccessful_passes_opposition_half
    from lines
    group by player_id
)

select
    p.*,

    case when p.total_passes > 0
        then round(100.0 * p.successful_passes / p.total_passes, 2)
        else 0
    end as pass_accuracy_pct,

    case when p.minutes_played > 0
        then round(90.0 * p.goals / p.minutes_played, 3)
        else 0
    end as goals_per_90,

    case when p.minutes_played > 0
        then round(90.0 * p.assists / p.minutes_played, 3)
        else 0
    end as assists_per_90,

    case when p.duels > 0
        then round(100.0 * p.duels_won / p.duels, 2)
        else 0
    end as duel_win_pct,

    case when p.total_shots > 0
        then round(100.0 * p.shots_on_target / p.total_shots, 2)
        else 0
    end as shot_on_target_pct
from pivot as p
