# Tasks

## 1. Resolve documented ambiguities

- [ ] 1.1 Obtain an explicit decision on handling missing/invalid `id` or `updated`, and on distinct payloads sharing the same `(event_id, updated)`; update the proposal, delta scenarios, and test cases to encode the decision without inventing fallback values.

## 2. Add durable PostgreSQL structures

- [ ] 2.1 Implement additive, ordered migrations in the existing `observatorio` schema for event versions, current events, quarantine records, and migration tracking; verify migrations apply and rerun safely against an isolated PostgreSQL database without deleting existing data.
- [ ] 2.2 Add PostgreSQL integration tests for migration compatibility with the current initialized schema and existing-volume shape; verify exact source-feature JSON and extraction metadata can be stored and read back.
- [ ] 2.3 Document the new persistence model, version/history distinction, quarantine fields, and non-destructive migration procedure in `backend/README.md`; verify the documented steps do not remove Compose volumes.

## 3. Validate input and durably quarantine rejected messages

- [ ] 3.1 Implement decoding and validation for the live producer envelope and documented GeoJSON fields, preserving original bytes/event and extraction context; verify synthetic fixtures cover valid messages, malformed JSON/envelopes, invalid geometry/coordinates, optional values, UTC timestamps, and the decision from task 1.1.
- [ ] 3.2 Implement quarantine writes containing raw Kafka value bytes, rejection reason, topic, partition, and offset; verify with PostgreSQL tests that a rejected message is durable and duplicate delivery of the same broker record does not duplicate quarantine effects.
- [ ] 3.3 Verify validation failures enter quarantine while database/transport failures roll back and remain unacknowledged; test both branches using controlled transaction failures and fake Kafka records.

## 4. Persist versions and maintain current state idempotently

- [ ] 4.1 Persist each accepted source version and its original feature transactionally, and advance the current projection only for a later `updated`; verify PostgreSQL tests for first version, duplicate delivery, later revision, and older redelivery.
- [ ] 4.2 Verify a failed event/version transaction leaves both history and current state unchanged, while successful commits retain extraction context and UTC-converted timestamps without replacing optional nulls with zero.
- [ ] 4.3 Document version retention, current-state semantics, and known validation limits in `backend/README.md`; verify terminology does not imply geographic enrichment, replay, or API implementation.

## 5. Consume Kafka with commit-after-transaction recovery

- [ ] 5.1 Subscribe to configurable `KAFKA_TOPIC` (default `earthquakes-live`) in the existing consumer group, process records sequentially with auto-commit disabled, and explicitly commit each next offset only after its accepted-event or quarantine transaction; verify call-order tests assert DB commit precedes Kafka commit.
- [ ] 5.2 Handle PostgreSQL unavailability without acknowledging the current record and reconnect/retry after readiness; verify a controlled failure followed by recovery processes the same record once effectively and eventually commits its offset.
- [ ] 5.3 Pass the same topic setting to the existing Compose consumer without adding services or changing topology; verify `docker compose config` shows exactly five services and matching producer/consumer topics.
- [ ] 5.4 Document how to start, inspect, and stop the consumer and how to interpret database/processing failures; verify README claims distinguish consumer readiness from completed event processing.

## 6. Verify the integrated consumer path

- [ ] 6.1 Run the backend test suite and PostgreSQL migration/integration tests with synthetic envelopes only; verify tests make no calls to USGS and preserve any pre-existing local Compose volumes.
- [ ] 6.2 Run a controlled end-to-end test with Kafka records and isolated PostgreSQL state; verify valid event persistence, duplicate/revision/old-version behavior, quarantine durability, PostgreSQL recovery, and commit-after-transaction ordering.
- [ ] 6.3 Review the final diff and Compose configuration; verify no Natural Earth enrichment, functional API endpoints, historical loading, replay, frontend, or API-contract changes are included.
