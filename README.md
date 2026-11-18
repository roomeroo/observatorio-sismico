# Observatorio de actividad sísmica

Sistema que recoge terremotos de USGS, los valida, los enriquece con el país donde ocurren, los guarda y los muestra en un panel web. Responde a: **¿dónde se está registrando actividad sísmica y cómo se compara con un periodo histórico equivalente?**

- Panel publicado: <https://adrian-observatorio-sismico.netlify.app> (necesita el backend y el túnel encendidos).
- Flujo: **USGS → productor → Kafka → consumidor → PostgreSQL → API FastAPI → ngrok (HTTPS) → panel Angular + Leaflet en Netlify**.

> Cómo usar este documento: la sección 2 recorre la rúbrica criterio por criterio. Cada uno tiene **qué hice**, **cómo**, **dónde está la evidencia** y **qué decir**. Las secciones 3–6 son el arranque, la demostración y la lista de capturas.

---

## 1. Arquitectura en 30 segundos

| Servicio (Docker Compose) | Qué hace |
|---|---|
| `producer` | Consulta el feed de USGS cada 60 s, publica en Kafka solo las versiones nuevas y guarda cada sondeo, sus descartes y el GeoJSON original. |
| `kafka` | Transporta los mensajes (topic `earthquakes-live` y, para la reproducción, `earthquakes-replay`). |
| `consumer` | Valida, convierte, asigna país por punto-en-polígono y escribe en PostgreSQL de forma idempotente. Lo rechazado va a cuarentena. |
| `postgres` | Esquema `observatorio` (en vivo) y esquema aislado `replay`. |
| `api` | FastAPI de solo lectura: `/api/eventos`, `/api/estadisticas`, `/api/salud`. |

Extras: perfil opcional `tunnel` (ngrok, HTTPS) y dos comandos puntuales con la misma imagen: `observatorio.historical` (descarga 2025) y `observatorio.replay` (reproducción acelerada). **Son los cinco servicios obligatorios; no añadí infraestructura nueva.**

---

## 2. La rúbrica, punto por punto

### 2.1 Extracción — «Carga + análisis de tipos»

**Qué hice.** Cargo las tres fuentes que pide el enunciado y las trato de forma automática:

| Fuente | Cómo se extrae | Resultado |
|---|---|---|
| Feed reciente (`all_day.geojson`) | Productor Python con `httpx`/`aiokafka`, un sondeo cada 60 s | Se guarda cada sondeo (estado, latencia, nº de features, error) |
| Histórico 2025 (FDSN) | `python -m observatorio.historical`, un mes por consulta | **18.302 eventos** M≥4 en 12 consultas; ficheros reutilizables sin red |
| Catálogo geográfico | `paises.geojson` de Natural Earth (110 m) | 177 entidades con `ADM0_A3` único |

**Cómo.**
- **Automatización y robustez del feed:** reintentos con espera progresiva (3 intentos; 20 s y 40 s), tratamiento de HTTP 429/5xx, timeout y JSON inválido. Si falla, se salta el ciclo y no se borra el estado válido anterior.
- **Estado persistente del productor** (SQLite en un volumen): guarda el último `updated` publicado de cada `id`. Solo marca la versión como publicada **después** de la confirmación de Kafka (si cae entre ambos pasos, reenvía y el consumidor lo tolera).
- **Histórico sin truncar en silencio:** si un mes llega a 20.000 resultados, se **biseca** de forma recursiva y la respuesta truncada no se usa. Los eventos de frontera se deduplican por `id`. El resultado real: ningún mes llegó al límite (máximo 2.684 en julio). Reejecución sin red verificada (`docker run --network none`: 12/12 consultas reutilizadas).
- **Procedencia:** cada consulta queda en `extraction_queries` (URL, parámetros, estado HTTP, nº de registros, fecha, huella SHA-256 del fichero) y el GeoJSON original del feed se guarda deduplicado por hash con retención de 7 días.
- **Descartes con motivo:** se filtra `type == "earthquake"` y se guarda por qué se excluye cada otro (p. ej. `EVENT_TYPE_QUARRY BLAST`, `EVENT_TYPE_EXPLOSION`).

