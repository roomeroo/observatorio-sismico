## ADDED Requirements

### Requirement: Select and query replay data through documented, isolated mechanisms

Replay MUST be started by a one-shot command that takes an occurrence-time interval and a speed factor, publishes in occurrence order to a dedicated replay topic, and appends controlled duplicate and older-revision messages. Replay data MUST be stored in a separate PostgreSQL schema and exposed by the API only when the client requests replay mode. Replay MUST NOT modify live tables or the live `last_ingestion` value.

#### Scenario: Replay is accelerated and ordered

- **GIVEN** a selected interval and a speed factor of 60
- **WHEN** replay runs
- **THEN** messages are published in ascending occurrence time with inter-message delay divided by the factor
- **AND** each message carries `mode: replay` and a replay timestamp

#### Scenario: Live queries ignore replay

- **GIVEN** replay data is loaded
- **WHEN** a client queries the API without replay mode
- **THEN** no replay event is returned and counts are unchanged

#### Scenario: Replay health is not a live ingestion

- **GIVEN** a client queries health in replay mode
- **WHEN** the response is built
- **THEN** it reports replay load time under a replay-specific field and leaves live `last_ingestion` untouched

#### Scenario: Controlled duplicates and revisions

- **GIVEN** the replay includes a duplicate and an older revision of one event
- **WHEN** the consumer processes them
- **THEN** the replay current-state count equals the number of unique events and the newest version is retained
