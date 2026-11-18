## MODIFIED Requirements

### Requirement: Real‑time map display
The system SHALL render earthquake events on an interactive map by polling the project API every 60 seconds, updating the display without a full page refresh and without opening a streaming connection.

#### Scenario: New event appears on map
- **WHEN** a poll returns an event not previously displayed
- **THEN** the map adds a marker at the event's coordinates, sized by magnitude and colored by depth, and the legend remains valid.

#### Scenario: Revised event is not duplicated
- **WHEN** a poll returns a later revision of an event already displayed
- **THEN** the existing marker is updated and no second marker is created.
