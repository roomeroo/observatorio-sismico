# Procedencia de los datos

## Fuente en vivo
- Feed `all_day.geojson` de USGS (`https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/all_day.geojson`), sondeado cada 60 s por el productor.
- Cada sondeo queda en `observatorio.poll_log` (estado, latencia, recuento, error); los descartes con su motivo, en `observatorio.poll_exclusions` (p. ej. `EVENT_TYPE_QUARRY BLAST`, `EVENT_TYPE_EXPLOSION`); el GeoJSON original, deduplicado por SHA-256, en `observatorio.raw_payloads` con retención de 7 días.

## Histórico 2025
Servicio FDSN de USGS: `https://earthquake.usgs.gov/fdsnws/event/1/query`, parámetros `format=geojson`, `minmagnitude=4`, `eventtype=earthquake`, `orderby=time-asc`, `limit=20000`, un intervalo por mes (UTC, fin exclusivo).

Comando (misma imagen del backend, ficheros en `backend/data/historical/`, ignorado por Git):

```
docker compose run --rm -v "<ruta-absoluta>/backend/data:/app/data" producer python -m observatorio.historical --year 2025
```

Un intervalo que alcanza 20.000 eventos se biseca de forma recursiva y su respuesta truncada **no** se usa. Una reejecución reutiliza los ficheros y `manifest.json` sin red (`--refresh` fuerza nueva descarga).

### Resultado de la ejecución real (2026-11-18)

| Mes 2025 | Eventos | | Mes 2025 | Eventos |
|---|---:|---|---|---:|
| Enero | 1.413 | | Julio | 2.684 |
| Febrero | 1.394 | | Agosto | 2.222 |
| Marzo | 1.178 | | Septiembre | 1.604 |
| Abril | 1.316 | | Octubre | 1.509 |
| Mayo | 1.228 | | Noviembre | 1.321 |
| Junio | 1.156 | | Diciembre | 1.277 |

- 12 consultas, ninguna alcanzó el límite (máximo mensual 2.684), sin bisección.
- Suma devuelta = 18.302 = eventos únicos = `SELECT count(*) FROM observatorio.historical_events` (sin duplicados de frontera porque USGS trata el fin como exclusivo; la deduplicación por `id` se prueba igualmente con tests).
- 3.952 eventos (21,6 %) con `country_id`; el resto queda como «Sin país asignado» (mar abierto o costa fuera de los polígonos simplificados).
- Reejecución offline (`docker run --network none`): 12/12 consultas reutilizadas, 18.302 eventos, sin peticiones HTTP.

Comprobación SQL de procedencia:

```sql
SELECT count(*) AS consultas, sum(result_count) AS devueltos FROM observatorio.extraction_queries;  -- 12, 18302
SELECT count(*) FROM observatorio.historical_events;                                               -- 18302
```
