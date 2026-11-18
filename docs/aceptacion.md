# Evidencias de aceptación

## Reproducción acelerada con Kafka real (tarea 6.4)

Entorno: `docker compose up --build -d` (cinco servicios), histórico 2025 ya cargado (ver `procedencia.md`).

Comando:

```
docker compose run --rm producer python -m observatorio.replay \
  --from 2025-03-28T06:00:00Z --to 2025-03-28T12:00:00Z --speed 600
```

Salida: `Replaying 23 events (25 messages) ... at x600; expected duration 34 s.` y `Replay finished: 25 messages published to earthquakes-replay (23 unique events expected).`

| Comprobación | Resultado |
|---|---|
| Mensajes publicados (23 eventos + 1 duplicado + 1 revisión antigua) | 25 |
| `replay.current_events` | **23** = eventos únicos |
| `replay.event_versions` | 24 (el duplicado idéntico no se reinserta; la revisión antigua queda en el histórico pero no sustituye al actual) |
| `replay.quarantine_records` | 0 |
| Estado vivo antes / después | `190 | 2026-11-18 20:04:09.349772+00` en ambos casos (recuento y `last_ingestion` intactos) |
| `GET /api/eventos?mode=replay&start=…&end=…` | `total: 23`, `mode: "replay"`, `replay_loaded_at: 2026-11-18T20:06:02Z`, sin `last_ingestion` |
| Misma consulta sin `mode` | `total: 0` |
| `GET /api/estadisticas?mode=replay…` | `total: 23`, 6 ventanas horarias, comparación con media 2025 = 18.302 / 365 = 50,14 eventos/día |

## Matriz de las 11 pruebas de aceptación (enunciado §11)

Evidencia automática: `cd backend && python -m unittest discover -s tests -t tests` (114 tests, PostgreSQL real) y `cd frontend && npm test && npx cypress run` (6 + 6). Evidencia en vivo: pila Compose real (ver arriba y `procedencia.md`).

