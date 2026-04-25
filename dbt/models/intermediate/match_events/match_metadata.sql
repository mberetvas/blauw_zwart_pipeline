-- One row per match_id with calendar metadata propagated through v2 event payloads.
select distinct on (match_id)
    match_id,
    kickoff_local,
    timezone,
    attendance,
    home_away,
    encounter_type,
    opponent,
    home_score,
    away_score,
    venue_label,
    club_home_club,
    club_home_stadium,
    club_home_stadium_capacity,
    club_home_reported_total_attendance,
    club_home_reported_average_attendance,
    club_home_reported_home_matches,
    club_home_reported_sold_out_matches,
    club_home_reported_capacity_pct
from {{ ref('match_events') }}
order by match_id, ingested_at desc, id desc