# Costes, escalado y fiabilidad

Medido el 2026-11-18 con la pila completa en Docker Desktop (Windows 11, 12 CPU, 15 GB de RAM), con el histórico 2025 cargado y ≈ 1 hora de datos en vivo.

## 1. Coste de ejecución actual

| Servicio | Memoria en reposo | CPU en reposo |
|---|---:|---:|
| `postgres` | 170 MiB | < 0,1 % |
| `producer` | 35 MiB | ≈ 0 % |
| `consumer` | 38 MiB | 0,2 % |
| `api` | 40 MiB | 0,1 % |
| `kafka` (KRaft, un nodo) | 570 MiB | variable (JVM) |
| **Total** | **≈ 0,85 GiB** | |

Kafka es con diferencia el componente más caro (JVM); el resto cabe en un portátil. No se añade infraestructura nueva: el túnel `ngrok` es un perfil opcional y el histórico/replay son comandos puntuales.

## 2. Volumen de datos y almacenamiento

| Dato | Tamaño medido | Crecimiento |
|---|---:|---|
| `historical_events` (18.302 filas) | 4,3 MB (≈ 240 B/fila) | fijo (carga única) |
| Ficheros del histórico (`backend/data/historical`, git-ignored) | 13 MB | fijo |
| `event_versions` / `current_events` | ≈ 1,8–2,1 KB/fila a esta escala (incluye JSONB original, índices y relleno de página) | ≈ 200–300 eventos nuevos/día en el feed «all_day» (todas las magnitudes) → del orden de **0,5 MB/día** |
| `raw_payloads` (GeoJSON original) | ≈ 32 KB por payload distinto | hasta 1.440 sondeos/día → **≈ 46 MB/día** si todos difirieran; la retención de **7 días** lo acota a ≈ **320 MB** |
| `poll_log`, `poll_exclusions` | < 1 KB/fila | ≈ 1.440 + ≈ 100–200 filas/día: despreciable |
| Kafka (retención 168 h) | ≈ 1 KB/mensaje | ≈ 0,3 MB/día |
| Base de datos completa hoy | 14 MB | — |

La partida que domina el crecimiento es `raw_payloads`, no los eventos. Por eso tiene retención diaria y deduplicación por SHA-256 (un payload idéntico entre sondeos consecutivos se guarda una vez).

## 3. Coste de red y de cuotas

- **USGS:** 1 petición/minuto = 1.440/día al feed (≈ 90 ms cada una según `poll_log`); una descarga histórica puntual de 12 peticiones (≈ 13 MB).
- **API ↔ panel:** cada pestaña abierta hace 3 peticiones cada 60 s (`/api/salud`, `/api/eventos`, `/api/estadisticas`) = **4.320 peticiones/día por pestaña**. El sondeo está serializado (nunca hay dos en vuelo) y la API usa un pool de 1–5 conexiones.
- **Túnel y alojamiento gratuitos (ngrok, Netlify):** el sondeo de 60 s y la ausencia de refrescos adicionales mantienen el tráfico bajo; el límite práctico lo marcan las cuotas del plan gratuito vigentes, que deben comprobarse antes de una demostración con muchos asistentes (no se asumen cifras aquí).

## 4. Qué se paga al escalar

| Si crece… | Primer cuello de botella | Respuesta dentro de PostgreSQL/Kafka (sin nuevos componentes) |
|---|---|---|
| Número de pestañas abiertas | CPU de la API y conexiones | cabeceras de caché + `ETag`, aumentar `max_size` del pool, réplicas de lectura |
| Frecuencia del feed | tamaño de `raw_payloads` | menor retención o guardar solo el *diff* |
| Años de histórico (10⁸ filas) | agregaciones completas y tamaño de índices | partición mensual, índice BRIN, tabla de agregados por hora y país (ver [complejidad.md](complejidad.md)) |
| Más países/polígonos | arranque del consumidor | `STRtree` en memoria: O(log n) por punto; cientos de polígonos cuestan milisegundos |

## 5. Fiabilidad y coste de fallo

- **PostgreSQL caído:** la API devuelve 503 con `Retry-After` (verificado), el productor sigue publicando y registrando en logs; el consumidor reintenta y no confirma el *offset* de Kafka hasta persistir, de modo que no se pierde ningún mensaje.
- **Kafka caído:** el productor reintenta (3 intentos con espera progresiva) y no marca el evento como publicado hasta el acuse.
- **USGS caído:** se salta el ciclo y el siguiente sondeo recupera lo que siga en la ventana de 24 h; un evento que salga de la ventana antes de recuperarse no se puede reponer (limitación documentada).
- **Túnel caído:** el panel conserva la última lectura, avisa con un banner y se recupera solo.

## 6. Qué no se ha medido

No se han medido costes monetarios de nube, consumo energético ni el rendimiento con decenas de clientes concurrentes; las cifras de memoria y crecimiento son de una sola máquina de desarrollo y de un periodo corto de datos en vivo.
