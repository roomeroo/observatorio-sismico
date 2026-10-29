# Design

## Context

See `proposal.md` for motivation and scope; behavior contracts are in `specs/event-processing-and-quality/spec.md`. The existing consumer starts an `AIOKafkaConsumer` with auto-commit disabled and waits without subscribing or reading. It opens one PostgreSQL connection after dependency readiness. The only checked-in SQL initialization creates the `observatorio` schema; no event tables or migration runner exist. Compose already runs the five required services, and the producer's live topic defaults to `earthquakes-live`.

The existing pipeline contracts require current and historical event versions, durable quarantine, idempotency, and PostgreSQL commit before Kafka offset confirmation. They leave the missing-identity/version policy and conflicting payloads with equal `(id, updated)` unresolved; those questions remain as listed in the proposal and must not be silently decided by schema or tests.

## Goals / Non-Goals

**Goals:**

- Process records sequentially per consumer instance so an offset cannot be confirmed ahead of an earlier uncommitted record in the same partition.
- Give accepted events, their version history, and rejected messages durable PostgreSQL representations.
- Make transaction boundaries, repeat delivery, broker references, and PostgreSQL recovery observable in tests.
- Apply schema changes to existing persisted databases without deleting or recreating their volumes.

**Non-Goals:**

- Add a new service, broker, database, external dependency, replay consumer, or distributed transaction.
- Decide the unresolved validation and same-version collision policies recorded in the proposal.
- Enrich events with Natural Earth or implement API queries against the resulting tables.

## Decisions

### Consume the existing configurable live topic without auto-commit

Read `KAFKA_TOPIC` in the consumer with default `earthquakes-live`, and pass the same setting through the existing Compose consumer service. Retain the current consumer group and disabled auto-commit. Process one record at a time and explicitly commit the record's next offset only after its PostgreSQL transaction succeeds.

**Alternative considered:** Enable auto-commit or process records concurrently. Rejected because either can advance a partition past a record whose database transaction has not committed.

### Separate accepted versions, current state, and quarantine

Use PostgreSQL tables in the existing `observatorio` schema for (1) accepted source versions, including original GeoJSON and extraction context; (2) one current projection per event ID; and (3) rejected source messages with the exact Kafka value bytes, an optional decoded envelope, reason, and Kafka topic/partition/offset. Store the Kafka reference on accepted versions as well to retain processing traceability. Keep country enrichment fields nullable or absent until the separate geographic-enrichment change.

Use database uniqueness/conditional updates to make ordinary duplicate versions and repeated broker deliveries idempotent. Exact constraints for colliding payloads with the same event ID and `updated` timestamp depend on the unresolved proposal question; do not pick a winner or silently overwrite while that question remains open.

**Alternative considered:** Store only the latest event. Rejected because the existing F-06 contract requires observed versions to remain available. Put rejected records only in application logs. Rejected because a log is not durable quarantine and cannot prove offset-safe recovery.

### Commit persistence before Kafka offsets

For each record, decode and validate the envelope, then use one PostgreSQL transaction for either accepted-event/version writes and current-state advancement, or the quarantine insert. After transaction completion, explicitly commit the Kafka offset. If the transaction or connection fails, do not commit the offset; close/re-establish the database connection and retry processing after readiness. Keep validation rejection distinct from database/transport errors: only a documented invalid message enters quarantine.

**Alternative considered:** Commit the Kafka offset before writing or use a distributed Kafka/PostgreSQL transaction. The first can lose input; the second is not required by the project and adds unnecessary coupling.

### Preserve source values and transform only documented fields

Persist the original feature as JSONB with `source`, `ingested_at`, and `mode` from the producer envelope. Parse occurrence and update timestamps from Unix milliseconds as UTC for typed query fields while retaining original millisecond values/context. Preserve optional magnitude and location values as null when absent; do not normalize the original event, infer country, or invent fallback identity/version values.

**Alternative considered:** Replace the original payload with normalized columns only. Rejected because it loses traceability and contradicts the source-retention requirements.

### Apply schema evolution without resetting PostgreSQL data

Add a small, ordered, idempotent schema migration mechanism using the existing Python/PostgreSQL stack, or an equivalently verified deployment path. It must create the new tables and indexes on the existing persistent database without dropping data or requiring `docker compose down -v`. Do not rely solely on PostgreSQL's one-time `/docker-entrypoint-initdb.d` scripts for an already-initialized named volume.

**Alternative considered:** Delete the PostgreSQL volume or assume init scripts rerun. Rejected because both risk existing data and do not support upgrading an initialized Compose deployment.

### Test with synthetic messages and isolated PostgreSQL state

Use synthetic producer-compatible envelopes and controlled Kafka records; no test calls USGS. Unit tests use fake Kafka/connection boundaries to assert DB commit precedes offset commit and that failures leave offsets uncommitted. PostgreSQL integration tests apply the migration and exercise version, current-state, and quarantine constraints in an isolated test database or schema. A broker-backed smoke test may use the existing Compose Kafka service and a synthetic topic/record; it must not write fixtures into user data or require a new permanent Compose service.

**Alternative considered:** Use only mocks for the SQL layer. Rejected because they cannot verify PostgreSQL constraints, transaction rollback, migration behavior, or JSONB persistence.

## Risks / Trade-offs

- [Risk] A crash after PostgreSQL commit but before offset commit causes redelivery → use database idempotency for accepted versions and quarantine broker references.
- [Risk] A prolonged PostgreSQL outage can hold a partition and delay later records → leave offsets uncommitted, report the failure, and resume through connection recovery rather than silently skipping input.
- [Risk] A migration applied to the wrong database/schema can affect existing data → use the configured PostgreSQL database, schema-qualified objects, idempotent migrations, and isolated integration-test databases; never drop the persistent volume.
- [Risk] Missing identity/version and same-timestamp payload conflicts lack approved semantics → keep both listed in the proposal as explicit decisions pending; do not implement fallback or winner behavior until resolved.
- [Risk] Optional columns may be interpreted as measured zero by later consumers → preserve nulls and original JSON values.

## Migration Plan

1. Define and test an additive migration that creates version-history, current-event, quarantine, and migration-tracking structures in `observatorio`.
2. Apply pending migrations before the consumer begins reading, without removing existing PostgreSQL volumes or the producer's separate SQLite checkpoint.
3. Roll back by stopping the consumer and reverting application code; retain additive tables and stored records. Do not automatically drop tables or data during rollback.
4. Verify startup and migration behavior against both an empty test database and a database representing the existing initialized Compose volume.
