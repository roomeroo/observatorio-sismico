## ADDED Requirements

### Requirement: Keep filters coherent and show backend failure with automatic recovery

One filter state (date range, minimum magnitude, country/subregion) MUST drive the map, charts, counts and table. The dashboard MUST show last successful API access, last successful ingestion, queried period, and a staleness warning. When the API is unreachable the dashboard MUST show a visible failure banner, keep and label the last successful data with its timestamp, and resume automatically on the next 60-second poll after the API returns, without overlapping requests.

#### Scenario: Filter change affects every view

- **GIVEN** the dashboard shows data
- **WHEN** the user sets minimum magnitude 5
- **THEN** map markers, hourly chart, distributions, country counts and table all reflect magnitude ≥ 5

#### Scenario: Tunnel closed

- **GIVEN** the dashboard is open
- **WHEN** the API stops responding
- **THEN** a failure banner appears and the last data stays visible with its timestamp

#### Scenario: Tunnel reopened

- **GIVEN** the failure banner is shown
- **WHEN** the API becomes reachable again
- **THEN** the next poll succeeds, the banner clears and data refreshes with no user action

#### Scenario: Unknown magnitude is labeled

- **GIVEN** an event with null magnitude
- **WHEN** it appears on map and table
- **THEN** it is marked "ND" and styled distinctly, not as zero

#### Scenario: Replay mode is labeled

- **GIVEN** the user selects replay mode
- **WHEN** data loads
- **THEN** a persistent "REPRODUCCIÓN" label is visible and the queried interval is the replay interval
