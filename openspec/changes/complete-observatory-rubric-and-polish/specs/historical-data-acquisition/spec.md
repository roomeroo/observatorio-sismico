## ADDED Requirements

### Requirement: Download the historical year by month with explicit overflow handling

The historical acquisition command MUST download 2025 (worldwide, magnitude ≥ 4, `earthquake`) in monthly intervals and MUST subdivide any interval whose result reaches the 20,000-event maximum. It MUST NOT truncate silently. Events present in two adjacent intervals MUST be stored once.

#### Scenario: Month within the limit

- **GIVEN** a monthly query returns fewer than 20,000 events
- **WHEN** it completes
- **THEN** the response is saved as a file and its count is recorded

#### Scenario: Month reaches the limit

- **GIVEN** a query returns 20,000 events
- **WHEN** acquisition evaluates it
- **THEN** the interval is split into smaller intervals and re-queried
- **AND** the original truncated response is not used as final data

#### Scenario: Boundary event appears twice

- **GIVEN** an event at an interval boundary is returned by both adjacent queries
- **WHEN** events are loaded
- **THEN** exactly one historical row exists for that `id`

### Requirement: Record query provenance and allow offline reuse

Each historical query MUST be recorded with URL, parameters, extraction timestamp, HTTP status and returned count. Downloaded files MUST live in a documented, git-ignored location and a rerun MUST reuse existing files without network access unless a refresh is requested.

#### Scenario: Rerun without network

- **GIVEN** all monthly files already exist
- **WHEN** the command runs with no network
- **THEN** it loads the files and exits successfully without HTTP requests

#### Scenario: Provenance is queryable

- **GIVEN** the historical load has finished
- **WHEN** the query log is read
- **THEN** it contains one row per executed query with its count and extraction date
