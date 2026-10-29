# Design

## Context

See `proposal.md` for motivation and scope. The existing Compose service `producer` runs `backend/observatorio/producer.py`, connects to Kafka using `KAFKA_BOOTSTRAP_SERVERS`, and then waits idle. `aiokafka` is already pinned; no USGS HTTP client or producer behavior is present. The existing `usgs-live-ingestion` capability defines the feed, approximate 60-second polling, rolling 24-hour semantics, `earthquake` filter, version comparison, Kafka key/envelope, ACK-before-state-update, and progressive-backoff requirement.

The source requirements do not define a Kafka topic name, exact envelope serialization, retry limits/delays, or a storage mechanism for durable publication state. The user approved concrete choices for this change: a producer-only SQLite volume containing publication metadata, topic `earthquakes-live`, a JSON envelope, three total attempts with 20/40-second waits, per-feature exclusion for missing identity/version, and continued processing after a failed event send. These are project implementation choices, not claims about USGS.

## Goals / Non-Goals

**Goals:**

- Complete the producer path from a documented USGS feed response through event eligibility/version checks to Kafka acknowledgement.
- Preserve the existing five-service topology and readiness behavior; only wire producer-specific configuration if required.
- Make source, filtering, versioning, envelope, ACK ordering, and recovery behavior testable without USGS network access.

**Non-Goals:**

- Consume Kafka messages, persist seismic records in PostgreSQL, implement API endpoints, historical acquisition/reconciliation, replay, or frontend behavior.
- Change base specifications, API contracts, Compose topology, health checks, Kafka retention, or service responsibilities.
- Introduce serialization details, topic names, retry limits/delays, or event-update rules beyond the choices explicitly approved for this change.

## Decisions

### Keep the producer flow behind the existing producer service

Implement source acquisition and Kafka publication under the existing `producer` runtime role. Keep its current dependency readiness and Compose service identity. Add only producer configuration wiring needed to make the already-required broker/topic/frequency settings configurable; do not alter the five-service architecture.

**Alternative considered:** Add a separate polling service or change the Compose topology. Rejected because the existing contract assigns both extraction and publication to the producer and the infrastructure skeleton is already implemented.

### Treat source responses as complete rolling-feed snapshots

Use the documented `all_day.geojson` endpoint and approximately 60-second cadence. Interpret a valid empty feature collection as a successful no-op. For non-empty responses, only events with `properties.type == "earthquake"` are eligible; other event types remain excluded with a reason. Do not infer deletions from events missing in a later window. Do not use any event excluded by a failed/invalid JSON response.

**Alternative considered:** Treat each response as a delta of new occurrences. Rejected because the documents explicitly describe a complete rolling 24-hour window.

### Preserve the event-version and Kafka acknowledgement boundary

For each eligible event, compare its documented `id` and `properties.updated` with publication state. Publish only unseen or later versions, use the event ID as the Kafka key, include the required envelope fields and original event, and record a version only after Kafka acknowledges it. A failure before acknowledgement must not mark the version as published; an interruption after acknowledgement can produce a tolerated duplicate.

**Alternative considered:** Advance publication state before sending or without an ACK. Rejected because it can lose an event and contradicts the existing requirement.

### Store only publication metadata in a producer-owned SQLite volume

Persist `(id, updated)` only after a Kafka acknowledgement in a SQLite database mounted on a named volume used by the existing producer service. Do not store full event payloads in this database or add seismic event persistence to PostgreSQL. The volume is a narrowly scoped persistence prerequisite; it does not add a service or change the existing topology/readiness contract.

**Alternative considered:** Keep state in process memory. Rejected because it is lost on restart and conflicts with the documented persistent-state requirement. Persist event rows in PostgreSQL. Rejected because event persistence is explicitly outside this change.

### Use an explicit live topic and JSON envelope

Use the configurable topic `earthquakes-live` by default. Encode each value as UTF-8 JSON with `source` (documented feed URL), `ingested_at` (Unix milliseconds UTC), `mode` (`live`), and `event` (the unchanged original GeoJSON Feature); use the string event `id` as the Kafka key. This makes the required envelope consumable without changing or normalizing the source event.

**Alternative considered:** Publish the feature without the required envelope. Rejected because the existing contract requires traceability fields. Invent additional fields or normalize the original event. Rejected because neither is required.

### Bound transient retries without discarding candidates

For each source request or event send, make at most three total attempts: the initial attempt and two retries. Wait 20 seconds before the second attempt and 40 seconds before the third. After source retries are exhausted, log the failure, preserve state, and resume on a subsequent regular poll. After an event send exhausts retries, leave its version unmarked and continue with other eligible events; the live feed can make it eligible again on a later poll.

This finite schedule is a project choice approved for this change; the source documents specify progressive backoff but no numerical schedule. The HTTP client timeout is not assigned a project-specific number: use and document the selected client's documented default, and treat its timeout exception as a failed attempt.

**Alternative considered:** Retry indefinitely or mark failed events as published. Rejected because indefinite retries can stall the producer and marking without ACK can lose events.

### Exclude malformed features individually

Reject a whole response when JSON parsing or the documented GeoJSON feed structure fails. For an otherwise valid feature collection, skip and log a feature that lacks `id` or `properties.updated`, then continue with the remaining features. Never synthesize an identity or version. If one Kafka send ultimately fails, continue to later eligible features in that response.

**Alternative considered:** Reject the entire feature collection because one event is incomplete. Rejected because it prevents valid independent events from being published. Generate a fallback `id` or `updated`. Rejected because it invents source identity/version semantics.

### Test with deterministic local substitutes

Use clearly synthetic GeoJSON fixtures containing only documented fields and units. Exercise the same producer behavior through an injected/local fake HTTP transport and a fake Kafka producer that can acknowledge, fail, and recover. Cover empty feed, invalid JSON, timeout, HTTP 429/5xx, event filtering/version ordering, message key/envelope contents, and state updates around ACKs. Tests MUST not contact the public USGS service; optional manual smoke testing may be documented separately and is not the acceptance test.

**Alternative considered:** Use a live `all_day.geojson` request as the primary integration test. Rejected because event contents, network conditions, and availability are unstable and cannot produce deterministic assertions.

## Risks / Trade-offs

- [Risk] A producer volume is new to the infrastructure skeleton → add only a named volume mount to the existing producer service and verify it survives container recreation.
- [Risk] An unavailable Kafka broker can leave acknowledgement outcome uncertain → do not mark a version without ACK; permit duplicates after uncertain outcomes as required by the consumer contract.
- [Risk] A live feed outage longer than its 24-hour window cannot be exhaustively reconciled from that feed → retain the existing documented historical-catalog recovery boundary; historical loading is not implemented here.
- [Risk] Retry attempts can delay a poll or a batch → use the approved finite schedule and keep the event-send failure isolated so later eligible events can proceed.
- [Risk] An HTTP fixture might drift from USGS → limit fixtures to the documented GeoJSON shape/fields and keep them explicitly synthetic; no unstable live-call test is required.

## Migration Plan

No PostgreSQL schema or service-topology migration is planned. Add the producer-owned SQLite volume to the existing Compose service, implement the producer behind its existing command, run deterministic backend tests, and smoke-test with local substitutes. Rollback is limited to the producer behavior/configuration and its new volume; do not remove or recreate the already implemented infrastructure.
