# Backend local runtime

## Requirements

- Docker Engine or Docker Desktop with the Docker Compose v2 plugin.
- A local `.env` file containing the PostgreSQL settings used by Compose.

From the repository root, copy the example and replace its placeholder password:

```powershell
Copy-Item .env.example .env
```

On macOS or Linux, use `cp .env.example .env`. Keep `.env` local; Git ignores it. The example contains placeholders, not credentials.

## Start and inspect

From the repository root:

```text
docker compose up --build -d
docker compose ps
docker compose logs producer consumer api
```

Wait until Kafka and PostgreSQL report `healthy` and the producer, consumer, and API report `healthy`. Their health checks test connectivity to their required dependencies; the API check also verifies its listening socket.

Compose runs five separate services: `producer`, `kafka`, `consumer`, `postgres`, and `api`. The Python services connect to dependencies by their Compose service names. The API listens on `0.0.0.0:8000` inside its container and is published only on host loopback at `127.0.0.1:8000`. Kafka and PostgreSQL have no host port mappings.

The producer stores its publication checkpoint in SQLite at `/var/lib/observatorio/publication-state.sqlite3`, on the named `producer_state` volume. This database contains only each USGS event ID and the latest `updated` timestamp acknowledged by Kafka; it is not the seismic event store. Event persistence belongs to the consumer/PostgreSQL pipeline. `docker compose down` preserves the producer checkpoint along with the Kafka and PostgreSQL volumes.

## USGS live feed

The producer reads the USGS GeoJSON feed at <https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/all_day.geojson>. `USGS_POLL_INTERVAL_SECONDS` configures the interval and defaults to 60 seconds, approximately the source's update cadence. Each response is the full rolling 24-hour window, not a daily archive or a delta of new events.

The documented event fields are:

| Field | Type and meaning |
|---|---|
| `id` | String event identifier, retained across revisions |
| `properties.time` | Integer Unix timestamp in milliseconds for occurrence time |
| `properties.updated` | Integer Unix timestamp in milliseconds for the source revision |
| `properties.mag` | Number or `null`; magnitude, whose scale is described by `magType` |
| `properties.magType` | String or `null`; magnitude scale/type |
| `properties.type` | String event type; only `earthquake` is eligible for publication |
| `properties.place` | String or `null`; source location description |
| `geometry.coordinates` | GeoJSON numeric array `[longitude, latitude, depth_km]` |

The producer preserves the original feature. It records why non-earthquake or incomplete features are excluded; it does not infer a deletion when an event ages out of the window. Request failures, HTTP 429/5xx, invalid JSON, and invalid GeoJSON structure are recorded. The HTTP client uses its documented default timeout. Request latency is measured with a monotonic clock from before the HTTP GET until the response body has been decoded and the feed structure validated; logs report each attempt's elapsed seconds. No fixed latency is claimed by this documentation.

USGS requests and individual Kafka sends each allow at most three attempts, with waits of 20 seconds before attempt two and 40 seconds before attempt three. After source retries are exhausted, that polling cycle is skipped and a later regular poll can fetch again. After a Kafka send exhausts its retries, the event is left unmarked in the checkpoint, logged, and does not prevent later events in that feed from being attempted; a later feed can publish it after Kafka recovers. Recovery is limited by the source: because the feed is a rolling 24-hour window and no archive is read, an event that ages out before a successful later poll cannot be recovered by this producer.

The producer publishes live messages to the Kafka topic configured by `KAFKA_TOPIC` (default `earthquakes-live`). Each Kafka key is the event ID as UTF-8 bytes. The UTF-8 JSON value has this shape:

```json
{
  "source": "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/all_day.geojson",
  "ingested_at": 1793113140000,
  "mode": "live",
  "event": {
    "type": "Feature",
    "id": "USGS-event-id",
    "geometry": {},
    "properties": {}
  }
}
```

`ingested_at` is Unix milliseconds in UTC; `event` is the original GeoJSON feature. The producer saves the feature's `id` and `properties.updated` to its checkpoint only after Kafka acknowledges the message. Replay is a separate, out-of-scope flow. The consumer remains responsible for validating and persisting seismic events.

Producer tests use deterministic fake HTTP responses and fake retry sleeps; they do not depend on live USGS or Kafka services. From the repository root, run `cd backend` followed by `python -m unittest discover -s tests`.

For a host-based ngrok tunnel, forward the local API port:

```text
ngrok http 8000
```

## Consumer operations and failure interpretation

### Starting, inspecting, and stopping the consumer

- **Start**: The consumer starts automatically with Compose (`docker compose up -d`), or individually via `docker compose up -d consumer`.
- **Inspect**:
  ```text
  docker compose logs -f consumer
  ```
- **Stop**:
  ```text
  docker compose stop consumer
  ```
  Stopping the container does not lose data or offset positions; Compose volumes retain both Kafka log positions and PostgreSQL tables.

### Readiness vs. completed processing

The consumer healthcheck verifies socket readiness and connectivity to Kafka and PostgreSQL (`healthy` status). This indicates the scaffold and network connections are functioning, but **does not mean all queued events have been processed**. Completed event processing is tracked by Kafka consumer group lag and persisted rows in `observatorio.event_versions` or `observatorio.quarantine_records`.

