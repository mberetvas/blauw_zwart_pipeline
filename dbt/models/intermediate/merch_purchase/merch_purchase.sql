-- Merchandise purchase rows parsed from NDJSON payloads (event_type = merch_purchase).
select
    id,
    ingested_at,
    kafka_topic,
    kafka_partition,
    kafka_offset,
    event_time,
    payload_json->>'fan_id' as fan_id,
    payload_json->>'match_id' as match_id,
    payload_json->>'kickoff_local' as kickoff_local,
    payload_json->>'timezone' as timezone,
    (payload_json->>'attendance')::integer as attendance,
    payload_json->>'home_away' as home_away,
    payload_json->>'encounter_type' as encounter_type,
    payload_json->>'opponent' as opponent,
    (payload_json->>'home_score')::integer as home_score,
    (payload_json->>'away_score')::integer as away_score,
    payload_json->>'venue_label' as venue_label,
    payload_json->>'club_home_club' as club_home_club,
    payload_json->>'club_home_stadium' as club_home_stadium,
    (payload_json->>'club_home_stadium_capacity')::integer as club_home_stadium_capacity,
    (payload_json->>'club_home_reported_total_attendance')::integer
        as club_home_reported_total_attendance,
    (payload_json->>'club_home_reported_average_attendance')::integer
        as club_home_reported_average_attendance,
    (payload_json->>'club_home_reported_home_matches')::integer
        as club_home_reported_home_matches,
    (payload_json->>'club_home_reported_sold_out_matches')::integer
        as club_home_reported_sold_out_matches,
    (payload_json->>'club_home_reported_capacity_pct')::numeric
        as club_home_reported_capacity_pct,
    payload_json->>'location' as location,
    payload_json->>'item' as item,
    (payload_json->>'amount')::numeric as amount
from {{ ref('stg_fan_events_ingested') }}
where event_type = 'merch_purchase'
