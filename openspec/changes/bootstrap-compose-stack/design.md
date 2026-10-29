# Design

## Context

See `proposal.md` for motivation and scope. The applicable behavior contract is the delta to `runtime-deployment-and-publication` in `specs/runtime-deployment-and-publication/spec.md`; the base capability remains authoritative for requirements not changed here.

The repository currently has the Angular starter and OpenSpec artifacts but no backend source, Dockerfiles, or Compose file. The enunciado requires exactly five distinct backend roles and a reproducible Compose startup. The first baseline therefore needs minimal runnable service entrypoints, not the later seismic-data behavior.

## Goals / Non-Goals

**Goals:**

- Make a fresh checkout capable of building and starting the five backend service roles through one documented Compose procedure.
- Prove service discovery and dependency readiness without requiring the frontend, Netlify, ngrok, or USGS availability.
- Keep local database data across container recreation and bound Kafka message retention.

**Non-Goals:**

- Implement USGS polling, event publication/consumption, revisions, idempotency, domain schemas, quarantine, spatial enrichment, or historical loading.
- Implement the API endpoints or response bodies in `CONTRATO-API.md`; this change only establishes the API process and its database dependency.
- Add the frontend, ngrok, Kafka/PostgreSQL host exposure, or a permanent cloud runtime to Compose.

## Decisions

### Keep the five required roles as five Compose services

Define `producer`, `kafka`, `consumer`, `postgres`, and `api` as separate Compose services. Producer, consumer, and API may share one reproducible Python image and use separate entrypoints/commands, as the enunciado permits. This avoids duplicating Python build configuration without merging their lifecycles.

Alternative considered: one container running all Python processes. Rejected because the architecture requires separate services and independent lifecycles.

### Use a single-node Kafka broker in KRaft mode

Use an Apache Kafka image and a single-node KRaft configuration so the initial local stack needs no additional coordination service and retains the five-role topology. Pin the selected image tag and document the Kafka listener addresses used inside Compose. Configure bounded retention without claiming a particular duration or size is specified by the source documents.

Alternative considered: Kafka with a separate ZooKeeper service. Rejected for this baseline because it adds a sixth service not required by the approved topology.

### Make dependency readiness observable and retryable

Give Kafka and PostgreSQL health checks that test actual broker/database readiness. Gate dependent service startup on those checks where supported, and retain connection retries in application entrypoints so a later dependency restart does not require relying on initial start order. The producer waits for Kafka; the consumer waits for Kafka and PostgreSQL; the API waits for PostgreSQL.

The producer and consumer entrypoints establish their dependency connections and remain idle after becoming ready. They do not poll USGS or process seismic records in this change. The API starts Uvicorn and establishes its database dependency; its container-level readiness check verifies the listening process, not an undocumented HTTP response contract.

Alternative considered: health checks based only on container process existence. Rejected because a running process does not prove that Kafka or PostgreSQL accepts connections.

### Keep data local and bound external access

Use a named PostgreSQL volume and a named Kafka data volume; set a documented finite Kafka retention policy. Do not mount downloaded historical datasets or event data into Git. Do not publish broker or database ports. If the API port is published for host-based ngrok, bind it to loopback (`127.0.0.1:8000:8000`); container-based ngrok can later reach `api:8000` without a host port mapping.

Alternative considered: expose all service ports on the host for debugging. Rejected because the project guidance exposes only the API and explicitly keeps Kafka and PostgreSQL away from the public tunnel.

### Keep configuration reproducible without committing credentials

Pin Python dependencies and service image tags. Include a credential-free `.env.example` and instructions to create a local `.env` for values needed at runtime; ensure local secrets are not committed. Keep service names and internal host/port settings aligned with Compose DNS.

Alternative considered: hard-code a shared development password in Compose. Rejected because repository guidance prohibits committing credentials.

## Risks / Trade-offs

- [Risk] Kafka listener configuration can accept the initial bootstrap connection but advertise an unreachable address → configure and verify the in-network advertised listener from both Python services.
- [Risk] Health checks can delay startup or report false readiness → check actual broker/database operations and confirm behavior with Compose status and dependency restart tests.
- [Risk] A minimal producer/consumer/API skeleton can be mistaken for a working earthquake pipeline → label the README baseline as infrastructure-only and list the deferred functional behaviors.
- [Risk] Container image tags or local Docker availability may vary → pin image tags and record the Docker/Compose prerequisites; run the documented build and startup validation on a Docker-enabled environment.
- [Risk] The exact Kafka retention bound is not specified → choose and document a bounded local default during implementation; do not treat that chosen value as a source requirement.

## Migration Plan

No existing backend services or data schema need migration. Add the initial Compose and backend skeleton, build and start it, verify service readiness and persistence, then stop it without deleting named volumes. Later changes can add the actual data pipeline and API behavior without changing the five-service topology.

Rollback consists of removing the newly introduced backend/Compose files and stopping the stack. Preserve volumes unless the operator explicitly chooses to remove local development data.

## Open Questions

- The documents specify bounded Kafka retention but not a numeric bound. Select a finite local-development value during implementation and document it.
- The exact image versions and a Docker-enabled acceptance environment must be selected/confirmed when implementing; the approved requirements do not prescribe version numbers.