### Interpreting failures

- **PostgreSQL unavailability / disconnect**: Logged as `WARNING: PostgreSQL error while processing record... Retrying after reconnection...`. The consumer rolls back the active transaction, keeps the Kafka offset uncommitted, and retries connecting until PostgreSQL is ready. Once restored, the uncommitted message is re-processed.
- **Validation errors**: Logged as `WARNING: Message at <topic>:<partition>:<offset> quarantined. Reason: <REASON>`. The original raw payload and rejection reason are persisted into `observatorio.quarantine_records`, and the Kafka offset is committed to allow subsequent records to proceed.
- **Payload conflict on same version**: Logged when an incoming message matches `(event_id, updated)` but has a differing content hash. The conflicting message is directed to quarantine with reason `PAYLOAD_CONFLICT_SAME_VERSION` without altering existing stored records.

## Persistence model and schema migrations

The PostgreSQL database maintains durable seismic event records within the `observatorio` schema:

1. **Version history (`observatorio.event_versions`)**:
   - Stores every accepted earthquake version identified by `(event_id, updated)`.
   - Preserves the exact original GeoJSON feature (`original_feature` as JSONB) and extraction context (`source`, `ingested_at`, `mode`, `kafka_topic`, `kafka_partition`, `kafka_offset`).
   - Timestamps (`time`, `updated`) in milliseconds are converted and indexed as UTC timestamps (`time_utc`, `updated_utc`).
   - Idempotent: repeated delivery of the same version does not create duplicate rows.

2. **Current projection (`observatorio.current_events`)**:
   - Maintains the single latest known state for each `event_id`.
   - Advances only when a record with a strictly higher `updated` timestamp is processed (`EXCLUDED.updated > current_events.updated`).
   - An older redelivery or delayed message never overwrites newer state.

3. **Quarantine (`observatorio.quarantine_records`)**:
   - Durably stores rejected messages that fail validation before advancing Kafka offsets.
   - Contains raw Kafka message payload bytes (`raw_payload`), rejection reason (`rejection_reason`), decoded envelope JSON if parseable, and broker coordinates (`kafka_topic`, `kafka_partition`, `kafka_offset`).
   - Duplicate deliveries of the same broker offset do not create duplicate quarantine records (`UNIQUE(kafka_topic, kafka_partition, kafka_offset)`).

4. **Ordered migrations (`observatorio.schema_migrations`)**:
   - Additive, ordered SQL migrations reside in `observatorio/migrations/`.
   - Applied automatically on startup by the consumer before processing starts, without requiring volume deletion or recreation.
   - Never reset or delete Docker Compose volumes (`docker compose down` preserves volumes; do NOT use `docker compose down -v`).

### Version retention, current state, and validation limits

- **Version retention**: Every distinct accepted version is permanently retained in `observatorio.event_versions`. When an earthquake is updated by USGS with a newer `updated` timestamp, a new version row is recorded.
- **Current state**: `observatorio.current_events` is a materialized projection holding the latest version for each `event_id`. Re-delivery of an older or duplicate revision does not regress this projection.
- **Payload conflict resolution**: If a message arrives with the same `(event_id, updated)` as an existing row but different payload content, the incoming record is sent to quarantine with `PAYLOAD_CONFLICT_SAME_VERSION`, preserving existing history.
- **Validation limits**:
  - Missing or empty `id` or missing/invalid `updated` is quarantined with `MISSING_OR_INVALID_ID_OR_UPDATED`; no synthetic identities or fallback timestamps are created.
  - Features where `properties.type != 'earthquake'` are quarantined with `NON_EARTHQUAKE_EVENT`.
  - Geometry other than GeoJSON `Point` or coordinates outside valid ranges (longitude not in `[-180, 180]`, latitude not in `[-90, 90]`) are quarantined with `INVALID_GEOMETRY_OR_COORDINATES`.
  - Negative values for magnitude or depth are valid physical measurements and are retained without rejection.
  - Absent or null magnitudes remain `null` and are not replaced with 0.
- **Out of scope**: Geographic enrichment (country/region lookups via Natural Earth), historical data loading, event replay, and HTTP API query endpoints remain out of scope for this consumer change.

## Current scope

The infrastructure baseline now includes live producer ingestion. The following downstream features remain outside this producer change:

- The consumer connects to Kafka and PostgreSQL but does not subscribe to or process seismic records.
- The FastAPI process connects to PostgreSQL but does not implement the endpoints in `docs/CONTRATO-API.md`.
- Consumer-side event validation, persistence, idempotency, and quarantine; historical loading; statistics; replay; and the frontend-to-API integration are not implemented by this baseline.

The local Kafka broker uses a finite retention setting of 168 hours. This is a development default; the project documents require bounded retention but do not prescribe a numeric value.

## Stop without deleting local data

From the repository root:

```text
docker compose down
```

This stops and removes the containers but preserves the named Kafka and PostgreSQL volumes. Do not add `--volumes`/`-v` if you want to keep local data.