| # | Prueba | Pasos | Resultado esperado | Resultado observado | Evidencia |
|---|---|---|---|---|---|
| 1 | Evento nuevo | Publicar un evento y consultar | Una fila actual visible en API, mapa y análisis | 190 eventos reales del feed en `current_events` tras el arranque; visibles en `/api/eventos` y `/api/estadisticas`; mapa, tabla y gráficos lo muestran | `test_api.py::test_events_geojson_filters_pagination_and_nulls`, `test_geo_persistence.py`, Cypress «shows map markers, charts, counts and a table» |
| 2 | Reenviar la misma versión | Procesar dos veces el mismo mensaje | No aumenta el número de terremotos | Recuento igual; reenvío idéntico no se reinserta (replay: 25 mensajes → 24 versiones, 23 eventos) | `test_persistence.py::test_duplicate_delivery_with_matching_payload_is_idempotent`, `test_replay.py` |
| 3 | Versión posterior | Evento con `updated` mayor | Cambian datos actuales y agregaciones | Estado actual con la nueva magnitud; el evento se cuenta una vez, en la ventana de su último `time` | `test_acceptance_gaps.py::test_newer_version_replaces_current`, `test_api.py::test_revision_does_not_inflate_counts`, Cypress «does not duplicate a marker when an event is revised» |
| 4 | Versión antigua después | Procesar v2 y luego v1 | No sustituye a la más reciente | `current_events` conserva `updated` y `mag` de v2; v1 queda solo en `event_versions` | `test_acceptance_gaps.py::test_older_version_does_not_replace_current`, `test_replay.py` (revisión antigua controlada) |
| 5 | Magnitud nula | Evento con `mag: null` | Se conserva y se muestra ND | `mag IS NULL` (no 0); no cumple `min_mag` y se contabiliza aparte (`null_magnitude_excluded`); la tabla y el mapa lo marcan «ND» | `test_acceptance_gaps.py::test_null_magnitude_is_stored_as_null_not_zero`, `test_api.py` (filtros), Cypress (fila q5 «ND») |
| 6 | Coordenadas inválidas | Mensaje con latitud 145° | Cuarentena con motivo; ningún punto inventado | Motivo `INVALID_GEOMETRY_OR_COORDINATES` en `quarantine_records`; nada en `current_events` | `test_validation.py::test_invalid_geometry_or_coordinates_rejected`, `test_quarantine.py`, `test_consumer_e2e.py` |
| 7 | Evento marítimo | Punto fuera de todo polígono | Sin país asignado; permanece en el análisis | `country_id` nulo, sigue en `current_events` y cuenta como «Sin país asignado» en estadísticas | `test_geo_persistence.py::test_offshore_event_has_null_country_and_stays_current`, `test_api.py::test_distributions_and_country_breakdown_with_missing` |
| 8 | Reiniciar consumidor | Reprocesar los mismos offsets con conexión nueva | Reanuda sin duplicar efectos | Versiones, estado actual y cuarentena idénticos antes y después | `test_acceptance_gaps.py::test_consumer_restart_rereading_same_records_changes_nothing`, `test_consumer_e2e.py::test_end_to_end_sequence_and_recovery`, `test_geo_persistence.py` (carga de países idempotente) |
| 9 | Cerrar el túnel | Dejar de responder a la API | Banner de fallo y última lectura conservada con su hora | Banner `failure-banner` con la hora de la última lectura válida; marcadores y tabla intactos | Cypress «shows a failure banner keeping the last data» (API simulada que cierra y abre) |
| 10 | Reabrir el túnel | La API vuelve | Recuperación automática | Banner desaparece en el siguiente sondeo sin acción del usuario; sondeo serializado sin solapes | Cypress (mismo test), `poller.spec.ts::recovers automatically after failures` |
| 11 | Reproducción histórica | `observatorio.replay` con Kafka real | Procesa por Kafka sin mezclarse con live | 23 eventos únicos en esquema `replay`; recuento y `last_ingestion` vivos idénticos antes/después; API solo con `mode=replay`; etiqueta REPRODUCCIÓN | Sección «Reproducción acelerada» de este documento, `test_replay.py`, Cypress «labels replay mode» |

Limitaciones: el cierre/apertura del túnel se prueba con una API simulada en Cypress (no hay `NGROK_AUTHTOKEN` en este entorno); la prueba con ngrok real queda para la defensa (README §4, paso 3).

## Túnel ngrok real (pruebas 9 y 10, tarea 10.1)

Pila levantada con `docker compose --profile tunnel up --build -d`; URL pública HTTPS leída de `127.0.0.1:4040` (`https://old-unripe-body.ngrok-free.dev`) y fijada en `frontend/public/config.json`.

| Comprobación | Resultado |
|---|---|
| `GET {URL}/api/salud` y `/api/eventos` por HTTPS | 200; 178 eventos en vivo, `mode: live`, `truncated: false` |
| Preflight `OPTIONS` con `Origin: http://localhost:4200` y cabecera `ngrok-skip-browser-warning` | 200, origen y cabecera permitidos, métodos `GET, OPTIONS` |
| Preflight desde `https://evil.example` | 400, sin `Access-Control-Allow-Origin` |
| Panel (Cypress, `cypress/e2e/tunnel.cy.ts`, sin simulación): `docker compose stop ngrok` | banner de fallo visible con la hora de la última lectura; marcadores y tabla intactos |
| `docker compose start ngrok` | el banner desaparece solo en el siguiente sondeo; misma URL; «Último acceso correcto» avanza |

Reproducir: `CYPRESS_TUNNEL_URL=<url> CYPRESS_COMPOSE_PROJECT=<proyecto> npx cypress run --spec cypress/e2e/tunnel.cy.ts` (con `npm start` en marcha).
Pendiente por ser de tu cuenta: publicar el panel en Netlify y añadir su origen a `CORS_ALLOWED_ORIGINS`.
