# Tasks

## 1. Project Setup

- [x] 1.1 Verify `leaflet` is present (already in dependencies) and add `leaflet.markercluster` (or Angular wrapper) to `package.json`, then run `npm install` and ensure build succeeds.
- [x] 1.2 Add `fastapi[websockets]` to backend requirements and verify installation.
- [x] 1.3 Create a new route file `src/websocket.py` with a placeholder WebSocket endpoint and verify the server starts.

## 2. Backend WebSocket Endpoint

- [x] 2.1 Implement `/ws/earthquakes` WebSocket endpoint using FastAPI that accepts connections and broadcasts incoming earthquake events received from the Kafka producer.
- [x] 2.2 Add a simple in‑memory broadcast mechanism and verify that a test client receives a dummy event.
- [x] 2.3 Write unit test `tests/websocket_test.py` that connects to the endpoint and asserts receipt of a test message.

## 3. Frontend Map View

- [x] 3.1 Create a new Angular component `real-time-map.component.ts` (and HTML template) that loads the Leaflet map lazily (using dynamic import) and displays a base tile layer.
- [x] 3.2 Add an Angular service `earthquake.service.ts` that opens a WebSocket connection to `/ws/earthquakes` and provides an Observable stream of earthquake events.
- [x] 3.3 Provide an Angular module `RealTimeMapModule` that declares the component, imports `NgxLeafletModule`, and injects the service to add markers for each incoming event.
- [x] 3.4 Verify that the Angular component loads, connects to the WebSocket, and renders a marker when a mock event is pushed (manual QA).

## 4. Integration & UI Wiring

- [x] 4.1 Add a navigation entry `Real‑Time Map` to the main menu linking to the new view.
- [x] 4.2 Ensure existing build scripts include the new lazy‑loaded chunk and that the app bundles without errors.
- [x] 4.3 Run end‑to‑end test using Cypress that opens the map view, simulates a WebSocket message, and checks that a marker appears on the map.

## 5. Documentation & Cleanup

- [x] 5.1 Update `README.md` with a section describing the real‑time map feature and how to run the backend WebSocket.
- [x] 5.2 Add documentation in `docs/frontend.md` about the `EarthquakeContext` API.
- [x] 5.3 Remove any unused imports and run `npm run lint` to ensure no lint errors.

## 6. Verification & Release

- [x] 6.1 Deploy the backend to the staging environment and verify the WebSocket endpoint is reachable.
- [x] 6.2 Verify the frontend map works in both desktop and mobile browsers (manual QA).
- [x] 6.3 Tag a new release version `v0.2.0‑real‑time‑map`.
