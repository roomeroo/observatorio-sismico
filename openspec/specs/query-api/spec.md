# Query API

## Purpose

Specify the observable HTTP contract for querying current processed events, system health, and statistical results.

## Requirements

### Requirement: [F-08] Serve current events using the GeoJSON contract

`GET /api/eventos` MUST conform to the response, filters, and data rules in `docs/CONTRATO-API (1).md`. Empty results succeed; null magnitude does not satisfy `min_mag`.

Priority: API contract requirement.
Traceability: `docs/CONTRATO-API (1).md` “GET /api/eventos”; `docs/ENUNCIADO (1).md` §8; `docs/FAQ.md` Q9, Q25–Q27.

#### Scenario: Default event query returns current events

- **GIVEN** PostgreSQL contains current events in and outside the previous 24 hours
- **WHEN** a client requests `GET /api/eventos` without time filters
- **THEN** the response is a GeoJSON FeatureCollection containing only current events from the previous 24 hours
- **AND** each event appears once with valid Point geometry and the documented coordinate order

#### Scenario: No events match

- **GIVEN** no current event matches the request
- **WHEN** the client requests `GET /api/eventos`
- **THEN** the API returns HTTP 200 with `features: []`

#### Scenario: Time and magnitude filters are applied

- **GIVEN** a request supplies `start`, `end`, or `min_mag`
- **WHEN** the API evaluates the query
- **THEN** `start` is inclusive and `end` is exclusive
- **AND** null magnitudes do not pass `min_mag` and are counted separately

#### Scenario: Country filter is applied

- **GIVEN** a request supplies `country_id`
- **WHEN** the API evaluates the event query
- **THEN** only current events matching that catalog identifier are returned

#### Scenario: Response metadata distinguishes generated data from ingestion

- **GIVEN** the API returns a FeatureCollection
- **WHEN** response metadata is inspected
- **THEN** `generated` describes response generation and `last_ingestion` describes the latest successful USGS query
- **AND** a recent `generated` timestamp does not imply a recent ingestion

#### Scenario: Unknown values are serialized

- **GIVEN** a current event has an unknown magnitude, depth, or country
- **WHEN** it is serialized in the response
- **THEN** the corresponding property is JSON `null`
- **AND** the response contains no NaN or Infinity values

#### Scenario: Result is truncated

- **GIVEN** the API applies a documented maximum and the matching result exceeds it
- **WHEN** the response is returned
- **THEN** metadata indicates `truncated: true`
- **AND** the response provides the full matching total and a pagination mechanism

### Requirement: [F-09] Provide health and statistical endpoints

The API MUST implement `/api/salud` and `/api/estadisticas` as specified in `docs/CONTRATO-API (1).md`. Statistics identify period, filters, unit, and missing-value counts, and use map-equivalent filters. Database failure is explicit, not a valid zero result.

Priority: API contract requirement.
Traceability: `docs/CONTRATO-API (1).md` “Otros endpoints a implementar”; `docs/ENUNCIADO (1).md` §8.

#### Scenario: Health is queried

- **GIVEN** the API is available
- **WHEN** a client requests `GET /api/salud`
- **THEN** the response reports API state and the latest ingestion date
- **AND** it does not expose credentials

#### Scenario: Statistics are queried

- **GIVEN** current and historical data are available
- **WHEN** a client requests `GET /api/estadisticas` with filters
- **THEN** the response includes the requested counts, distributions, and historical comparison
- **AND** identifies period, filters, unit, and records without a value

#### Scenario: Database is unavailable

- **GIVEN** the API cannot query PostgreSQL
- **WHEN** an event or statistics request is processed
- **THEN** the API returns an explicit failure
- **AND** does not present zero events as a successful result

## Clarifications Pending

- The statistics endpoint's exact JSON shape, distribution binning, and comparison fields are not defined.
- The contract requires a complete total and pagination when truncating but does not choose field names or an offset/cursor scheme.
- The behavior and HTTP status for malformed filter values or an unknown `country_id` are not specified.
- The contract exposes `country_id`; the dashboard also mentions region/subregion filters, but the parameter and semantics for those filters are unspecified.