**Análisis de tipos y unidades** (del feed; ejemplo medido, no supuesto):

| Campo | Tipo | Unidad / formato | ¿Puede faltar? | Tratamiento |
|---|---|---|---|---|
| `id` | texto | identificador estable entre revisiones | no | clave del evento y de Kafka |
| `properties.time` | entero | ms Unix (ocurrencia) | raro | se convierte a UTC y se conserva el original |
| `properties.updated` | entero | ms Unix (revisión de la fuente) | no | decide qué versión es la actual |
| `properties.mag` | número | magnitud (la escala la da `magType`) | **sí (`null`)** | se conserva nulo; se muestra «ND»; nunca se imputa 0 |
| `properties.magType` | texto | tipo de escala (`ml`, `mb`, `mw`…) | sí | se conserva |
| `properties.type` | texto | tipo de evento | no | solo `earthquake` pasa |
| `properties.place` | texto | descripción | sí | solo informativo; **no** se usa para asignar país |
| `geometry.coordinates` | `[lon, lat, prof]` | grados WGS84, **profundidad en km** | no | validadas: finitas y en rango |

Distinciones que conviene saber contar: el feed es una **ventana móvil de 24 h** (cada respuesta repite todo, por eso hay que deduplicar), `time` ≠ `updated` ≠ hora de ingesta, y la profundidad puede ser negativa o la magnitud negativa sin ser error.

**Evidencia.** [docs/procedencia.md](docs/procedencia.md), [docs/diccionario-datos.md](docs/diccionario-datos.md); código en `backend/observatorio/{producer,usgs_source,historical,poll_recorder}.py`; tests `test_historical.py`, `test_producer.py`, `test_poll_recorder.py`, `test_usgs_source.py`.

**Qué decir.** «Automaticé las tres fuentes. El feed devuelve siempre las últimas 24 horas, así que el productor compara `id` y `updated` con un estado persistente y solo publica lo nuevo. El histórico lo bajé por meses y, si un mes llegara al límite de 20.000, lo subdivido en vez de truncar. Guardo qué consulté, cuándo y cuántos registros, y puedo reejecutar sin red.»

**Límites.** No hay reconciliación de eventos eliminados fuera del feed (ampliación; el enunciado lo permite). Si el sistema está parado más de 24 h, el hueco se recupera con el histórico, no con el feed.

---

### 2.2 Calidad — «Completo + acciones» (6 dimensiones)

**Qué hice.** Analicé **las seis dimensiones** con consultas SQL reproducibles, resultados antes/después, decisiones y limitaciones. Todo está generado por `backend/tools/quality.py` (cada cifra sale de la consulta que se muestra junto a ella).

**Antes y después** (medido en una sesión de ~30 min con el feed real):

| Etapa | Medida | Valor |
|---|---|---:|
| Antes (feed bruto) | features recibidas en 26 sondeos | 4.941 |
| Antes | de ellas, no son terremotos (excluidas) | 78 |
| Antes | eventos distintos / versiones distintas | 190 / 197 |
| Después (PostgreSQL) | `current_events` / `event_versions` | 190 / 197 |
| Después | registros en cuarentena | 0 |

**Las seis dimensiones, qué comprobé y qué hice:**

| Dimensión | Comprobación | Resultado | Acción |
|---|---|---|---|
| Completitud | % de magnitud, lugar, profundidad y país nulos | magnitud/lugar/profundidad 0 % nulos; **sin país 16,3 %** (en vivo) y **78,4 %** (histórico) | Conservar nulos; ND en la interfaz; «Sin país asignado» como categoría, no como error |
| Unicidad | pares `(id, updated)` y ids repetidos | 0 y 0; 6 eventos revisados | Clave única + `ON CONFLICT`; el reenvío idéntico se ignora |
| Validez | coordenadas, magnitud, profundidad, fechas futuras, tipo | 0 violaciones en el estado actual | El consumidor rechaza lo inválido **antes** de guardar (cuarentena con motivo) |
| Consistencia | estado actual = versión más reciente; claves de país huérfanas | 0 y 0 | Una versión antigua nunca sustituye a la actual |
| Actualidad | retraso evento→ingesta, ingesta→PostgreSQL, latencia de sondeo | latencia de USGS mediana 104 ms, p95 125 ms | Se muestra «última ingesta» y un aviso a los 15 min |
| Exactitud | contraste independiente: `place` vs. país por polígono | **71,6 %** de coincidencia (1.167 de 1.630 eventos a ≤ 20 km del pueblo) | Documentar: los fallos son costas e islas pequeñas del catálogo de baja resolución |

