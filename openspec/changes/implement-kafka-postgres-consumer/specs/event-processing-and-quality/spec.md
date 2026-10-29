# Spec Delta

## MODIFIED Requirements

### Requirement: [F-05] Validate, transform, persist, and quarantine consumed messages

The consumer MUST consume the configured live Kafka topic, validate and transform messages under documented rules, preserve the original event and extraction context, and persist accepted data. It MUST durably retain rejected input with its rejection reason and Kafka topic, partition, and offset before advancing past that message. It MUST confirm offsets only after the corresponding PostgreSQL transaction commits. Rejected input MUST NOT be silently discarded or block the whole queue indefinitely.

Priority: Explicitly required.
Traceability: `docs/ENUNCIADO (1).md` §5–§7, §11; `docs/FAQ.md` Q13, Q16–Q17.

#### Scenario: Valid event is consumed

- **GIVEN** a valid live event message is available in Kafka
- **WHEN** the consumer processes it
- **THEN** it validates and prepares the event and persists the resulting data transactionally
- **AND** it confirms the Kafka offset only after the database transaction commits

#### Scenario: Event cannot be processed

- **GIVEN** a message contains an event that cannot be treated under the documented validation rules
- **WHEN** the consumer rejects it
- **THEN** the original input, rejection reason, and message reference are durably retained before the offset advances
- **AND** the rejected record is not represented as a valid event

#### Scenario: Invalid coordinates are received

- **GIVEN** an event contains coordinates outside valid geographic ranges or otherwise unusable geometry
- **WHEN** the consumer validates it
- **THEN** it is quarantined with a reason and is not exposed as an invented map point

#### Scenario: Optional magnitude is absent

- **GIVEN** an otherwise processable event has a null or missing magnitude
- **WHEN** the consumer prepares it
- **THEN** the unknown magnitude remains null rather than being replaced with zero
- **AND** the event remains available for views that do not require a magnitude value

#### Scenario: Timestamp and unusual values are transformed

- **GIVEN** an event contains Unix-millisecond timestamps or an unusual magnitude/depth value
- **WHEN** it is transformed
- **THEN** timestamps are interpreted in UTC and their original units/context are retained
- **AND** a negative magnitude or depth is not rejected solely for being negative without investigation

#### Scenario: Consumer stops after database commit

- **GIVEN** the database transaction committed but the Kafka offset was not confirmed
- **WHEN** Kafka delivers the message again after consumer restart
- **THEN** processing the redelivery does not duplicate its persisted effects

#### Scenario: PostgreSQL is unavailable while processing a message

- **GIVEN** a message is available but PostgreSQL cannot commit its transaction
- **WHEN** the consumer attempts to persist the event or quarantine record
- **THEN** it does not confirm the Kafka offset
- **AND** it can process the message after PostgreSQL becomes available again

#### Scenario: A rejected message is quarantined before its offset advances

- **GIVEN** a Kafka message is rejected by documented validation
- **WHEN** the consumer records the rejection
- **THEN** the original input, reason, topic, partition, and offset are committed durably
- **AND** the offset is confirmed only after that commit

### Requirement: [F-06] Preserve event versions and maintain one current version

Persistence MUST retain observed event versions and expose one current version per event ID. A later version updates current state without erasing history; an older redelivery cannot replace it. Effects MUST be idempotent under at-least-once delivery; a distributed Kafka–PostgreSQL transaction is not required.

Priority: Explicitly required.
Traceability: `docs/ENUNCIADO (1).md` §7, §11; `docs/FAQ.md` Q12–Q15, Q20.

#### Scenario: Version sequence contains duplicates and a revision

- **GIVEN** an empty database receives E1 at `updated=10:05`, the same version again, E1 at `updated=10:09`, the old E1 version again, and E2
- **WHEN** the consumer finishes processing the sequence
- **THEN** there are two current events
- **AND** current E1 contains the `10:09` version
- **AND** three distinct versions are retained

#### Scenario: Revision changes event time or attributes

- **GIVEN** a later version changes an event's magnitude, location, or occurrence time
- **WHEN** the consumer commits that version
- **THEN** the current state reflects the later version
- **AND** dependent aggregates can be recalculated from current state or corrected for affected windows
