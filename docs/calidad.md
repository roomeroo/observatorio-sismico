<!-- Generado con: docker compose run --rm producer python tools/quality.py > docs/calidad.md -->
# Calidad de datos

_Generado por `backend/tools/quality.py`; cada cifra procede de la consulta indicada._

## Antes y después

| Etapa | Medida | Valor |
|---|---|---:|
| Antes (feed bruto) | Sondeos con payload guardado | 26 |
| Antes (feed bruto) | Features recibidas (suma de todos los sondeos) | 4941 |
| Antes (feed bruto) | Features que no son `earthquake` (excluidas) | 78 |
| Antes (feed bruto) | Versiones distintas (id, updated) de terremotos en los payloads | 197 |
| Antes (feed bruto) | Eventos distintos (id) de terremotos en los payloads | 190 |
| Antes (feed bruto) | Terremotos con magnitud nula en el payload (versiones distintas) | 0 |
| Después (PostgreSQL) | Versiones en `event_versions` | 197 |
| Después (PostgreSQL) | Eventos en `current_events` | 190 |
| Después (PostgreSQL) | Registros en cuarentena | 0 |

Decisión: el feed repite cada evento en cada sondeo (≈4941 features para 190 eventos distintos). Solo se publica la primera aparición de cada versión `(id, updated)`; solo `current_events` alimenta agregaciones.

Descartes del productor por motivo (`poll_exclusions`):

- `EVENT_TYPE_QUARRY BLAST`: 52
- `EVENT_TYPE_EXPLOSION`: 26

## 1. Completitud

| Medida | Valor | Consulta |
|---|---:|---|
| Magnitud nula | 0 | `SELECT count(*) FROM observatorio.current_events WHERE mag IS NULL` |
| Lugar nulo | 0 | `SELECT count(*) FROM observatorio.current_events WHERE place IS NULL` |
| Profundidad nula | 0 | `SELECT count(*) FROM observatorio.current_events WHERE depth IS NULL` |
| Sin país asignado | 31 | `SELECT count(*) FROM observatorio.current_events WHERE country_id IS NULL` |
| Histórico 2025: eventos | 18302 | `SELECT count(*) FROM observatorio.historical_events` |
| Histórico 2025: magnitud nula | 0 | `SELECT count(*) FROM observatorio.historical_events WHERE mag IS NULL` |
| Histórico 2025: profundidad nula | 0 | `SELECT count(*) FROM observatorio.historical_events WHERE depth IS NULL` |
| Histórico 2025: sin país | 14350 | `SELECT count(*) FROM observatorio.historical_events WHERE country_id IS NULL` |

Tiempo real: magnitud nula 0.0 %, sin país 16.3 %. Histórico: magnitud nula 0.0 %, sin país 78.4 %. Una magnitud nula se conserva y se muestra «ND»; nunca se imputa 0.

## 2. Unicidad

| Medida | Valor | Consulta |
|---|---:|---|
| Pares (id, updated) repetidos en `event_versions` | 0 | `SELECT count(*) FROM (SELECT event_id, updated FROM observatorio.event_versions GROUP BY 1,2 HAVING count(*)>1) t` |
| ids repetidos en `current_events` | 0 | `SELECT count(*) FROM (SELECT event_id FROM observatorio.current_events GROUP BY 1 HAVING count(*)>1) t` |
| Eventos con más de una versión (revisados) | 6 | `SELECT count(*) FROM (SELECT event_id FROM observatorio.event_versions GROUP BY 1 HAVING count(*)>1) t` |

La clave `(event_id, updated)` y el `ON CONFLICT` hacen imposibles los duplicados; los reenvíos idénticos se ignoran y los conflictos de carga distinta van a cuarentena.

## 3. Validez

| Medida | Valor | Consulta |
|---|---:|---|
| Coordenadas fuera de rango | 0 | `SELECT count(*) FROM observatorio.current_events WHERE longitude NOT BETWEEN -180 AND 180 OR latitude NOT BETWEEN -90 AND 90` |
| Magnitud fuera de [-2, 10] | 0 | `SELECT count(*) FROM observatorio.current_events WHERE mag IS NOT NULL AND mag NOT BETWEEN -2 AND 10` |
| Profundidad fuera de [-10, 800] km | 0 | `SELECT count(*) FROM observatorio.current_events WHERE depth NOT BETWEEN -10 AND 800` |
| Eventos con hora en el futuro | 0 | `SELECT count(*) FROM observatorio.current_events WHERE time_utc > clock_timestamp()` |
| `event_type` distinto de earthquake en el estado actual | 0 | `SELECT count(*) FROM observatorio.current_events WHERE event_type <> 'earthquake'` |