**Decisiones que defender:** no se imputa 0 a un nulo («desconocido no es cero»); no se atribuye un evento marino al país más cercano; una magnitud o profundidad negativas no se rechazan por serlo; los casos dañados artificialmente de las pruebas están separados e identificados.

**Evidencia.** [docs/calidad.md](docs/calidad.md) (con las consultas y registros de ejemplo), `backend/tools/quality.py`, `backend/observatorio/validation.py`, `test_validation.py`, `test_quarantine.py`.

**Qué decir.** «Mi punto de partida fue ver que el feed repite ~5.000 features para 190 eventos reales. Medí las seis dimensiones con SQL y documenté la acción de cada una. Lo más interesante fue la exactitud: lo contrasté contra el texto de `place` y obtuve un 71,6 %, y expliqué que los fallos vienen del catálogo simplificado, no de un error de lógica.»

**Límites.** La exactitud física de la magnitud no se puede verificar con rangos; el contraste del país es un indicio, no una verdad de referencia.

---

### 2.3 Modelado — «Modelo optimizado»

**Qué hice.** Integré los terremotos con el catálogo de países y diseñé un modelo con grano y claves explícitos, revisiones idempotentes e índices justificados con medidas.

- **Integración geográfica:** punto-en-polígono con **Shapely** (`STRtree` en memoria, coste medio O(log n) por punto). Regla documentada y determinista: el borde cuenta como dentro (`covers`); si coincide con varias entidades gana el menor `ADM0_A3` y se marca `geo_ambiguous`; sin coincidencia → país nulo («Sin país asignado»). Uso `ADM0_A3` (no `ISO_A3`, que vale `-99` en varias entidades).
- **Modelo** (conceptual, lógico y físico en [docs/modelo.md](docs/modelo.md)):

| Tabla | Grano | Clave |
|---|---|---|
| `current_events` | un evento (su versión más reciente) | `event_id` |
| `event_versions` | cada revisión | `(event_id, updated)` |
| `dim_country`, `dim_date` | país / fecha UTC | `country_id` / `date_key` |
| `quarantine_records`, `poll_log`, `poll_exclusions`, `raw_payloads`, `extraction_queries`, `historical_events` | trazabilidad e histórico | ver el documento |
| `replay.*` | copia aislada de las tres tablas de eventos | igual |

- **Revisiones e idempotencia:** el estado actual solo cambia si `EXCLUDED.updated > actual.updated`. Un mensaje repetido no suma (restricción única + `ON CONFLICT`); una versión antigua queda en el historial pero no sustituye a la actual; un conflicto (mismo `(id, updated)` con distinto contenido) va a cuarentena. Escribo en una transacción y confirmo el offset de Kafka **después**, con la lógica de «al menos una vez» del enunciado.
- **Optimización:** las agregaciones salen de `current_events` (cuentan eventos, no mensajes), con índices en `time_utc`, `(country_id, time_utc)` y `mag`. Las medí con y sin índice (ver 2.5).

**Evidencia.** [docs/modelo.md](docs/modelo.md), [docs/diccionario-datos.md](docs/diccionario-datos.md); `backend/observatorio/{geo,persistence}.py`, migraciones `0001`–`0004`; tests `test_geo.py`, `test_persistence.py`, `test_acceptance_gaps.py`, `test_migration.py`.

