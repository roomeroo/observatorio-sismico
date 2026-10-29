# Historical Data Acquisition

## Purpose

Define the one-time acquisition and reproducible retention of a complete historical year used by the observatory and its comparisons.

## Requirements

### Requirement: [F-02] Acquire and retain a complete historical year

The system MUST obtain one complete, documented year of USGS catalog data. It MUST subdivide queries exceeding 20,000 results, deduplicate interval endpoints, record queries/date/counts, and allow downloaded files to be reused. The suggested 2025/worldwide/magnitude-4 scope is not fixed.

Priority: A complete year is required; the specific year, geographic scope, and filters are not fixed.
Traceability: `docs/ENUNCIADO (1).md` §4.2, §12; `docs/FAQ.md` Q6, Q21.

#### Scenario: Reproducible annual extraction

- **GIVEN** a documented year, scope, and set of filters
- **WHEN** the historical dataset is acquired
- **THEN** the extraction covers the complete selected year
- **AND** records the queries, extraction date, filters, and returned record counts
- **AND** makes the downloaded files available for reuse

#### Scenario: Source result limit is exceeded

- **GIVEN** an interval query would exceed the source limit of 20,000 records
- **WHEN** the extraction processes that interval
- **THEN** it subdivides the interval and retrieves the records without silently accepting a truncated response

#### Scenario: Adjacent intervals share an endpoint

- **GIVEN** the source may include both endpoints of adjacent time intervals
- **WHEN** records from those intervals are combined
- **THEN** a shared event is deduplicated and is not counted twice

#### Scenario: Historical load is repeated

- **GIVEN** a previously downloaded historical dataset is available
- **WHEN** the historical processing is repeated
- **THEN** it reuses that dataset and follows the same documented validation and integration rules as the selected system path

#### Scenario: Original source response is retained

- **GIVEN** a historical response is acquired before transformation
- **WHEN** it is stored for processing
- **THEN** the original GeoJSON and extraction metadata are retained
- **AND** a documented retention policy avoids indefinitely storing identical copies

#### Scenario: A live-ingestion gap exceeds 24 hours

- **GIVEN** the producer was unavailable long enough for events to leave the rolling feed
- **WHEN** the missed interval is recovered
- **THEN** the documented recovery procedure uses the historical catalog

## Clarifications Pending

- The required year and final geographic/filter scope are not specified. 2025, worldwide, magnitude at least 4, and `earthquake` are only the suggested starting point; a documented bounded area is also permitted.
- The documents allow historical loading through Kafka or a batch path that reuses common processing logic; they do not mandate one loading mechanism.
- The catalog extract is a snapshot at extraction time, not a complete history of every past USGS revision.
