-- Fan activity tied to a match: envelope fields plus optional merch columns when applicable.
select
    id,
    ingested_at,
    kafka_topic,
    kafka_partition,
    kafka_offset,
    event_type,
    event_time,
    payload_json->>'fan_id' as fan_id,
    payload_json->>'match_id' as match_id,
    payload_json->>'location' as location,
    payload_json->>'item' as item,
    (payload_json->>'amount')::numeric as amount
from {{ ref('stg_fan_events_ingested') }}
where payload_json->>'match_id' is not null
    and payload_json->>'match_id' != ''