**Qué decir.** «La clave está en el grano: una fila por evento para analizar y una fila por versión para auditar. Eso hace que reenviar un mensaje o recibir una revisión vieja no cambie los resultados. Para el país uso Shapely con un árbol espacial y una regla explícita para fronteras, y dejo "Sin país asignado" porque muchos terremotos son marinos.»

**Límites.** El catálogo de 110 m no recoge islas pequeñas; con uno de mayor resolución subiría la proporción asignada.

---

### 2.4 Análisis — «Análisis + insights»

**Qué hice.** Ventanas de una hora UTC (por hora del evento), recuentos por país y subregión (incluyendo «Sin país asignado»), distribuciones de magnitud y profundidad con sus nulos contados, y una comparación histórica equivalente (últimas 24 h frente a la media diaria de 2025 con el mismo filtro y 365 días como denominador). Todo se calcula desde el estado actual, con las mismas reglas de filtro que el mapa.

**Tres conclusiones con cifras** (2025, M ≥ 4, mundo; consultas en [docs/analisis.md](docs/analisis.md)):

1. **Una sola secuencia domina el año.** Julio tiene 2.684 eventos frente a una media mensual de 1.525 (+76 %). El 30 de julio hubo 645 eventos, **12,9 veces** la media diaria (50,1), consecuencia del terremoto de Kamchatka M 8,8 del 29 de julio y sus réplicas.
2. **Ley de Gutenberg-Richter.** M≥4: 18.302; M≥5: 2.129; M≥6: 145; M≥7: 16; M≥8: 1. Cada unidad de magnitud divide el número de eventos entre ≈ 9–15 (cerca de 10).
3. **Casi toda la sismicidad M≥4 es marina y superficial.** El 78,4 % no cae en ningún polígono; la mediana de profundidad es 20,9 km y el 74,8 % de los eventos tiene menos de 70 km.

**Insight que da más valor:** la comparación «24 h frente a la media» engaña tras un gran terremoto (conclusión 1), y el recuento por país es una aproximación geográfica, no una medida de peligrosidad. Por eso el panel muestra una nota de «último periodo incompleto».

**Panel (qué se ve):** mapa con tamaño por magnitud y color por profundidad, leyenda, magnitud nula como «ND» (anillo discontinuo), ficha del evento; filtros coherentes (periodo, magnitud mínima, país, subregión); gráficos; tabla ordenable y accesible; estado del sistema y banner de fallo con recuperación automática.

**Evidencia.** [docs/analisis.md](docs/analisis.md); `backend/observatorio/queries.py`; `frontend/src/app/`; tests `test_api.py` y los e2e de `frontend/cypress/e2e/dashboard.cy.ts`.

**Qué decir.** «Tengo tres conclusiones con cifras y filtros, y una advertencia: tras un gran terremoto, comparar las últimas 24 h con una media anual exagera, por eso lo indico en el panel.»

**Límites.** Son estadísticas descriptivas, no predicción ni evaluación de riesgo.

---

### 2.5 Reflexión — «Excelente + propuestas»

**Complejidad (medida, no solo teórica)** — `backend/tools/benchmark.py`, tres tamaños (18.302; 183.020; 1.830.200 filas; las réplicas están marcadas como sintéticas y aisladas fuera del análisis real):

| Operación | Coste | A 1,8 M de filas |
|---|---|---|
| Buscar una versión por id con diccionario | O(1) medio | ≈ 0,04 µs |
| Lo mismo recorriendo una lista | O(n) | ≈ 21 ms |
| PostgreSQL con índice B-tree | O(log n) | ≈ 0,2 ms |
| PostgreSQL sin índice (recorrido secuencial) | O(n) | ≈ 50–90 ms |
| Punto-en-polígono con `STRtree` | O(log n) medio | milisegundos para cientos de polígonos |
| Agregación `GROUP BY` completa | O(n), con o sin índice | ≈ 150 ms |

Razonamiento a **100 millones de filas:** sin índice una búsqueda tardaría varios segundos y el diccionario no cabría en RAM; con índice sigue siendo ≈ milisegundos, pero hay que **particionar por mes**, usar un índice BRIN en el tiempo y **pre-agregar** por hora y país. Detalle en [docs/complejidad.md](docs/complejidad.md).

