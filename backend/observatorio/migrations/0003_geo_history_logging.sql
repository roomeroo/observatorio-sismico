-- Additive migration: geographic enrichment, dimensions, producer logging, history.
ALTER TABLE observatorio.event_versions ADD COLUMN IF NOT EXISTS country_id TEXT;
ALTER TABLE observatorio.event_versions ADD COLUMN IF NOT EXISTS geo_ambiguous BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE observatorio.current_events ADD COLUMN IF NOT EXISTS country_id TEXT;
ALTER TABLE observatorio.current_events ADD COLUMN IF NOT EXISTS geo_ambiguous BOOLEAN NOT NULL DEFAULT FALSE;

CREATE TABLE IF NOT EXISTS observatorio.dim_country (
    country_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    iso_a2 TEXT,
    continent TEXT,
    subregion TEXT
);

CREATE TABLE IF NOT EXISTS observatorio.dim_date (
    date_key DATE PRIMARY KEY,
    year INTEGER NOT NULL,
    month INTEGER NOT NULL,
    day INTEGER NOT NULL,
    iso_week INTEGER NOT NULL,
    day_of_week INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS observatorio.raw_payloads (
    payload_hash TEXT PRIMARY KEY,
    payload JSONB NOT NULL,
    first_seen_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);

CREATE TABLE IF NOT EXISTS observatorio.poll_log (
    id BIGSERIAL PRIMARY KEY,
    polled_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    status TEXT NOT NULL,
    latency_ms INTEGER,
    feed_count INTEGER,
    published_count INTEGER,
    excluded_count INTEGER,
    error TEXT,
    payload_hash TEXT REFERENCES observatorio.raw_payloads(payload_hash)
);

CREATE TABLE IF NOT EXISTS observatorio.poll_exclusions (
    id BIGSERIAL PRIMARY KEY,
    poll_id BIGINT REFERENCES observatorio.poll_log(id) ON DELETE CASCADE,
    event_id TEXT,
    reason TEXT NOT NULL,
    event_type TEXT,
    place TEXT,
    excluded_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);

CREATE TABLE IF NOT EXISTS observatorio.extraction_queries (
    id BIGSERIAL PRIMARY KEY,
    source TEXT NOT NULL,
    url TEXT NOT NULL,
    params JSONB NOT NULL,
    starttime TIMESTAMPTZ,
    endtime TIMESTAMPTZ,
    status TEXT NOT NULL,
    result_count INTEGER,
    file_path TEXT,
    file_sha256 TEXT,
    executed_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);

CREATE TABLE IF NOT EXISTS observatorio.historical_events (
    event_id TEXT PRIMARY KEY,
    time_utc TIMESTAMPTZ,
    updated_utc TIMESTAMPTZ,
    mag DOUBLE PRECISION,
    mag_type TEXT,
    place TEXT,
    event_type TEXT,
    longitude DOUBLE PRECISION NOT NULL,
    latitude DOUBLE PRECISION NOT NULL,
    depth DOUBLE PRECISION,
    country_id TEXT,
    geo_ambiguous BOOLEAN NOT NULL DEFAULT FALSE,
    query_id BIGINT REFERENCES observatorio.extraction_queries(id)
);

CREATE INDEX IF NOT EXISTS idx_current_events_country_time ON observatorio.current_events(country_id, time_utc);
CREATE INDEX IF NOT EXISTS idx_current_events_mag ON observatorio.current_events(mag);
CREATE INDEX IF NOT EXISTS idx_historical_events_time ON observatorio.historical_events(time_utc);
CREATE INDEX IF NOT EXISTS idx_poll_log_polled_at ON observatorio.poll_log(polled_at);
