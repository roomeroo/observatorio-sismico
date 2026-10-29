# Runtime Deployment and Publication

## Purpose

Define the mandatory runtime stack, container topology, network boundaries, external access, persistence, and deployment behavior.

## Requirements

### Requirement: [NF-01] Run the five backend services in Docker Compose

Producer, Kafka, consumer, PostgreSQL, and FastAPI MUST run as five distinct local Compose services, startable with `docker compose up --build -d`. Python services MAY share an image but not a service. Angular is an SPA; ngrok may run on the host or in a container.

Priority: Mandatory architecture.
Traceability: `docs/ENUNCIADO (1).md` §2, §9, §12; `docs/README (1).md` §3–§4; `docs/FAQ.md` Q4.

#### Scenario: Backend stack starts together

- **GIVEN** the required Dockerfiles and Compose configuration are present
- **WHEN** a user runs `docker compose up --build -d`
- **THEN** producer, Kafka, consumer, PostgreSQL, and API start as five distinct services

#### Scenario: Python services share a built image

- **GIVEN** producer, consumer, and API use a shared Python image
- **WHEN** Compose starts them
- **THEN** each remains a distinct service with its own start command and runtime role

#### Scenario: Initial Compose baseline is inspected

- **GIVEN** the initial Compose baseline has been built and started
- **WHEN** the user inspects Compose's configured services and running containers
- **THEN** exactly the five required backend roles are configured as distinct services
- **AND** all five service containers remain running without requiring the frontend or ngrok

### Requirement: [NF-02] Preserve the required technology and hosting architecture

The architecture MUST use Python/aiokafka, Apache Kafka, PostgreSQL, Python/FastAPI, and Angular/Leaflet. Publish the SPA through Netlify and expose the API through ngrok HTTPS. Spark, Flink, Kubernetes, machine learning, and a permanent cloud server are not required.

Priority: Mandatory technology restrictions.
Traceability: `docs/ENUNCIADO (1).md` §2–§3; `docs/README (1).md` §1, §3–§5; `docs/FAQ.md` Q4–Q5, Q25–Q30.

#### Scenario: Required stack is deployed

- **GIVEN** the project is deployed for demonstration
- **WHEN** its service topology and frontend are inspected
- **THEN** the required technologies and hosting roles are present
- **AND** no excluded infrastructure is required to run the project

### Requirement: [NF-03] Make startup resilient and state persistent

The delivery MUST include pinned dependencies, database initialization, and credential-free `.env.example`. Health checks/retries MUST handle dependency readiness. Volumes MUST preserve PostgreSQL and historical data; Kafka retention MUST be limited.

Priority: Explicitly required.
Traceability: `docs/ENUNCIADO (1).md` §2, §9, §12; `docs/README (1).md` §3; `docs/FAQ.md` Q4, Q21, Q35.

#### Scenario: Dependency is not ready at process start

- **GIVEN** a dependent service starts before Kafka or PostgreSQL is healthy
- **WHEN** the dependency is not yet ready
- **THEN** the application uses health checks/retries rather than treating container start order as readiness

#### Scenario: Services restart

- **GIVEN** PostgreSQL and Kafka have accepted data
- **WHEN** their containers are restarted
- **THEN** PostgreSQL's persisted data remains available and Kafka retention remains bounded by its configured policy

#### Scenario: Fresh checkout has the required runtime configuration

- **GIVEN** the project is checked out without a developer-specific `.env`
- **WHEN** the user follows the documented Compose startup procedure
- **THEN** a credential-free example environment file and database initialization are available
- **AND** dependencies and service images are pinned sufficiently for the documented reproducible build

#### Scenario: Dependent services start while dependencies are unavailable

- **GIVEN** Kafka or PostgreSQL is not yet healthy
- **WHEN** a dependent service starts or attempts to connect
- **THEN** it waits or retries until the dependency is available rather than silently exiting as a successful service

### Requirement: [NF-05] Restrict and correctly route container network access

Containers MUST communicate through service names and correctly configured Kafka listeners. Uvicorn listens on `0.0.0.0:8000`. Only the API is tunnel-accessible; ngrok targets the API service in Compose or its published host port when running on the host.

Priority: Explicitly required.
Traceability: `docs/ENUNCIADO (1).md` §2, §9; `docs/README (1).md` §3; `docs/FAQ.md` Q28–Q29.

#### Scenario: ngrok runs in Compose

- **GIVEN** ngrok runs in the same Docker network as the API
- **WHEN** it forwards requests
- **THEN** it targets the API by service name and port rather than its own `localhost`
- **AND** publishing the API port on the host is not required for that route
- **AND** the API may use HTTP locally because ngrok provides the public HTTPS endpoint and manages its certificate

#### Scenario: ngrok runs on the host

- **GIVEN** ngrok runs on the host and the API port is published
- **WHEN** it forwards requests
- **THEN** it targets the host-published API port
- **AND** Kafka and PostgreSQL remain unavailable through the public tunnel

#### Scenario: Backend services use Compose service discovery

- **GIVEN** the five backend services are running in the Compose network
- **WHEN** producer, consumer, and API connect to their required broker or database dependencies
- **THEN** they use the corresponding Compose service names rather than `localhost`
- **AND** Kafka advertises an address reachable by its in-network clients
- **AND** the API listens on `0.0.0.0:8000` inside its container

#### Scenario: API port is published for a host-based tunnel

- **GIVEN** ngrok is run on the host as described in the README
- **WHEN** Compose publishes the API port for that route
- **THEN** the host binding is restricted to loopback, preferably `127.0.0.1:8000:8000`
- **AND** PostgreSQL and Kafka are not published as public tunnel targets

### Requirement: [NF-06] Configure browser access without exposing credentials

The API MUST allow the exact Netlify origin and `http://localhost:4200` through CORS, including OPTIONS and `ngrok-skip-browser-warning`. Frontend configuration and Git MUST contain no credentials. CORS is not authentication.

Priority: Explicitly required.
Traceability: `docs/CONTRATO-API (1).md` “Acceso desde Netlify”; `docs/ENUNCIADO (1).md` §9; `docs/README (1).md` §3–§4; `docs/FAQ.md` Q29–Q30, Q35.

#### Scenario: Frontend uses the public tunnel

- **GIVEN** an Angular page is served by Netlify
- **WHEN** it calls the API through ngrok
- **THEN** the public URL uses HTTPS and the browser's allowed-origin preflight succeeds
- **AND** credentials are absent from the public frontend bundle and repository

### Requirement: [NF-09] Publish the SPA and document demonstration startup

The Angular SPA MUST be publishable on Netlify. Instructions MUST explain how to start the backend/tunnel and verify access from another device, and clarify that stopping the host/tunnel removes backend availability. 24/7 availability is not required.

Priority: Publication and activation procedure required; permanent availability explicitly not required.
Traceability: `docs/ENUNCIADO (1).md` §9, §12; `docs/README (1).md` §4; `docs/FAQ.md` Q31, Q35.

#### Scenario: Remote demonstration

- **GIVEN** the backend services and ngrok tunnel are running
- **WHEN** the published Netlify page is opened from another device
- **THEN** the page can query the public API and display processed data

#### Scenario: Host or tunnel is stopped

- **GIVEN** the frontend remains published but the backend host or tunnel is stopped
- **WHEN** a visitor opens or refreshes the dashboard
- **THEN** the UI reports that data is unavailable or stale rather than implying that its local display is live

## Clarifications Pending

- The exact Netlify URL and ngrok URL are deployment values supplied at deployment time, not fixed by the repository.
- Free-tier service quotas and availability are external; the project does not promise 24/7 availability.
