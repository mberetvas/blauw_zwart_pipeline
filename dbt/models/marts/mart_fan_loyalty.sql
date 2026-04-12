-- Fan loyalty mart: one row per fan with lifetime purchase and attendance metrics.
-- Aggregates stadium merchandise, retail, and match-attendance data for LLM Q&A.
--
-- Incremental strategy (delete+insert on unique_key = fan_id):
--   On each run, only fans whose source records arrived after the watermark
--   (last_updated_at) are reprocessed. Their old row is deleted and the freshly
--   recomputed row is re-inserted. A full refresh (`dbt run --full-refresh`)
--   rebuilds the table from scratch.
{{
    config(
        materialized = 'incremental',
        unique_key = 'fan_id',
        incremental_strategy = 'delete+insert',
        tags = ['mart', 'fan_loyalty']
    )
}}

-- Fans with any new source event since the last mart refresh.
-- On a full refresh (or the very first run) every fan is included.
with new_or_updated_fans as (
    {% if is_incremental() %}
    select distinct fan_id
    from (
        select fan_id, ingested_at from {{ ref('merch_purchase') }}
        union all
        select fan_id, ingested_at from {{ ref('retail_purchase') }}
        union all
        select fan_id, ingested_at from {{ ref('match_events') }}
    ) all_source_events
    where ingested_at > (
        select coalesce(max(last_updated_at), '1970-01-01'::timestamptz)
        from {{ this }}
    )
    {% else %}
    select distinct fan_id from {{ ref('merch_purchase') }}
    union
    select distinct fan_id from {{ ref('retail_purchase') }}
    {% endif %}
),

merch_agg as (
    select
        fan_id,
        count(id)                               as merch_purchase_count,
        coalesce(sum(amount), 0)                as merch_total_spend,
        mode() within group (order by item)     as favourite_merch_item,
        max(ingested_at)                        as last_ingested_at
    from {{ ref('merch_purchase') }}
    where fan_id in (select fan_id from new_or_updated_fans)
    group by fan_id
),

retail_agg as (
    select
        fan_id,
        count(id)                               as retail_purchase_count,
        coalesce(sum(amount), 0)                as retail_total_spend,
        mode() within group (order by item)     as favourite_retail_item,
        mode() within group (order by shop)     as favourite_shop,
        max(ingested_at)                        as last_ingested_at
    from {{ ref('retail_purchase') }}
    where fan_id in (select fan_id from new_or_updated_fans)
    group by fan_id
),

attendance_agg as (
    select
        fan_id,
        count(distinct match_id)                as matches_attended,
        max(event_time)                         as last_match_attended,
        min(event_time)                         as first_match_attended,
        max(ingested_at)                        as last_ingested_at
    from {{ ref('match_events') }}
    where event_type = 'ticket_scan'
      and fan_id in (select fan_id from new_or_updated_fans)
    group by fan_id
)

select
    f.fan_id,

    -- Merchandise (stadium purchases tied to a match)
    coalesce(ma.merch_purchase_count, 0)                            as merch_purchase_count,
    coalesce(ma.merch_total_spend, 0)::numeric(12, 2)               as merch_total_spend,
    ma.favourite_merch_item,

    -- Retail (non-match channel purchases)
    coalesce(ra.retail_purchase_count, 0)                           as retail_purchase_count,
    coalesce(ra.retail_total_spend, 0)::numeric(12, 2)              as retail_total_spend,
    ra.favourite_retail_item,
    ra.favourite_shop,

    -- Combined spend
    (coalesce(ma.merch_total_spend, 0)
        + coalesce(ra.retail_total_spend, 0))::numeric(12, 2)       as total_spend,

    -- Match attendance
    coalesce(at.matches_attended, 0)                                as matches_attended,
    at.first_match_attended,
    at.last_match_attended,

    -- Watermark: latest ingested_at across all source tables for this fan.
    -- Used on the next incremental run to find newly arrived rows.
    greatest(
        coalesce(ma.last_ingested_at, '1970-01-01'::timestamptz),
        coalesce(ra.last_ingested_at, '1970-01-01'::timestamptz),
        coalesce(at.last_ingested_at, '1970-01-01'::timestamptz)
    )                                                               as last_updated_at

from new_or_updated_fans f
left join merch_agg      ma on f.fan_id = ma.fan_id
left join retail_agg     ra on f.fan_id = ra.fan_id
left join attendance_agg at on f.fan_id = at.fan_id
order by total_spend desc
