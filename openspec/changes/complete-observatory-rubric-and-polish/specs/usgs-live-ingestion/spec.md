## ADDED Requirements

### Requirement: Persist extraction metadata, exclusions and the original payload

For every successful or failed feed poll the producer MUST persist a record with timestamp, HTTP status, latency, feature count, published count and error text when applicable. Each excluded feature MUST be stored with its id (if any) and exclusion reason. The original GeoJSON MUST be stored only when its content hash differs from the last stored one, and stored payloads MUST be deleted after a configured retention period.

#### Scenario: Non-earthquake feature is excluded

- **GIVEN** the feed contains a feature with `type: quarry blast`
- **WHEN** the poll is processed
- **THEN** it is not published and an exclusion record with reason `type_not_earthquake` exists

#### Scenario: Identical payload is not stored twice

- **GIVEN** two consecutive polls return byte-identical GeoJSON
- **WHEN** both are processed
- **THEN** two poll records exist and only one stored payload

#### Scenario: Failed poll keeps valid state

- **GIVEN** a poll fails with HTTP 503
- **WHEN** the failure is recorded
- **THEN** the poll log contains the error and the last published-version state is unchanged

#### Scenario: Retention is applied

- **GIVEN** stored payloads older than the retention period
- **WHEN** the retention task runs
- **THEN** those payloads are deleted and poll records remain
