# Complejidad y rendimiento

Reproducible con `docker compose run --rm producer python tools/benchmark.py` (necesita el histórico 2025 cargado). Entorno de la medición: PostgreSQL 17.5 en Docker Desktop (Windows 11), 12 CPU lógicas, 15 GB de RAM; cliente Python en otro contenedor de la misma red. Los tiempos son medianas de varias repeticiones y varían entre ejecuciones (±30–50 % en las cifras pequeñas); lo que importa es la **tendencia con n**.

## Qué se mide

Tres tamaños de entrada: **18.302** filas (todos los eventos reales de 2025), **183.020** (×10) y **1.830.200** (×100). Los dos tamaños mayores son **réplicas sintéticas** de los reales (id `synthetic-k-…`, columna `synthetic = TRUE`); viven solo en el esquema temporal `bench`, que se elimina al terminar, así que **no entran en ninguna consulta analítica ni en [analisis.md](analisis.md)**. Las réplicas conservan la distribución pero no la variedad real; sirven para escalar, no para concluir sobre sismicidad.

Operaciones:

1. **Búsqueda por id** (50 ids al azar): diccionario Python (hash, O(1)) frente a recorrido de lista (O(n)), y PostgreSQL con índice B-tree único (O(log n)) frente a tabla sin índice (recorrido secuencial, O(n)).
2. **Rango de un día** por instante: recorrido de lista (O(n)), lista ordenada + `bisect` (O(log n + k)), PostgreSQL con y sin índice sobre `t`. Las cuatro estrategias devuelven el mismo número de filas (el script lo comprueba con `assert`).
3. **`GROUP BY country_id`** (agregación completa, O(n) inevitable).

## Resultados

Filas **sintéticas** (réplicas de los datos reales de 2025 con id `synthetic-k-…`) solo existen en el esquema temporal `bench`, que se elimina al terminar; no están en las tablas analíticas.

| n filas | reales | sintéticas |
|---:|---:|---:|
| 18,302 | 18,302 | 0 |
| 183,020 | 18,302 | 164,718 |
| 1,830,200 | 18,302 | 1,811,898 |

### Búsqueda por id (µs por consulta, mediana)

| n | dict Python O(1) | recorrido lista O(n) | PostgreSQL con índice | PostgreSQL sin índice (seq scan) |
|---:|---:|---:|---:|---:|
| 18,302 | 0.04 | 117 | 213 | 1,046 |
| 183,020 | 0.04 | 1,810 | 167 | 9,172 |
| 1,830,200 | 0.04 | 21,259 | 249 | 87,768 |

### Rango de un día (mismo resultado en las 4 estrategias)

| n | filas en el rango | lista O(n) (ms) | lista ordenada + bisect (µs) | PostgreSQL con índice (ms) | PostgreSQL sin índice (ms) | GROUP BY país (ms) |
|---:|---:|---:|---:|---:|---:|---:|
| 18,302 | 51 | 0.5 | 0.3 | 0.28 | 0.8 | 2.4 |
| 183,020 | 510 | 5.3 | 0.3 | 0.42 | 8.1 | 31.0 |
| 1,830,200 | 5100 | 56.6 | 0.3 | 1.50 | 74.1 | 146.8 |

### Memoria y tamaño

| n | pico Python dict (MB) | pico Python lista ordenada (MB) | tabla PG (MB) | índices PG (MB) |
|---:|---:|---:|---:|---:|
| 18,302 | 0.6 | 0.4 | 1.7 | 1.2 |
| 183,020 | 11.5 | 4.4 | 15.3 | 10.3 |
| 1,830,200 | 92.3 | 43.9 | 154.8 | 99.6 |

### Planes de ejecución (último tamaño)

- con índice: `Index Scan using idx_pk on idx  (cost=0.43..8.45 rows=1 width=52)`
- sin índice: `Gather  (cost=1000.00..29428.39 rows=1 width=52) / Workers Planned: 2 / ->  Parallel Seq Scan on plain  (cost=0.00..28428.29 rows=1 width=52)`

## Lectura

- **Diccionario frente a recorrido:** la búsqueda en el diccionario es constante (≈ 0,04 µs) en los tres tamaños; el recorrido de lista crece linealmente (117 µs → 1,8 ms → 21 ms: ×100 de datos ≈ ×180 de tiempo). El diccionario cuesta memoria (≈ 50 B por entrada de índice: 92 MB a 1,8 M filas).
- **Con y sin índice en PostgreSQL:** con índice la consulta puntual se mantiene en ≈ 0,2 ms (dominada por el viaje de red cliente-servidor, no por el plan); sin índice crece de ≈ 1 ms a ≈ 50–90 ms (el plan es un `Parallel Seq Scan`, mientras que con índice es un `Index Scan`). A 1,8 M filas el índice aporta un factor ≈ 200–400.
- **Rango temporal:** `bisect` y el índice sobre `t` apenas crecen con n (devuelven k filas; k crece porque la réplica multiplica los eventos por día), mientras que los recorridos completos pasan de 0,5–0,8 ms a 57–74 ms.
- **La agregación** (`GROUP BY`) es lineal con índice o sin él (147 ms a 1,8 M filas): un índice no evita leer todas las filas; por eso la API agrega siempre sobre `current_events` filtrado por tiempo (índice en `time_utc`) y limita el periodo horario a 31 días.
- **Coste del índice:** a 1,8 M filas los índices ocupan 99,6 MB frente a 154,8 MB de tabla (≈ 64 %) y encarecen cada escritura; en este sistema la escritura es de un evento por segundo, así que compensa con holgura.

## Razonamiento a 100 millones de filas (sin ejecutar)

Extrapolación lineal desde el tamaño mayor (×55):

| Estrategia | 1,8 M medido | 100 M estimado | Veredicto |
|---|---|---|---|
| Búsqueda por id con índice B-tree | ≈ 0,2 ms | ≈ 0,2–0,3 ms (un nivel más de árbol) | viable |
| Búsqueda por id sin índice | 50–90 ms | **3–5 s** por consulta | inviable para una API |
| Recorrido de lista en Python | 21 ms | ≈ **1,2 s**, y las filas no caben en RAM | inviable |
| Diccionario Python en memoria | 92 MB (solo el índice) | ≈ 5 GB solo de índice, más las filas | no escala en un proceso; sí como caché de claves calientes |
| Tabla + índices en PostgreSQL (esquema estrecho del benchmark) | 155 + 100 MB | ≈ 8,5 GB + 5,4 GB | viable en un nodo |
| `current_events` real (≈ 600 B/fila con `original_feature` JSONB, estimación) | — | ≈ 60 GB + índices | viable en un nodo, con particionado por mes |
| `GROUP BY` completo | 147 ms | ≈ **8 s** | requiere pre-agregación |

Decisiones que se tomarían a esa escala: partición declarativa de `current_events` y `event_versions` por mes de `time_utc` (el filtro por periodo poda particiones); índice BRIN en `time_utc` si los datos entran en orden temporal (decenas de KB en lugar de GB); tabla de agregados por hora y país refrescada de forma incremental para las estadísticas; mover `original_feature` a una tabla aparte o a almacenamiento de objetos; y réplicas de lectura para la API. Ninguna de ellas añade infraestructura: son decisiones de modelado sobre el PostgreSQL existente.
