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

For a host-based ngrok tunnel, forward the local API port:

```text
ngrok http 8000
```

## Current scope

This is an executable infrastructure baseline, not a functional seismic pipeline:

- The producer connects to Kafka but does not ingest USGS data or publish events.
- The consumer connects to Kafka and PostgreSQL but does not subscribe to or process seismic records.
- The FastAPI process connects to PostgreSQL but does not implement the endpoints in `docs/CONTRATO-API.md`.
- Event validation, revisions, idempotency, quarantine, historical loading, statistics, replay, and the frontend-to-API integration are not implemented by this baseline.

The local Kafka broker uses a finite retention setting of 168 hours. This is a development default; the project documents require bounded retention but do not prescribe a numeric value.

## Stop without deleting local data

From the repository root:

```text
docker compose down
```

This stops and removes the containers but preserves the named Kafka and PostgreSQL volumes. Do not add `--volumes`/`-v` if you want to keep local data.
