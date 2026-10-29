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
