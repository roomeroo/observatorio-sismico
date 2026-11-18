-- Isolated schema for accelerated replay: same tables as the live schema, never mixed with it.
CREATE SCHEMA IF NOT EXISTS replay;

CREATE TABLE IF NOT EXISTS replay.event_versions (LIKE observatorio.event_versions INCLUDING ALL);
CREATE TABLE IF NOT EXISTS replay.current_events (LIKE observatorio.current_events INCLUDING ALL);

CREATE TABLE IF NOT EXISTS replay.quarantine_records (
    id BIGSERIAL PRIMARY KEY,
    kafka_topic TEXT NOT NULL,
    kafka_partition INTEGER NOT NULL,
    kafka_offset BIGINT NOT NULL,
    raw_payload BYTEA NOT NULL,
    rejection_reason TEXT NOT NULL,
    decoded_envelope JSONB,
    quarantined_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT uq_replay_quarantine_kafka_record UNIQUE (kafka_topic, kafka_partition, kafka_offset)
);
