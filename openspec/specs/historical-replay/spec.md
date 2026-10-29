# Historical Replay

## Purpose

Define an isolated, accelerated Kafka replay path that makes the end-to-end pipeline demonstrable without depending on new earthquakes.

## Requirements

### Requirement: [F-12] Replay historical events through Kafka without mixing live data

The system MUST replay selected historical events through Kafka and the consumer, preserving occurrence time and recording replay time. Replay MUST be isolated from live data, labeled “REPRODUCCIÓN”, and queryable by its historical interval. Demonstrations MUST include controlled duplicates and revisions.

Priority: Required for demonstration.
Traceability: `docs/ENUNCIADO (1).md` §5, §11; `docs/FAQ.md` Q6, Q21, Q32, Q35.

#### Scenario: Historical events are replayed

- **GIVEN** a selected historical dataset is available for demonstration
- **WHEN** replay is started
- **THEN** selected events are published through Kafka and processed by the consumer
- **AND** their original occurrence timestamps remain unchanged
- **AND** replay time and replay mode are recorded
- **AND** the replay is visibly labeled “REPRODUCCIÓN”

#### Scenario: Live and replay records coexist

- **GIVEN** live records are present in the system
- **WHEN** replay records are processed and queried
- **THEN** replay records remain isolated from live records by a separate topic and storage/schema or equivalent mechanism

#### Scenario: Historical replay is queried

- **GIVEN** replay records have occurrence dates outside the recent 24-hour default
- **WHEN** the replay view is opened
- **THEN** it queries the relevant historical interval and isolated replay data
- **AND** does not alter original event dates to make those events appear

#### Scenario: Replay demonstrates idempotency

- **GIVEN** controlled duplicate and revision messages are included in the replay
- **WHEN** the consumer processes them
- **THEN** the observed result matches the duplicate and revision behavior in the event-processing specification

## Clarifications Pending

- The exact user interface and API mechanism for selecting replay mode and historical intervals are not specified.
- The treatment of `last_ingestion` and health state when replay data is queried is not defined; replay time MUST NOT be misrepresented as a live USGS ingestion.
