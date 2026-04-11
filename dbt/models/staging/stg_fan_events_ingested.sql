-- Staging view over the ingest table; extend with column renames / casts as needed.
select
    id,
    ingested_at,
    kafka_topic,
    kafka_partition,
    kafka_offset,
    event_type,
    event_time,
    payload_json
from {{ source('fan_pipeline', 'fan_events_ingested') }}
