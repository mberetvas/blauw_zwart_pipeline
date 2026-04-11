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
    payload_json->>'location' as location,
    payload_json->>'item' as item,
    (payload_json->>'amount')::numeric as amount
from {{ ref('stg_fan_events_ingested') }}
where event_type = 'merch_purchase'