**Costes** ([docs/costes.md](docs/costes.md)): toda la pila ocupa ≈ 0,85 GiB de RAM en reposo (Kafka la mitad); la base completa pesa ≈ 14 MB; lo que más crece son los payloads originales (≈ 46 MB/día si todos difirieran), por eso tienen retención de 7 días y deduplicación por hash. Una cuota gratuita (ngrok/Netlify) no equivale a coste cero: se consideran electricidad, mantenimiento y tiempo de desarrollo.

**Fiabilidad probada:** PostgreSQL caído → la API devuelve 503 con `Retry-After`, el productor sigue publicando y todo se recupera solo; Kafka caído → reintentos sin marcar como publicado; túnel caído → el panel conserva la última lectura y avisa.

**Limitaciones** (las asumo explícitamente): catálogo de baja resolución; sin reconciliación de eventos retirados del catálogo; datos del feed sujetos a revisiones tardías; el panel solo funciona con el equipo, Docker y el túnel encendidos (lo pide el enunciado); mediciones de una sola máquina de desarrollo.

**Propuestas de mejora:** catálogo de mayor resolución (50 m) para recuperar costas e islas; tabla de agregados por hora y país con refresco incremental; particionado mensual; caché con `ETag` en la API; reconciliar eventos eliminados con consultas periódicas al catálogo; alertas cuando la ingesta se retrasa.

**Qué decir.** «Medí en tres tamaños y vi la diferencia entre O(1), O(log n) y O(n). Lo que más aprendí: un índice acelera las búsquedas, pero una agregación completa sigue siendo lineal. A 100 millones de filas haría particiones y pre-agregados sin añadir infraestructura nueva.»

---

## 3. Pruebas de aceptación del enunciado (las 11)

Matriz completa con pasos, resultado esperado, resultado observado y evidencia en [docs/aceptacion.md](docs/aceptacion.md). Resumen: evento nuevo, mismo mensaje repetido, versión posterior, versión antigua después, magnitud nula, coordenadas inválidas, evento marítimo, reinicio del consumidor, túnel cerrado, túnel reabierto y reproducción histórica. **Las 11 están cubiertas** por tests automáticos (114 de backend con PostgreSQL real, 6 unitarios y 9 e2e del frontend) y por la demostración real con Kafka y ngrok.

---

## 4. Arrancar todo

```bash
cp .env.example .env            # en PowerShell: Copy-Item .env.example .env
# edita en .env: POSTGRES_PASSWORD, CORS_ALLOWED_ORIGINS (+ origen de Netlify), NGROK_AUTHTOKEN
docker compose --profile tunnel up --build -d
docker compose --profile tunnel ps          # todo "healthy"
curl http://127.0.0.1:4040/api/tunnels      # URL pública HTTPS (ponla en frontend/public/config.json)
curl http://127.0.0.1:8000/api/salud
```

Histórico 2025 (una vez; reutiliza ficheros si ya existen):

```bash
docker compose run --rm -v "<ruta-absoluta>/backend/data:/app/data" producer \
  python -m observatorio.historical --year 2025
```

Pruebas:

```bash
cd backend && python -m unittest discover -s tests -t tests     # 114 tests (PostgreSQL real si hay POSTGRES_*)
cd frontend && npm test                                          # sondeo y filtros
npm start & npx cypress run                                      # e2e (si falla: unset ELECTRON_RUN_AS_NODE)
```

Panel en local: `cd frontend && npm install && npm start` → <http://localhost:4200>.

**Publicar en Netlify:** el `netlify.toml` de la raíz ya fija base `frontend`, `npm ci && npm run build` y `dist/observatorio/browser`. No definas variables de entorno del backend en Netlify. Añade el origen exacto de tu sitio a `CORS_ALLOWED_ORIGINS`, reinicia la API (`docker compose up -d api`) y asegúrate de que `config.json` lleva la URL HTTPS vigente del túnel.

