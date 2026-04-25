-- fan_events_ingested v1 — see specs/005-compose-kafka-pipeline/contracts/ingestion-persistence-v1.md
-- event_type: JSON top-level "event" string; if absent, application inserts sentinel 'unknown'.

CREATE SCHEMA IF NOT EXISTS raw_data;

CREATE TABLE IF NOT EXISTS raw_data.fan_events_ingested (
    id BIGSERIAL PRIMARY KEY,
    ingested_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    kafka_topic TEXT NOT NULL,
    kafka_partition INTEGER NOT NULL CHECK (kafka_partition >= 0),
    kafka_offset BIGINT NOT NULL,
    event_type TEXT NOT NULL,
    event_time TIMESTAMPTZ,
    payload_json JSONB NOT NULL,
    CONSTRAINT fan_events_ingested_kafka_coord_uniq UNIQUE (kafka_topic, kafka_partition, kafka_offset)
);

COMMENT ON COLUMN raw_data.fan_events_ingested.event_type IS
    'From JSON event field; missing or non-string values mapped to sentinel unknown by ingest.';
