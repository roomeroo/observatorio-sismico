# Dashboard and Analysis

## Purpose

Specify how the Angular application presents processed earthquake data, enables coherent exploration, and supports defensible statistical conclusions.

## Requirements

### Requirement: [F-10] Explore processed data through the dashboard

The Angular application MUST query the project API and provide the specified interactive map, event details, magnitude/depth encoding, legend, and null handling. It MUST provide geographic and one-hour UTC counts, magnitude/depth distributions with missing counts, coherent filters, a queryable table, and API/ingestion/period/staleness status.

Priority: Required.
Traceability: `docs/ENUNCIADO (1).md` §3, §8; `docs/FAQ.md` Q2–Q3, Q18, Q22, Q25–Q27, Q31, Q35; `docs/README (1).md` §1–§5.

#### Scenario: Dashboard loads processed events

- **GIVEN** the dashboard is configured for API mode and the API is reachable
- **WHEN** the dashboard loads or refreshes
- **THEN** it requests processed events from the project's API
- **AND** does not use a direct USGS request as the submitted data path

#### Scenario: User filters the data

- **GIVEN** a user selects a date interval, minimum magnitude, or country/region
- **WHEN** the map and analytical views refresh
- **THEN** the applicable filter is reflected coherently in the map and statistics
- **AND** missing magnitudes and events without assigned country remain visible or accounted for rather than silently becoming zero or disappearing from unrelated views

#### Scenario: User inspects map and table

- **GIVEN** the dashboard has event results
- **WHEN** the user inspects an event on the map or uses the table
- **THEN** the map shows the documented magnitude and depth encodings, legend, boundaries, and event details
- **AND** the table provides a queryable alternative to interpreting position or color
- **AND** the OpenStreetMap tile attribution remains visible when that background is used

#### Scenario: Dashboard reports stale data or an API failure

- **GIVEN** the backend is unavailable or the last successful ingestion is old
- **WHEN** the dashboard refreshes
- **THEN** it displays a failure or stale-data warning and the latest successful read/response state
- **AND** it does not label previously displayed data as newly obtained

#### Scenario: API result is truncated

- **GIVEN** the API indicates that its event result is truncated
- **WHEN** the dashboard presents the response
- **THEN** it exposes the truncation and total to the user
- **AND** does not present statistics calculated from the truncated sample as global statistics

### Requirement: [F-11] Compare equivalent periods and state evidence-based conclusions

The analysis MUST compare recent and historical counts with equivalent types, scopes, and filters; include zero-event days in historical daily averages; and explain reporting delays. It MUST NOT claim prediction or risk assessment. Evidence MUST include at least three conclusions with figures, filters, and period.

Priority: Required.
Traceability: `docs/ENUNCIADO (1).md` §8; `docs/FAQ.md` Q1, Q23–Q24, Q34.

#### Scenario: Equivalent comparison is shown

- **GIVEN** recent and historical data are available for documented filters
- **WHEN** the dashboard or analysis compares their counts
- **THEN** it applies equivalent type and geographic/magnitude filters to both samples
- **AND** includes zero-count days in a historical daily average
- **AND** identifies the compared periods and filters

#### Scenario: Historical mean is zero

- **GIVEN** the historical comparison denominator produces a mean of zero
- **WHEN** a percentage variation is requested
- **THEN** the variation is shown as not defined (ND) and the reason is explained

#### Scenario: Conclusions are presented

- **GIVEN** the analysis is submitted
- **WHEN** its conclusions are reviewed
- **THEN** at least three conclusions cite numerical evidence, period, filters, and relevant denominator
- **AND** none claims that these descriptive statistics predict an earthquake or establish risk

### Requirement: [NF-07] Refresh without overlapping requests and recover visibly

API polling MUST avoid overlapping requests, use a timeout, retain the prior map layer with a warning on failure, cancel work on component destruction, and recover on a later successful refresh. The supplied frontend specifies a 15-second timeout and 60-second refresh interval.

Priority: Explicitly required for the supplied frontend behavior.
Traceability: `docs/README (1).md` §3; `docs/ENUNCIADO (1).md` §8–§9, §11; `docs/VALIDACION (1).md` “Límites de esta comprobación”.

#### Scenario: Refresh takes longer than its interval

- **GIVEN** an API request is still in progress when the next refresh interval would otherwise occur
- **WHEN** the refresh scheduler runs
- **THEN** it does not start an overlapping request

#### Scenario: API request fails and later recovers

- **GIVEN** the dashboard has successfully loaded a map layer
- **WHEN** a subsequent API request fails
- **THEN** the previous layer is retained and a warning is shown
- **WHEN** a later refresh succeeds
- **THEN** the layer is replaced by the successful response and the failure state is cleared

#### Scenario: Dashboard component is destroyed

- **GIVEN** an API request or refresh timer is active
- **WHEN** the dashboard component is destroyed
- **THEN** the active request and timer are cancelled

## Clarifications Pending

- The exact region/subregion filter contract is not defined; `/api/eventos` currently specifies `country_id`.
- The historical comparison is illustrated with recent 24-hour counts versus a 2025 daily average, but the historical year and geographic scope are selectable/documented rather than fixed.
- `magType` scales may differ; no normalization rule is specified for comparisons between different magnitude types.
- `docs/VALIDACION (1).md` reports that browser visual testing and a real Netlify/ngrok deployment were not completed; those behaviors remain unverified in the base material.
- OpenStreetMap tiles require Internet and visible attribution and have no service guarantee; offline tile use or bulk prefetching is not part of this requirement.
