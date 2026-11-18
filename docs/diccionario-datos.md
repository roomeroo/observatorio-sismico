# Diccionario de datos

Esquema PostgreSQL `observatorio`. Las migraciones de `backend/observatorio/migrations/` son la fuente única del esquema.

## Tablas de eventos

| Tabla | Clave | Contenido |
|---|---|---|
| `event_versions` | `(event_id, updated)` | Cada versión aceptada de un evento (histórico completo, inmutable). |
| `current_events` | `event_id` | Última versión conocida de cada evento (`updated` más alto). Es la fuente de toda agregación. |
| `quarantine_records` | `(kafka_topic, kafka_partition, kafka_offset)` | Mensajes rechazados con su motivo. |

Columnas principales de `event_versions` / `current_events`:

| Columna | Tipo | Significado |
|---|---|---|
| `event_id` | texto | Identificador USGS del evento. |
| `updated` | bigint | Marca de última actualización (ms epoch); decide qué versión es la actual. |
| `time_utc` | timestamptz | Instante del evento en UTC. |
| `mag`, `mag_type` | double, texto | Magnitud (puede ser nula → «ND») y su tipo. |
| `longitude`, `latitude`, `depth` | double | Epicentro; `depth` en km. |
| `place`, `status`, `event_type` | texto | Descripción, estado de revisión y tipo. |
| `original_feature` | jsonb | Feature GeoJSON original, sin alterar. |
| `country_id` | texto | `ADM0_A3` del país asignado; **`NULL` = «Sin país asignado»**. |
| `geo_ambiguous` | boolean | `true` si el punto coincidió con más de una entidad del catálogo. |

## Dimensiones

### `dim_country`

Una fila por `ADM0_A3` único del catálogo `paises.geojson` (Natural Earth, copia en `backend/observatorio/data/`).

| Columna | Origen en el catálogo |
|---|---|
| `country_id` | `ADM0_A3` |
| `name` | `NAME_ES` (si falta: `NAME`, `ADMIN`) |
| `iso_a2` | `ISO_A2` (`-99` → nulo) |
| `continent` | `CONTINENT` |
| `subregion` | `SUBREGION` |

Se carga al arrancar el consumidor con un *upsert*, por lo que reiniciarlo no añade filas.

Se usa `ADM0_A3` y no `ISO_A3` como identificador porque `ISO_A3` vale `-99` en varias entidades (no es único); `ADM0_A3` sí lo es en el catálogo incluido. Si un catálogo futuro trajera `ADM0_A3` duplicados, el consumidor lo registra en el log, conserva los atributos de la primera aparición y **une las geometrías** para no perder superficie.

### `dim_date`

Una fila por fecha UTC que aparece en algún evento (`date_key`, año, mes, día, semana ISO, día de la semana ISO). Se rellena por *upsert* al persistir cada evento.

## Regla de asignación geográfica

Implementada en `backend/observatorio/geo.py`:

1. Se construye en memoria un `STRtree` de Shapely con los polígonos del catálogo.
2. Un punto **en el borde** de un polígono se considera dentro (semántica `covers`).
3. Si el punto coincide con **varias** entidades (frontera compartida o solapamiento), se elige la de **menor `ADM0_A3`** (orden lexicográfico) y se marca `geo_ambiguous = true`.
4. Si no coincide con ninguna (océano), `country_id` queda `NULL` y el evento **se conserva** en el estado actual y en las agregaciones bajo «Sin país asignado».

La regla es determinista: reprocesar el mismo mensaje produce la misma asignación.

### Aviso de exactitud

El catálogo es de baja resolución. Las costas están simplificadas, por lo que un epicentro marino cercano a la costa puede quedar sin país o asignado al vecino. «Sin país asignado» **no es un error de datos**: la mayoría de los sismos ocurren en el mar. Las cifras por país deben leerse como una aproximación geográfica, no como atribución administrativa oficial.
