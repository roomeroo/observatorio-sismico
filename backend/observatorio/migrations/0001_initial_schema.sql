CREATE SCHEMA IF NOT EXISTS observatorio;

CREATE TABLE IF NOT EXISTS observatorio.schema_migrations (
    version VARCHAR(255) PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);
