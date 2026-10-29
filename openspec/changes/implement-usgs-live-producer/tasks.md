# Tasks

## 1. Persist producer publication state

- [ ] 1.1 Add a SQLite state store containing only each event `id` and latest Kafka-acknowledged `updated`; verify insert, equal/later/older comparisons, and close/reopen persistence with a temporary database.
- [ ] 1.2 Mount a named `producer_state` volume only on the existing `producer` Compose service and configure its SQLite path; verify `docker compose config` still defines the same five services and no new service or PostgreSQL event table.
- [ ] 1.3 Update `backend/README.md` to document the producer-only state volume and its contents; verify the instructions distinguish publication metadata from seismic-event persistence.

## 2. Acquire and validate the USGS feed

- [ ] 2.1 Add the documented `all_day.geojson` source request and configurable polling interval, defaulting to the documented approximate 60 seconds; verify scheduling with a controllable clock rather than real waiting.
- [ ] 2.2 Validate JSON and the documented GeoJSON feature-collection structure; verify empty collections publish nothing, invalid responses publish nothing and preserve state, and a fixture with missing `id`/`updated` excludes only that feature with a recorded reason.
- [ ] 2.3 Filter `properties.type == "earthquake"` and record exclusion reasons for other types; verify synthetic fixtures cover eligible and excluded features without contacting USGS.
- [ ] 2.4 Add deterministic fake-HTTP tests for success, empty feed, invalid JSON/structure, timeout, HTTP 429, and HTTP 5xx; verify tests make no outbound request to USGS.
- [ ] 2.5 Update `backend/README.md` with the source URL, documented fields/types/units, rolling-window semantics, polling configuration, error handling, and how request latency is measured; verify no unsupported latency result is presented as fact.

## 3. Publish versioned events to Kafka

- [ ] 3.1 Publish to configurable topic `earthquakes-live` by default, using the string event `id` as key and the UTF-8 JSON envelope `{source, ingested_at, mode, event}` with the unchanged GeoJSON Feature; verify exact key, fields, timestamp units, mode, and original event using a fake Kafka producer.
- [ ] 3.2 Compare `id` and `properties.updated` with persisted publication state; verify new and later versions publish, while equal and older versions do not.
- [ ] 3.3 Record publication state only after Kafka acknowledgement; verify a failed or unacknowledged send leaves state unchanged and an acknowledged send records it.
- [ ] 3.4 Update `backend/README.md` with the topic configuration and message envelope; verify it distinguishes this live producer contract from replay and consumer processing.

## 4. Handle retries and recovery

- [ ] 4.1 Apply at most three total attempts to each source request and event send, waiting 20 seconds before attempt two and 40 seconds before attempt three; verify attempt counts and delays with a fake clock and no real sleep.
- [ ] 4.2 Verify exhausted source failures are logged, preserve prior state, and allow processing on a later regular poll; cover recovery after timeout, HTTP 429/5xx, invalid JSON, and invalid GeoJSON with deterministic fake responses.
- [ ] 4.3 Verify an event that exhausts Kafka attempts remains unmarked, later eligible events in the same response are still attempted, and the failed event can publish on a later feed after Kafka recovers.
- [ ] 4.4 Update `backend/README.md` with the approved retry count, delays, exhaustion behavior, and recovery boundary; verify documentation does not imply live-feed recovery beyond its rolling 24-hour window.

## 5. Verify producer integration without live USGS

- [ ] 5.1 Run the backend unittest suite from `backend` and verify all producer tests use synthetic fixtures/fakes and pass without network access.
- [ ] 5.2 Build and start the existing Compose stack, verify the producer remains a distinct service with only its state volume/configuration added, and confirm the SQLite state survives producer container recreation.
- [ ] 5.3 Run a local end-to-end producer smoke test with a local fake feed and controllable Kafka acknowledgement; verify the event key/envelope, ACK-before-state ordering, failure recovery, and absence of USGS calls.
- [ ] 5.4 Review the final diff and Compose configuration; verify no base specification, API contract, consumer behavior, PostgreSQL seismic persistence/schema, replay, or frontend files were changed.
