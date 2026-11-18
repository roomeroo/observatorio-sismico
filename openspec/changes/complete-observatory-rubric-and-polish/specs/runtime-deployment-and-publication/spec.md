## ADDED Requirements

### Requirement: Offer an optional ngrok tunnel and configurable origins without a sixth mandatory service

Compose MUST provide ngrok only under an optional profile, targeting the API by service name, reading its token from the environment, and the default startup MUST still run exactly the five required services. `.env.example` MUST list the token variable empty, the allowed CORS origins and the replay topic. The token MUST NOT appear in Git or in the frontend bundle.

#### Scenario: Default startup

- **GIVEN** a clean checkout and a filled `.env`
- **WHEN** `docker compose up --build -d` runs
- **THEN** producer, consumer, Kafka, PostgreSQL and API are running and healthy and no ngrok container exists

#### Scenario: Tunnel profile

- **GIVEN** `NGROK_AUTHTOKEN` is set
- **WHEN** the tunnel profile is enabled
- **THEN** ngrok exposes only the API over HTTPS

#### Scenario: Secrets scan

- **GIVEN** the repository and the built frontend
- **WHEN** they are searched for the token value
- **THEN** it is not found
