## ADDED Requirements

### Requirement: Resolve boundary and multi-match points deterministically

The consumer MUST treat a point lying on a polygon boundary as contained (covers semantics). When a point matches more than one catalog entity, the consumer MUST select the entity with the lexicographically smallest `ADM0_A3` and MUST flag the event as geographically ambiguous. The rule MUST be documented in the data dictionary.

#### Scenario: Boundary point is assigned

- **GIVEN** a valid event point lies exactly on the edge of one catalog polygon
- **WHEN** the event is enriched
- **THEN** the event is assigned to that polygon's `ADM0_A3`

#### Scenario: Multiple polygons match

- **GIVEN** a valid point matches two catalog entities
- **WHEN** the event is enriched
- **THEN** the smallest `ADM0_A3` is stored
- **AND** the ambiguity flag is true for that event

### Requirement: Persist country assignment and conformed dimensions

The system MUST store `country_id` for every current event and event version, with `NULL` meaning "Sin país asignado". It MUST maintain a country dimension (identifier, Spanish name, admin name, continent, subregion) loaded from the catalog and a date dimension covering the dates of stored events. Reprocessing the same message MUST yield the same country assignment.

#### Scenario: Offshore event keeps null country

- **GIVEN** a valid event point outside every polygon
- **WHEN** it is persisted
- **THEN** `country_id` is null and the event remains in current state and aggregations under "Sin país asignado"

#### Scenario: Country dimension is loaded once

- **GIVEN** the consumer starts against an empty database
- **WHEN** migrations and catalog loading complete
- **THEN** the country dimension contains one row per unique `ADM0_A3`
- **AND** restarting the consumer does not add rows

#### Scenario: Catalog identifier is not unique

- **GIVEN** the catalog contains duplicate `ADM0_A3` values
- **WHEN** the catalog is loaded
- **THEN** the consumer logs the duplicates and applies a documented deterministic resolution instead of failing silently
