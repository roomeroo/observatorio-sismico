# Event Processing and Quality

## Purpose

Specify validation, transformation, version persistence, idempotent consumption, and durable handling of rejected input.

## Requirements

### Requirement: [F-05] Validate, transform, persist, and quarantine consumed messages

The consumer MUST validate and transform consumed events, preserve the original event and extraction context needed for traceability, and persist accepted data. It MUST durably retain rejected input with its rejection reason and a reference to the original message before advancing past that message. Rejected input MUST NOT be silently discarded or block the whole queue indefinitely.

Priority: Explicitly required.
Traceability: `docs/ENUNCIADO (1).md` §5–§7, §11; `docs/FAQ.md` Q13, Q16–Q17.

#### Scenario: Valid event is consumed

- **GIVEN** a valid event message is available in Kafka
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

### Requirement: [F-06] Preserve event versions and maintain one current version

Persistence MUST retain observed versions and expose one current version per event ID. A later version updates current state without erasing history; an older redelivery cannot replace it. Effects MUST be idempotent under at-least-once delivery; a distributed Kafka–PostgreSQL transaction is not required.

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

### Requirement: [F-13] Provide evidence-based data-quality analysis

The report or notebook MUST document quality checks, dataset/period/denominator, code, results, actions, and limitations. Separate artificial tests from real data; automated reports and a quality dashboard are optional.

Priority: Required evidence; automation is optional.
Traceability: `ENUNCIADO (1).md` §6, §12–13; `FAQ.md` Q16–17, Q34–35; `README (1).md` §6.

#### Scenario: Quality evidence is reviewed

- **GIVEN** real source and prepared datasets have been analyzed
- **WHEN** the quality section is presented
- **THEN** it identifies the analyzed set and period, denominator, queries or code, results, actions, and limitations
- **AND** reports applicable before/after results without conflating overlapping issue counts
- **AND** considers completeness, uniqueness, validity, consistency, timeliness, and accuracy where verifiable
- **AND** justifies a dimension that cannot be verified

#### Scenario: A quality dimension cannot be verified

- **GIVEN** a quality dimension cannot be verified from available data
- **WHEN** the analysis documents that dimension
- **THEN** it states the limitation instead of claiming an unsupported result

#### Scenario: Artificially damaged data is used for testing

- **GIVEN** artificial invalid records are created to test validation
- **WHEN** they are included in test evidence
- **THEN** they are explicitly identified and kept separate from real seismic observations

#### Scenario: Optional quality automation is absent

- **GIVEN** the project provides the required written or notebook evidence and durable quarantine
- **WHEN** it is evaluated
- **THEN** absence of an automatic report generator, quality metrics table, or Angular quality panel does not by itself fail this requirement

## Clarifications Pending

- The documents do not define behavior for two different payloads with the same event ID and identical `updated` timestamp.
- The documents do not state a handling rule for missing event IDs or unparseable/missing `updated`; the implementation must make and document a decision without treating it as an approved source requirement.
