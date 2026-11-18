# Tasks

## 1. Limpieza y base (fase 0)

- [x] 1.1 Copiar enunciado y `CONTRATO-API.md` aportados a `docs/` y verificar que las rutas citadas en las specs existen
- [x] 1.2 Eliminar `backend/src/`, `backend/observatorio/src/` y el reexport `websocket.py`; `pytest backend/tests` sigue pasando
- [x] 1.3 Unificar o borrar `websocket_test.py`/`test_websocket.py` (se retiran con el WebSocket en 5.x); no quedan imports rotos (`python -c "import observatorio.api"`)
- [x] 1.4 Añadir `shapely` fijado a `requirements.txt` y verificar que `docker compose build` termina
- [x] 1.5 Migración `0003` aditiva (columnas de país, `dim_country`, `dim_date`, `poll_log`, `poll_exclusions`, `raw_payloads`, `historical_events`, `extraction_queries`, índices); unificar con `postgres/init`; test de migración sobre base vacía y repetida

## 2. Integración geográfica

- [x] 2.1 Módulo `geo`: carga del catálogo, comprobación de unicidad de `ADM0_A3`, `STRtree`, regla `covers` + menor `ADM0_A3` + bandera; tests con puntos interior, océano, frontera y doble coincidencia
- [x] 2.2 Cargar `dim_country` al arrancar el consumidor; test de idempotencia al reiniciar
- [x] 2.3 Enriquecer en `persist_accepted_event` y poblar `dim_date`; test: evento marítimo queda con `country_id` nulo y permanece en `current_events`
- [x] 2.4 Documentar la regla y el aviso de exactitud en `docs/diccionario-datos.md`

## 3. Registro del productor

- [x] 3.1 Persistir `poll_log` (estado, latencia, recuento, error) y exclusiones con motivo; tests con feed que incluye `quarry blast`
- [x] 3.2 Guardar el GeoJSON original deduplicado por hash y tarea de retención; tests de hash idéntico y de borrado por retención
- [x] 3.3 Tolerar fallo de PostgreSQL sin detener la publicación; test con base caída
- [x] 3.4 Verificar con `docker compose up --build -d` que las filas aparecen tras un sondeo real

## 4. Histórico 2025

- [x] 4.1 Comando `observatorio.historical` con descarga mensual, bisección en 20.000 y deduplicación; tests con respuestas simuladas (mes normal, mes saturado, evento en frontera)
- [x] 4.2 Registro en `extraction_queries`, ficheros git-ignored y reutilización offline; test sin red
- [x] 4.3 Ejecutar la descarga real una vez y anotar recuentos en `docs/procedencia.md`; verificar `SELECT count(*)` frente al manifiesto

## 5. API REST

- [x] 5.1 Pool con reintento y errores 503 explícitos; test con PostgreSQL parado
- [x] 5.2 `/api/eventos` (GeoJSON, filtros, `limit/offset`, `total`, metadatos `generated`/`last_ingestion`); tests incluidos nulos y 422
- [x] 5.3 `/api/estadisticas`: por país/subregión, ventanas horarias con horas vacías, distribuciones con `missing`, comparación 24 h vs media 2025; test: una revisión no infla recuentos
- [x] 5.4 `/api/salud` con última ingesta y periodo; test de que no expone credenciales
- [x] 5.5 CORS por `CORS_ALLOWED_ORIGINS`, `OPTIONS`, cabecera `ngrok-skip-browser-warning`; tests de origen permitido y no permitido
- [x] 5.6 Retirar WebSocket y `POST` de broadcast; test de 404 y borrado de tests/Cypress asociados

## 6. Reproducción

- [x] 6.1 Consumidor con selección de esquema por topic y esquema `replay`; test de aislamiento (recuentos live intactos)
- [x] 6.2 Comando `observatorio.replay` con intervalo, factor de velocidad, duplicado y revisión antigua controlados; test de orden y de recuento final
- [x] 6.3 Parámetro `mode=replay` en la API con `replay_loaded_at`; test de que `last_ingestion` live no cambia
- [x] 6.4 Demostrar con Kafka real y registrar la evidencia en `docs/aceptacion.md`

## 7. Panel Angular

- [x] 7.1 `ApiService` con sondeo de 60 s sin solapamiento, `config.json` y estado de filtros; test unitario del sondeo y de la recuperación
- [x] 7.2 Mapa con tamaño por magnitud, color por profundidad, leyenda, ND y ficha; sin duplicar marcadores por revisión
- [x] 7.3 Gráficos SVG: ventanas horarias, recuentos por país con "Sin país asignado", distribuciones con nulos
- [x] 7.4 Filtros coherentes entre mapa, gráficos, recuento y tabla consultable; prueba e2e de que un filtro afecta a todas las vistas
- [x] 7.5 Panel de estado, banner de fallo con última lectura y recuperación automática; prueba e2e cerrando y reabriendo la API simulada
- [x] 7.6 Modo REPRODUCCIÓN visible; `ng build` produce el SPA sin errores y `config.json` apunta a la URL HTTPS

## 8. Despliegue

- [x] 8.1 Perfil `tunnel` con ngrok, variables CORS y topic de replay en `compose.yaml`; verificar que `docker compose config` lista solo cinco servicios sin perfil
- [x] 8.2 Ampliar `.env.example` sin secretos y comprobar con búsqueda que no hay token en Git ni en `dist/`
- [x] 8.3 Reescribir `README.md` con arranque, túnel, Netlify y procedimiento de demostración; ejecutar los comandos tal como están escritos

## 9. Evidencias de evaluación

- [x] 9.1 Script y apartado de calidad (6 dimensiones, antes/después, registros de ejemplo) en `docs/calidad.md`; las consultas reproducen las cifras
- [x] 9.2 Modelos conceptual/lógico/físico, SQL e índices en `docs/modelo.md`
- [x] 9.3 Benchmark con tres tamaños (diccionario vs scan, con/sin índice, tiempo y memoria, datos sintéticos marcados) en `docs/complejidad.md`
- [x] 9.4 Costes, escalado y razonamiento a 100 millones de filas en `docs/costes.md`
- [x] 9.5 Al menos tres conclusiones con cifras, filtros y periodo en `docs/analisis.md`
- [x] 9.6 Matriz de las 11 pruebas de aceptación con evidencias; añadir los tests que falten (versión antigua, marítimo, magnitud nula, reinicio del consumidor) y verificar que pasan

## 10. Integración final

- [x] 10.1 Ejecutar la demostración completa (live + replay + caída y vuelta del túnel) y comprobar las 11 pruebas
- [x] 10.2 `pytest` completo, `ng build` y `docker compose up --build -d` desde clon limpio
