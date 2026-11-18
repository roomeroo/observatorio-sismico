## Why

El pipeline Kafka → consumidor → PostgreSQL funciona, pero la rúbrica puntúa Modelado, Análisis y Reflexión y hoy no hay integración geográfica, histórico, API REST de consulta, reproducción, panel analítico ni memoria de evidencias. Sin ello el proyecto no supera "Suficiente" en la mayoría de criterios. El enunciado además prohíbe subir nota con más infraestructura, así que el cambio cierra huecos de cobertura y calidad analítica, no añade componentes.

## What Changes

- **Integración geográfica** en el consumidor: punto-en-polígono con Shapely contra `paises.geojson`, `country_id` = `ADM0_A3` (unicidad verificada al cargar), regla determinista para frontera/múltiples coincidencias, "Sin país asignado" conservado. Tablas `dim_country` y `dim_date`.
- **Histórico 2025** (M≥4, `earthquake`): descarga mensual con subdivisión si se alcanza el límite de 20.000, deduplicación de extremos, archivos reutilizables offline, tablas de registro de consultas y de eventos históricos.
- **API REST** FastAPI sobre `current_events`: `/api/eventos` (GeoJSON), `/api/estadisticas`, `/api/salud`, filtros fecha/magnitud/país/subregión, ventanas UTC de una hora, distribuciones con nulos, comparación 24 h vs media diaria 2025 (con días a cero), estado del sistema. CORS por origen exacto, `OPTIONS`, `ngrok-skip-browser-warning`, sin rutas de administración.
- **BREAKING**: se retiran el WebSocket `/ws/earthquakes`, el `POST /ws/earthquakes/broadcast` y el código duplicado `backend/src/` y `backend/observatorio/src/`. El panel pasa a sondear la API cada 60 s.
- **Reproducción acelerada**: topic `earthquakes-replay` y esquema PostgreSQL `replay` aislados, etiquetada "REPRODUCCIÓN", con duplicados y revisiones controlados, reutilizando la validación y persistencia del consumidor. Se lanza como comando puntual del mismo contenedor, no como sexto servicio permanente.
- **Productor**: persistir el motivo de exclusión, los metadatos de cada consulta y el GeoJSON original con retención.
- **Panel Angular + Leaflet**: mapa (tamaño por magnitud, color por profundidad, leyenda, ND), ficha, filtros coherentes entre mapa/gráficos/tabla, gráficos de recuentos, ventanas y distribuciones, tabla consultable, panel de estado con banner de fallo y recuperación automática.
- **Despliegue**: perfil Compose opcional `tunnel` con ngrok, `.env.example` ampliado (sin token), `config.json` con `apiUrl`.
- **Evidencias** en `docs/`: diccionario de datos, calidad (6 dimensiones, antes/después), modelo conceptual/lógico/físico, benchmark de complejidad con 3 tamaños, costes y escalado, ≥3 conclusiones, matriz de las 11 pruebas de aceptación.
- **Pruebas** que faltan: versión antigua no sustituye, evento marítimo, magnitud nula como ND, reinicio del consumidor, caída y vuelta del túnel.

## Capabilities

### New Capabilities

Ninguna: las capacidades ya existen en `openspec/specs/`; este cambio las completa y resuelve sus "Clarifications Pending".

### Modified Capabilities

- `geographic-enrichment`: regla de frontera/múltiples coincidencias, dimensiones país y fecha, columnas de país en el estado.
- `historical-data-acquisition`: partición mensual, registro de consultas y procedencia, reutilización offline.
- `historical-replay`: mecanismo de selección y consulta de la reproducción, aislamiento de `last_ingestion`.
- `usgs-live-ingestion`: registro persistente de exclusiones y metadatos de extracción.
- `query-api`: forma de `/api/estadisticas`, paginación, errores de filtros, filtro por subregión, CORS.
- `dashboard-and-analysis`: filtros coherentes, estado visible, banner de fallo y recuperación.
- `real-time-map`: sondeo de la API en lugar de streaming; se retira el WebSocket.
- `runtime-deployment-and-publication`: perfil ngrok, orígenes CORS configurables, retirada de rutas no previstas.
- `project-evaluation-evidence`: entregables de memoria y matriz de aceptación.

## Impact

- Código: `backend/observatorio/{api,consumer,persistence,validation,producer}.py`, nuevos módulos `geo`, `historical`, `replay`, `stats`, migración `0003`.
- Eliminados: `backend/src/`, `backend/observatorio/src/`, `observatorio/websocket.py`, tests de websocket.
- Dependencias: `shapely` en `requirements.txt` (versión fijada); frontend sin librería de gráficos nueva (SVG propio).
- `compose.yaml`: perfil `tunnel`, variables CORS y topic de replay; los cinco servicios obligatorios no cambian.
- Frontend: `app.component`, nuevo servicio de API, componentes de mapa, gráficos, tabla y estado; `config.json`.
- Fuera de alcance: Spark/Flink/K8s, reconciliación exhaustiva de eventos eliminados, autenticación de la API.
