# Spec Delta

## MODIFIED Requirements

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

#### Scenario: A valid feed response contains no features

- **GIVEN** USGS returns a valid GeoJSON feed with an empty feature collection
- **WHEN** the producer processes that response
- **THEN** it publishes no event for that response
- **AND** it does not delete or reset previously recorded publication state

#### Scenario: The feed response is not valid GeoJSON

- **GIVEN** USGS returns JSON that is not a valid GeoJSON feed feature collection
- **WHEN** the producer validates the response structure
- **THEN** it records the response as invalid
- **AND** it publishes no event from that response
- **AND** it preserves previously recorded publication state

#### Scenario: A feature lacks its documented publication identity or version

- **GIVEN** a valid feature collection contains a feature without `id` or `properties.updated`
- **WHEN** the producer evaluates the features
- **THEN** it excludes only that feature and records the reason
- **AND** it does not synthesize an ID or version
- **AND** it continues evaluating the other features

### Requirement: [F-04] Publish a traceable Kafka envelope

Each producer message MUST contain `source`, `ingested_at`, `mode` (`live` or `replay`), and the original event. The producer MUST wait for Kafka's publish acknowledgement before marking that version as published in persistent state. For this live producer, it MUST use the `earthquakes-live` topic by default and a UTF-8 JSON envelope with the original GeoJSON Feature in `event`; `ingested_at` is Unix milliseconds UTC. Each publication MUST make at most three total attempts, waiting 20 seconds before the second attempt and 40 seconds before the third. After exhaustion, the producer MUST leave the version unmarked and continue with other eligible events.

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

#### Scenario: Kafka is unavailable before acknowledging an event

- **GIVEN** an eligible event has not been recorded as published
- **WHEN** Kafka is unavailable and the producer does not receive a publish acknowledgement
- **THEN** the producer does not mark that event version as published
- **AND** it records the publication failure without discarding valid prior publication state

#### Scenario: Publication resumes after Kafka recovers

- **GIVEN** an eligible event remains available in a subsequent live feed response after an unacknowledged publication attempt
- **WHEN** Kafka is available and acknowledges a later publication attempt
- **THEN** the producer records that version as published only after the acknowledgement
- **AND** any duplicate caused by an acknowledgement/state-update interruption remains tolerable by the consumer

#### Scenario: A message send fails after all attempts

- **GIVEN** multiple eligible events remain in a valid feed response
- **WHEN** a Kafka send fails on all three attempts for one event
- **THEN** the producer records the failure and leaves that version unmarked
- **AND** it continues attempting to publish the other eligible events
- **AND** it can retry the failed event when it appears in a later feed response

### Requirement: [NF-04] Recover from external feed failures

The producer MUST record timeouts, HTTP 429/5xx responses, invalid JSON, and invalid GeoJSON feed structure; apply at most three total attempts with waits of 20 and 40 seconds between attempts; and preserve valid prior publication state. After exhausting source retries, it MUST resume on a subsequent regular poll.

Priority: Explicitly required.
Traceability: `docs/ENUNCIADO (1).md` §5.

#### Scenario: Transient source or response failure

- **GIVEN** the producer has valid prior publication state
- **WHEN** a USGS request times out, returns HTTP 429/5xx, or contains invalid JSON
- **THEN** the failure is recorded and the applicable retry policy uses progressive backoff
- **AND** the prior valid state remains available

#### Scenario: A USGS request times out

- **GIVEN** the producer has valid prior publication state
- **WHEN** a request to the documented feed times out
- **THEN** the timeout is recorded as a source failure
- **AND** the producer retains the prior state and applies the documented progressive-backoff requirement where applicable

#### Scenario: USGS returns HTTP 429 or 5xx

- **GIVEN** the producer has valid prior publication state
- **WHEN** the feed request returns HTTP 429 or a 5xx response
- **THEN** the response is recorded as a source failure
- **AND** the producer retains the prior state and applies the documented progressive-backoff requirement where applicable

#### Scenario: USGS returns invalid JSON

- **GIVEN** the producer has valid prior publication state
- **WHEN** the feed response cannot be parsed as JSON
- **THEN** the response is recorded as invalid
- **AND** no event from that response is published
- **AND** the prior valid state remains available

#### Scenario: Source retry attempts are exhausted and the feed recovers

- **GIVEN** a feed request fails on the initial attempt and both retries
- **WHEN** a subsequent regular poll receives a valid feed response
- **THEN** the producer processes the valid response
- **AND** it retains publication state from before the failed request
