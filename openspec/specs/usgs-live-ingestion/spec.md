# USGS Live Ingestion

## Purpose

Define how recent USGS earthquake data is polled, filtered, versioned, and published to Kafka without losing valid producer state when external requests fail.

## Requirements

### Requirement: [F-01] Poll and inspect the recent USGS feed

The producer MUST request the USGS `all_day.geojson` feed approximately every 60 seconds. It MUST treat the feed as a rolling 24-hour window, inspect the documented event fields, publish earthquake events, and retain the reason for excluding non-earthquake event types. The producer MUST document the source response, field types, units, optional fields, request frequency, errors, and latency.

Priority: Explicitly required.
Traceability: `docs/ENUNCIADO (1).md` §4.1; `docs/FAQ.md` Q8–Q10.

#### Scenario: Polling a successful feed response

- **GIVEN** the producer is running and USGS returns a valid feed response
- **WHEN** a polling cycle is due
- **THEN** the producer requests the rolling `all_day.geojson` feed and evaluates each event using its `type`
- **AND** events whose type is `earthquake` are eligible for publication
- **AND** an event of another type is excluded with its exclusion reason retained
- **AND** the broker address, topic, and polling frequency are configurable through environment variables

#### Scenario: Interpreting the feed window

- **GIVEN** two successive responses contain overlapping events
- **WHEN** the producer processes the later response
- **THEN** it treats the response as a complete rolling 24-hour window, not as a list of newly occurred events
- **AND** it does not infer deletion merely because an event ages out of the window

### Requirement: [F-03] Publish only new or later event versions

The producer MUST compare each event's `id` and `properties.updated` with persistent publication state. It MUST publish previously unknown events and later revisions, and MUST omit versions already published or older than the latest known version. The event ID MUST be the Kafka message key.

Priority: Explicitly required.
Traceability: `docs/ENUNCIADO (1).md` §5; `docs/FAQ.md` Q10–Q14.

#### Scenario: New event

- **GIVEN** an event ID is absent from persistent publication state
- **WHEN** the producer observes the event
- **THEN** it publishes the event to Kafka using its ID as the message key

#### Scenario: Identical, later, and older versions

- **GIVEN** the producer has recorded a published version for an event ID
- **WHEN** it observes the same `updated` value
- **THEN** it does not publish that version again
- **WHEN** it observes a later `updated` value
- **THEN** it publishes the later version
- **WHEN** it observes an earlier `updated` value
- **THEN** it does not publish that version as a new update

#### Scenario: Event ages out of the rolling feed

- **GIVEN** an event is stored and later falls outside the feed's 24-hour window
- **WHEN** it is absent from a subsequent feed response
- **THEN** the producer does not treat that absence alone as a deletion instruction

#### Scenario: Dashboard is closed

- **GIVEN** the producer and consumer are running while the dashboard is closed
- **WHEN** another polling cycle is due
- **THEN** the producer continues its USGS polling and Kafka publication independently of the dashboard

#### Scenario: Producer outage exceeds the feed window

- **GIVEN** the producer has been stopped for more than 24 hours
- **WHEN** live polling resumes
- **THEN** recovery of the missed interval is explained using the historical catalog
- **AND** the producer does not claim exhaustive reconciliation of removals, merges, or revisions that are no longer in the live feed

### Requirement: [F-04] Publish a traceable Kafka envelope

Each producer message MUST contain `source`, `ingested_at`, `mode` (`live` or `replay`), and the original event. The producer MUST wait for Kafka's publish acknowledgement before marking that version as published in persistent state.

Priority: Explicitly required.
Traceability: `docs/ENUNCIADO (1).md` §5; `docs/FAQ.md` Q10, Q14.

#### Scenario: Message acknowledged

- **GIVEN** an eligible event is ready for publication
- **WHEN** Kafka acknowledges the message
- **THEN** the producer records that event version as published
- **AND** the message includes the required envelope fields and original event

#### Scenario: Producer fails between publication and state update

- **GIVEN** Kafka acknowledged a message but the producer stopped before recording its publication state
- **WHEN** the producer restarts and sees the same event version
- **THEN** it MAY publish the version again
- **AND** the consumer remains responsible for tolerating that duplicate

### Requirement: [NF-04] Recover from external feed failures

The producer MUST record timeouts, HTTP 429/5xx responses, and invalid JSON; apply retries with progressive backoff where applicable; and preserve valid prior state.

Priority: Explicitly required.
Traceability: `docs/ENUNCIADO (1).md` §5.

#### Scenario: Transient source or response failure

- **GIVEN** the producer has valid prior publication state
- **WHEN** a USGS request times out, returns HTTP 429/5xx, or contains invalid JSON
- **THEN** the failure is recorded and the applicable retry policy uses progressive backoff
- **AND** the prior valid state remains available

## Clarifications Pending

- The documents require retries with progressive backoff but do not define retry limits, exact delay values, or a terminal-failure policy.
- The documents do not define producer behavior for an event missing `id` or `updated`; do not infer a fallback identity or version rule.
