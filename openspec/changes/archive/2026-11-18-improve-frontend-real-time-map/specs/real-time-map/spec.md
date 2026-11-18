# Spec Delta

## Purpose

Provides a live, interactive map view that visualises earthquake events in real time.

## ADDED Requirements

### Requirement: Real‑time map display
The system SHALL render earthquake events on an interactive map as they are received, updating the display without a full page refresh.

#### Scenario: New event appears on map
- **WHEN** a new earthquake event is streamed from the backend API
- **THEN** the map instantly adds a marker at the event’s geographic coordinates and updates any relevant legend or heat‑map layer.

### Requirement: Map interaction
The system SHALL allow users to pan, zoom, and toggle map layers (e.g., magnitude filter, heat map) while maintaining real‑time updates.

#### Scenario: User pans map during live updates
- **WHEN** the user drags the map to a new region while events continue streaming
- **THEN** existing markers remain correctly positioned relative to the new viewport and new incoming events appear in the visible area.