**Seguridad:** el token de ngrok y la contraseña de la base solo viven en `.env` (ignorado por Git). Kafka y PostgreSQL no se publican; la API solo expone `/api/eventos`, `/api/estadisticas` y `/api/salud`.

---

## 5. Guion de demostración (≈ 5 min)

1. **En vivo:** abre el panel de Netlify; muestra «Operativo», mapa, gráficos y tabla. Cambia «Magnitud mín.» a 5: mapa, recuento, gráficos y tabla cambian a la vez. Pulsa una fila: se resalta en el mapa.
2. **Reproducción** (≈ 35 s):
   ```bash
   docker compose run --rm producer python -m observatorio.replay \
     --from 2025-03-28T06:00:00Z --to 2025-03-28T12:00:00Z --speed 600
   ```
   Elige «Datos → Reproducción»: aparece **REPRODUCCIÓN**, 23 eventos únicos (incluye un duplicado y una revisión antigua controlados) y los datos en vivo no cambian.
3. **Caída y vuelta del túnel:** `docker compose stop ngrok` → banner de fallo conservando la última lectura; `docker compose start ngrok` → se recupera solo.
4. **Idempotencia:** muestra los tests `test_acceptance_gaps.py` (versión antigua, nulo, reinicio) o la consulta SQL de `calidad.md` (0 duplicados).

---

## 6. Capturas recomendadas (para la memoria y la defensa)

Guárdalas en `docs/capturas/` con estos nombres:

| Archivo | Qué captura | Para qué criterio |
|---|---|---|
| `01-compose-ps.png` | `docker compose --profile tunnel ps` con todo `healthy` | Arquitectura |
| `02-panel-vivo.png` | Panel completo en vivo (mapa, KPIs, estado «Operativo») | Análisis |
| `03-filtro-antes.png` / `04-filtro-despues.png` | Panel sin filtro y con magnitud mín. 5 | Análisis (filtros coherentes) |
| `05-graficos.png` | Pestañas «Por hora», «Por lugar» y «Distribuciones» | Análisis |
| `06-tabla-nd.png` | Tabla con una fila de magnitud «ND» y otra «Sin país asignado» | Calidad / Modelado |
| `07-ficha-evento.png` | Evento seleccionado con su ficha | Análisis |
| `08-historico.png` | Salida de `observatorio.historical` (18.302 eventos, 12 consultas) | Extracción |
| `09-sql-calidad.png` | Resultado de `tools/quality.py` (antes/después) | Calidad |
| `10-sql-modelo.png` | `\d observatorio.current_events` y `\di` (claves e índices) | Modelado |
| `11-explain.png` | `EXPLAIN` con y sin índice (salida de `benchmark.py`) | Reflexión |
| `12-replay.png` | Panel con la etiqueta REPRODUCCIÓN | Pruebas de aceptación |
| `13-banner-fallo.png` / `14-recuperado.png` | Banner con el túnel cerrado y tras reabrirlo | Pruebas de aceptación |
| `15-ngrok-4040.png` | Interfaz de ngrok con la URL pública (tapa el token) | Despliegue |
| `16-netlify-deploy.png` | Despliegue correcto en Netlify | Despliegue |
| `17-tests.png` | Salida de los 114 tests en verde | Todas |

---

## 7. Mapa del repositorio

```
backend/observatorio/   producer, consumer, geo, validation, persistence, api, queries, historical, replay, migrations/
backend/tools/          quality.py (calidad), benchmark.py (complejidad)
backend/tests/          114 tests (unitarios e integración con PostgreSQL)
frontend/src/app/       panel Angular: mapa, gráficos SVG, tabla, servicio de API con sondeo serializado
frontend/cypress/e2e/   pruebas e2e (API simulada y túnel real)
docs/                   diccionario, procedencia, calidad, modelo, complejidad, costes, análisis, aceptación
compose.yaml            los cinco servicios (+ perfil tunnel); netlify.toml (raíz)
openspec/               especificaciones y tareas del proyecto (43/43 completadas)
```
