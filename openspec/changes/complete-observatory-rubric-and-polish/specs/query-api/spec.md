## ADDED Requirements

### Requirement: Define the statistics response, filters, pagination and errors

`GET /api/estadisticas` MUST return, for one set of filters (`start`, `end`, `min_mag`, `country_id`, `subregion`, `mode`): total and per-country/subregion counts including "Sin país asignado"; counts per fixed one-hour UTC window by event time; magnitude and depth distributions with explicit `missing` counts; and a historical comparison. All aggregates MUST be computed from the current-state table, never from message counts. Malformed filter values MUST yield HTTP 422; an unknown `country_id` MUST yield an empty valid result. `/api/eventos` MUST support `limit`/`offset` and report `total`.

#### Scenario: Revision does not inflate counts

- **GIVEN** an event received twice with a later revision
- **WHEN** statistics are requested
- **THEN** the event is counted once, in the window of its latest event time

#### Scenario: Hourly windows include empty hours

- **GIVEN** no events occurred in one hour of the period
- **WHEN** statistics are requested
- **THEN** that window appears with count 0

#### Scenario: Historical comparison

- **GIVEN** 2025 historical data loaded with the same filters
- **WHEN** statistics are requested with `min_mag=4`
- **THEN** the response contains the last-24-hour count, the 2025 daily mean (denominator 365, zero days included), their ratio and a note that the latest period may be incomplete

#### Scenario: Invalid filter

- **GIVEN** `min_mag=abc`
- **WHEN** a client requests `/api/eventos`
- **THEN** the API returns HTTP 422

### Requirement: Restrict the public surface and allow the exact browser origins

The API MUST expose only `/api/eventos`, `/api/estadisticas` and `/api/salud` (plus framework documentation if enabled). It MUST answer CORS preflight (`OPTIONS`) for the origins listed in configuration (exact Netlify origin and development origin), allow the header `ngrok-skip-browser-warning`, and MUST NOT use a wildcard origin.

#### Scenario: Allowed origin

- **GIVEN** a request with `Origin` equal to the configured Netlify origin
- **WHEN** a preflight is sent with the ngrok header
- **THEN** the response allows that origin and header

#### Scenario: Unlisted origin

- **GIVEN** a request from an unlisted origin
- **WHEN** a preflight is sent
- **THEN** no allow-origin header is returned

#### Scenario: Broadcast and WebSocket routes are gone

- **GIVEN** the API is running
- **WHEN** `/ws/earthquakes` or `/ws/earthquakes/broadcast` is requested
- **THEN** the API responds 404
