# Proposal

## Why

The current frontend displays seismic data only as static lists or charts. Users cannot visualise earthquake events on a geographic map in real time, which limits the ability to quickly assess spatial impact and trends.

## What Changes

- Add a new interactive map view that displays earthquake events as they are received.
- Provide real‑time updates without requiring a page refresh.
- Integrate the map with the existing backend API that streams earthquake data.
- Ensure the UI remains responsive on desktop and mobile browsers.

## Capabilities

### New Capabilities
- `real-time-map`: A capability that delivers a live, interactive map of earthquake events. It defines the requirement to render events on a map and keep the display synchronised with incoming data.

### Modified Capabilities
- *(none)*

## Impact

- Frontend codebase: new React (or Vue) components, map library (e.g., Leaflet or Mapbox GL).
- Backend API: may need a WebSocket or Server‑Sent Events endpoint to push new events.
- Deployment: additional static assets, possible increase in bundle size.
- Testing: UI tests for map interaction and real‑time update handling.