La validación del consumidor rechaza lo inválido antes de persistir (cuarentena); aquí se comprueba que nada inválido llegó al estado actual.

## 4. Consistencia

| Medida | Valor | Consulta |
|---|---:|---|
| Eventos cuyo estado actual no es la versión más reciente | 0 | `SELECT count(*) FROM observatorio.current_events c JOIN (SELECT event_id, max(updated) m FROM observatorio.event_versions GROUP BY 1) v USING (event_id) WHERE c.updated <> v.m` |
| Revisión anterior a la hora del evento | 0 | `SELECT count(*) FROM observatorio.current_events WHERE updated_utc < time_utc` |
| country_id sin fila en `dim_country` | 0 | `SELECT count(*) FROM observatorio.current_events c LEFT JOIN observatorio.dim_country d USING (country_id) WHERE c.country_id IS NOT NULL AND d.country_id IS NULL` |
| Asignaciones de país ambiguas (frontera) | 0 | `SELECT count(*) FROM observatorio.current_events WHERE geo_ambiguous` |

Una versión más antigua nunca sustituye a la actual (`WHERE EXCLUDED.updated > current.updated`).

## 5. Oportunidad (timeliness)

| Medida | Valor | Consulta |
|---|---:|---|
| Retraso evento → ingesta, mediana (s) | 51861.0 | `SELECT round(percentile_cont(0.5) WITHIN GROUP (ORDER BY extract(epoch FROM ingested_at - time_utc))::numeric,0) FROM observatorio.current_events` |
| Retraso evento → ingesta, p95 (s) | 83892.0 | `SELECT round(percentile_cont(0.95) WITHIN GROUP (ORDER BY extract(epoch FROM ingested_at - time_utc))::numeric,0) FROM observatorio.current_events` |
| Retraso ingesta → PostgreSQL, p95 (s) | 299.04 | `SELECT round(percentile_cont(0.95) WITHIN GROUP (ORDER BY extract(epoch FROM received_at - ingested_at))::numeric,2) FROM observatorio.event_versions` |
| Latencia del sondeo USGS, mediana (ms) | 104.0 | `SELECT percentile_cont(0.5) WITHIN GROUP (ORDER BY latency_ms) FROM observatorio.poll_log WHERE status='ok'` |
| Latencia del sondeo USGS, p95 (ms) | 125.0 | `SELECT percentile_cont(0.95) WITHIN GROUP (ORDER BY latency_ms) FROM observatorio.poll_log WHERE status='ok'` |
| Sondeos fallidos | 0 | `SELECT count(*) FROM observatorio.poll_log WHERE status <> 'ok'` |

El retraso evento → ingesta depende de cuándo USGS publica o revisa el evento (el feed es una ventana rodante de 24 h y la ingesta de un evento ocurre al aparecer su versión). El tramo ingesta → PostgreSQL incluye la espera en Kafka cuando el consumidor estuvo parado o reiniciándose, por eso su p95 es mayor que la mediana.

## 6. Exactitud

Sin verdad terreno oficial, se usa un contraste independiente: el texto `place` de USGS termina casi siempre en el nombre del país. `place` nombra el país del pueblo de referencia, que puede estar a cientos de km del epicentro; por eso solo se contrastan los eventos a ≤ 20 km del pueblo (los 11813 restantes con sufijo reconocible están lejos de la costa y no son comparables). Sobre el histórico 2025, de los 1630 eventos comparables la asignación por polígono coincide en **1167** (71.6 %).

Ejemplos de discrepancia (id, lugar, asignado, esperado):

- `us6000pgse` · 18 km NW of Port-Vila, Vanuatu · None · VUT
- `us6000phj9` · 10 km SW of Alanya, Turkey · None · TUR
- `us6000pht8` · 16 km WSW of Port-Vila, Vanuatu · None · VUT
- `us6000phuj` · 15 km NNW of Port-Vila, Vanuatu · None · VUT
- `us6000phws` · 7 km E of Lakatoro, Vanuatu · None · VUT

La causa típica es la simplificación de costas del catálogo de baja resolución (ver `diccionario-datos.md`).

## Registros de ejemplo

**excluded**

- `('ci41363087', 'EVENT_TYPE_QUARRY BLAST', '6 km WSW of Pala, CA')`
- `('ci41363095', 'EVENT_TYPE_QUARRY BLAST', '2 km E of Home Gardens, CA')`
- `('uw714140061', 'EVENT_TYPE_EXPLOSION', '12 km SW of Chilliwack, Canada')`

**quarantine**

- (sin registros)

**revised**

- `('se60506583', 3, 2.23, 2.23)`
- `('nc75468047', 2, 1.54, 1.54)`
- `('hv75071852', 2, 1.75, 2.07)`

**null_mag**

- (sin registros)

