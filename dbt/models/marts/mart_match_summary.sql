-- Match summary mart: one row per match with calendar metadata, scoreline,
-- attendance, and aggregated synthetic fan-engagement metrics.
--
-- Incremental strategy (delete+insert on unique_key = match_id):
--   On each run, only matches with newly ingested source events since the last
--   mart refresh are reprocessed. Their old row is deleted and a freshly
--   recomputed row is inserted. A full refresh (`dbt run --full-refresh`)
--   rebuilds the table from scratch.
{{
    config(
        materialized = 'incremental',
        unique_key = 'match_id',
        incremental_strategy = 'delete+insert',
        tags = ['mart', 'match_summary']
    )
}}

with new_or_updated_matches as (
    {% if is_incremental() %}
    select distinct match_id
    from {{ ref('match_events') }}
    where ingested_at > (
        select coalesce(max(last_updated_at), '1970-01-01'::timestamptz)
        from {{ this }}
    )
    {% else %}
    select distinct match_id
    from {{ ref('match_metadata') }}
    {% endif %}
),

base as (
    select *
    from {{ ref('match_metadata') }}
    where match_id in (select match_id from new_or_updated_matches)
),

event_agg as (
    select
        match_id,
        count(id) as match_event_count,
        count(*) filter (where event_type = 'ticket_scan') as ticket_scan_count,
        count(distinct fan_id) filter (where event_type = 'ticket_scan')
            as ticket_scanned_fans,
        min(event_time) as first_event_time,
        max(event_time) as last_event_time,
        max(ingested_at) as last_ingested_at
    from {{ ref('match_events') }}
    where match_id in (select match_id from new_or_updated_matches)
    group by match_id
),

merch_agg as (
    select
        match_id,
        count(id) as merch_purchase_count,
        count(distinct fan_id) as unique_merch_buyers,
        coalesce(sum(amount), 0)::numeric(12, 2) as merch_revenue,
        mode() within group (order by item) as top_merch_item,
        max(ingested_at) as last_ingested_at
    from {{ ref('merch_purchase') }}
    where match_id in (select match_id from new_or_updated_matches)
    group by match_id
)

select
    b.match_id,
    b.kickoff_local::timestamp as kickoff_local,
    b.timezone,
    b.home_away,
    b.encounter_type,
    b.opponent,
    b.venue_label,

    b.home_score,
    b.away_score,
    case
        when b.home_away = 'home' then b.home_score
        else b.away_score
    end as club_brugge_score,
    case
        when b.home_away = 'home' then b.away_score
        else b.home_score
    end as opponent_score,
    case
        when (
            case
                when b.home_away = 'home' then b.home_score
                else b.away_score
            end
        ) > (
            case
                when b.home_away = 'home' then b.away_score
                else b.home_score
            end
        ) then 'win'
        when (
            case
                when b.home_away = 'home' then b.home_score
                else b.away_score
            end
        ) < (
            case
                when b.home_away = 'home' then b.away_score
                else b.home_score
            end
        ) then 'loss'
        else 'draw'
    end as match_result,

    b.attendance as reported_attendance,
    coalesce(e.match_event_count, 0) as match_event_count,
    coalesce(e.ticket_scan_count, 0) as ticket_scan_count,
    coalesce(e.ticket_scanned_fans, 0) as ticket_scanned_fans,
    case
        when b.attendance is not null and b.attendance > 0 then
            round((100.0 * coalesce(e.ticket_scan_count, 0) / b.attendance)::numeric, 1)
    end as ticket_scan_pct_of_reported_attendance,

    coalesce(m.merch_purchase_count, 0) as merch_purchase_count,
    coalesce(m.unique_merch_buyers, 0) as unique_merch_buyers,
    coalesce(m.merch_revenue, 0)::numeric(12, 2) as merch_revenue,
    m.top_merch_item,

    b.club_home_club,
    b.club_home_stadium,
    b.club_home_stadium_capacity,
    b.club_home_reported_total_attendance,
    b.club_home_reported_average_attendance,
    b.club_home_reported_home_matches,
    b.club_home_reported_sold_out_matches,
    b.club_home_reported_capacity_pct,
    case
        when b.home_away = 'home'
         and b.club_home_stadium_capacity is not null
         and b.club_home_stadium_capacity > 0
         and b.attendance is not null then
            round((100.0 * b.attendance / b.club_home_stadium_capacity)::numeric, 1)
    end as home_capacity_utilization_pct,
    case
        when b.home_away = 'home'
         and b.club_home_stadium_capacity is not null
         and b.attendance is not null then
            b.attendance >= b.club_home_stadium_capacity
    end as is_home_capacity_sellout,

    e.first_event_time,
    e.last_event_time,
    greatest(
        coalesce(e.last_ingested_at, '1970-01-01'::timestamptz),
        coalesce(m.last_ingested_at, '1970-01-01'::timestamptz)
    ) as last_updated_at

from base b
left join event_agg e on b.match_id = e.match_id
left join merch_agg m on b.match_id = m.match_id
order by kickoff_local, match_id
