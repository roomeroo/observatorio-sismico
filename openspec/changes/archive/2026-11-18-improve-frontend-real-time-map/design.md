# Design

## Context

The existing frontend shows seismic data as static lists and charts. No visual map view exists, and the backend only provides a REST endpoint for historic data. Real‑time earthquake events are already streamed to the `producer` and stored in PostgreSQL, but there is no push mechanism for the frontend.

## Goals / Non‑Goals

**Goals:**
- Provide an interactive, responsive map that displays earthquake events as they arrive.
- Keep the UI performant on desktop and mobile browsers.
- Use a standard web‑mapping library (Leaflet) to avoid heavy dependencies.
- Enable real‑time updates via a push channel (WebSocket).

**Non‑Goals:**
- Redesign of the entire UI layout – the map will be added as a new view, not a full overhaul.
- Offline map tiles caching – not required for the initial MVP.

## Decisions

1. **Mapping library:** Leaflet (lightweight, well‑documented) over Mapbox GL (larger bundle size). Leaflet can use open‑source tile providers.
2. **Real‑time transport:** WebSocket endpoint (`/ws/earthquakes`) instead of Server‑Sent Events because the backend already uses `aiokafka` and async code, making a bidirectional channel straightforward.
3. **State management:** React Context with a simple reducer to store incoming events; avoids adding Redux for this limited use case.
4. **Marker clustering:** Use `leaflet.markercluster` only if event density becomes high; start without clustering for simplicity.
5. **Backend changes:** Add a lightweight WebSocket server using `fastapi`'s built‑in support; no new external services.

## Risks / Trade‑offs

- **Risk:** Increased bundle size may affect load time on slower connections.
  **Mitigation:** Code‑split the map view and lazy‑load the Leaflet library.
- **Risk:** WebSocket scaling under heavy load.
  **Mitigation:** Initial deployment will run a single instance; monitor and consider a message‑broker‑backed broadcast if needed.
- **Risk:** Map tile provider rate limits.
  **Mitigation:** Use a free, open tile source with attribution and cache tiles client‑side where possible.
