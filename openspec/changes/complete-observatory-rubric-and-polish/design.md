# Design

## Context

Estado observado: el productor (sondeo, estado SQLite, ack Kafka) y el consumidor (validación, cuarentena, `event_versions` + `current_events` con upsert `WHERE EXCLUDED.updated > current`) funcionan y tienen tests. `api.py` solo expone WebSocket y un `POST` de broadcast; hay tres copias del módulo websocket (`backend/src`, `backend/observatorio/src`, reexport). El frontend usa WebSocket. No hay país, histórico, replay, estadísticas ni memoria. Las specs existentes referencian `docs/CONTRATO-API (1).md`, `FAQ.md` y `ENUNCIADO (1).md`, que **no están en el repo**. Motivación: ver proposal.md.

## Goals / Non-Goals

**Goals:** cubrir cada evidencia de la rúbrica con código y documentos reproducibles; mantener los cinco servicios; agregar siempre desde el estado actual.

**Non-Goals:** más infraestructura, autenticación, reconciliación de eventos eliminados fuera del feed, motor cartográfico propio.

## Decisions

1. **Shapely sin GeoPandas.** Se lee `paises.geojson` con `json`, se construye un `STRtree` en memoria al arrancar el consumidor y se consulta con `covers`. Imagen más pequeña y coste medio O(log n) por punto frente a O(n) de recorrer polígonos. Alternativa: PostGIS (descartada: cambia la imagen de PostgreSQL y añade complejidad sin puntuar más).
2. **Frontera/múltiples coincidencias:** `covers` (el borde cuenta), menor `ADM0_A3` y bandera `geo_ambiguous`. Determinista, idempotente ante reenvíos. `country_id` nulo = "Sin país asignado".
3. **Migración `0003`:** columnas `country_id`, `geo_ambiguous` en `event_versions` y `current_events`; tablas `dim_country`, `dim_date`, `poll_log`, `poll_exclusions`, `raw_payloads`, `historical_events`, `extraction_queries`; índices en `current_events(time_utc)`, `(country_id, time_utc)` y `(mag)`. `dim_date` se rellena por upsert al persistir. Los scripts de `postgres/init` y las migraciones deben seguir sincronizados (se unifica en migraciones como fuente única).
4. **Registro del productor:** `poll_log`, exclusiones y payload original se escriben en PostgreSQL con un cliente síncrono simple y tolerante a fallo (si PostgreSQL cae, el productor sigue publicando y registra el fallo en logs). Deduplicación de payload por SHA-256; retención por tarea diaria.
5. **Histórico** como comando `python -m observatorio.historical` (misma imagen, `docker compose run --rm`). Ficheros en `backend/data/historical/` (git-ignored) con manifiesto; si un mes devuelve 20.000, se bisecciona recursivamente. Deduplicación por `id` en `historical_events`. La media diaria 2025 usa 365 días.
6. **Replay:** esquema `replay` con las mismas tablas; el consumidor selecciona esquema por topic (`earthquakes-live` → `observatorio`, `earthquakes-replay` → `replay`) reutilizando `process_single_record`. Comando `python -m observatorio.replay --from --to --speed` publica ordenado con retardo/factor y añade duplicado y revisión antigua controlados. La API recibe `mode=replay`; `last_ingestion` en replay se devuelve como `replay_loaded_at`.
7. **API:** módulos `queries.py` (SQL parametrizado) y `api.py`; ventanas con `generate_series` + `date_trunc('hour', time_utc AT TIME ZONE 'UTC')` para incluir horas vacías; paginación `limit/offset` con `total`. Pool de conexiones con reintento en lugar de una conexión única (hoy un corte deja la API colgada). Se eliminan WebSocket, broadcast y duplicados. CORS desde `CORS_ALLOWED_ORIGINS`.
8. **ngrok:** servicio bajo `profiles: [tunnel]` con `http http://api:8000`; así el puerto de la API puede seguir en `127.0.0.1`.
9. **Frontend:** servicio `ApiService` con sondeo de 60 s serializado (`exhaustMap`), estado global de filtros con señales de Angular, gráficos en SVG propios (sin librería nueva), clustering de `leaflet.markercluster` retirado del mapa principal para respetar tamaño/color por evento (se conserva opcional).
10. **Evidencias:** scripts reproducibles en `backend/tools/` (calidad, benchmark) que generan las cifras citadas en `docs/`; la memoria cita el comando exacto.
11. **Contrato API:** como `CONTRATO-API.md` no está versionado, la fase 0 lo copia a `docs/` (lo aporta el alumno) y las respuestas se alinean con él; donde el contrato no decide se aplica lo fijado en la spec de este cambio.

## Risks / Trade-offs

- [Escritura del productor en PostgreSQL añade acoplamiento] → cliente tolerante a fallo y registros no críticos para la publicación.
- [Carga del catálogo ralentiza el arranque] → ~250 polígonos, coste de ms; cache en memoria.
- [Polígonos simplificados clasifican mal costas] → documentado como limitación de exactitud; "Sin país asignado" no es error.
- [Replay y live comparten consumidor] → esquema aislado y test que verifica que los recuentos live no cambian.
- [Eliminar WebSocket rompe la pestaña y Cypress actuales] → fase específica que migra o borra esos tests.
- [Datos históricos pesados] → fuera de Git, regenerables con un comando.
- [Cuota gratuita de ngrok/Netlify] → sondeo de 60 s y sin refrescos extra.

## Migration Plan

Fases independientes y verificables, cada una con sus tests; `docker compose up --build -d` debe seguir funcionando al final de cada fase. Las migraciones son aditivas (`IF NOT EXISTS`, `ADD COLUMN IF NOT EXISTS`); el rollback es descartar el volumen en desarrollo. El borrado del WebSocket es la única rotura (BREAKING) y se hace tras tener la API REST y el sondeo funcionando.

## Open Questions

- Contenido exacto de `CONTRATO-API.md` (nombres de campos de `/api/estadisticas`): se alinea al aportarlo; no cambia el desglose de tareas.
