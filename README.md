# Observatorio de actividad sísmica

Plataforma de ingesta, procesamiento, análisis y visualización de terremotos con datos de USGS: **Kafka → consumidor → PostgreSQL → API REST → panel Angular + Leaflet**.

## Arquitectura

Cinco servicios Compose permanentes (no se añade más infraestructura):

| Servicio | Función |
|---|---|
| `producer` | Sondea el feed `all_day.geojson` de USGS cada 60 s, publica en `earthquakes-live` y registra cada sondeo, sus exclusiones y el GeoJSON original en PostgreSQL. |
| `kafka` | Bus de mensajes (topics `earthquakes-live` y `earthquakes-replay`). |
| `consumer` | Valida, enriquece con país (Shapely, punto en polígono) y persiste versiones y estado actual; cuarentena para anomalías. |
| `postgres` | Esquema `observatorio` (en vivo) y esquema aislado `replay`. |
| `api` | FastAPI de solo lectura: `/api/eventos`, `/api/estadisticas`, `/api/salud`. |

Opcional: perfil `tunnel` con `ngrok` para publicar la API por HTTPS. Comandos puntuales (misma imagen): `observatorio.historical` y `observatorio.replay`.

Documentación y evidencias en [docs/](docs/): `diccionario-datos.md`, `procedencia.md`, `aceptacion.md`.

## 1. Arranque

```bash
cp .env.example .env          # en PowerShell: Copy-Item .env.example .env
# edita POSTGRES_PASSWORD en .env
docker compose up --build -d
docker compose ps             # espera a que los cinco servicios estén "healthy"
curl http://127.0.0.1:8000/api/salud
```

Con la base vacía, el consumidor aplica las migraciones y carga los 177 países. La API queda solo en `127.0.0.1:8000`.

> Si ya existe un volumen `postgres_data` creado con otra contraseña, PostgreSQL rechazará las conexiones. Usa la contraseña original o recrea el volumen con `docker compose down -v` (borra los datos).

Panel en local:

```bash
cd frontend
npm install
npm start                     # http://localhost:4200 ; usa public/config.json
```

Pruebas:

```bash
# backend (sin pytest; opcionalmente con una instancia de PostgreSQL y las variables POSTGRES_*)
cd backend && python -m unittest discover -s tests -t tests
# frontend
cd frontend && npm test                      # sondeo y filtros (node:test)
npm start &  &&  npx cypress run             # e2e (si falla, ejecuta antes: unset ELECTRON_RUN_AS_NODE)
```

## 2. Histórico 2025 (una sola vez)

Descarga M ≥ 4 de 2025 por meses (biseca si un mes llega a 20.000), guarda los ficheros en `backend/data/historical/` (ignorado por Git) y los carga:

```bash
docker compose run --rm -v "<ruta-absoluta-del-repo>/backend/data:/app/data" producer \
  python -m observatorio.historical --year 2025
```

Una repetición reutiliza los ficheros sin red (`--refresh` fuerza nueva descarga). Resultados y procedencia en [docs/procedencia.md](docs/procedencia.md).

## 3. Túnel público y Netlify

1. Crea una cuenta en ngrok y copia tu *authtoken*. Ponlo **solo** en tu `.env` local (`NGROK_AUTHTOKEN=`); nunca en Git.
2. Arranca el túnel: `docker compose --profile tunnel up -d`. La URL HTTPS aparece en <http://127.0.0.1:4040> (o fija `NGROK_URL`).
3. Añade el origen exacto de tu sitio Netlify a `CORS_ALLOWED_ORIGINS` en `.env` (separados por comas, sin `*`) y reinicia la API: `docker compose up -d api`.
4. Edita `frontend/public/config.json` con la URL HTTPS del túnel:
   ```json
   { "apiUrl": "https://TU-DOMINIO.ngrok-free.app", "refreshMs": 60000, "skipNgrokWarning": true }
   ```
5. En Netlify: *base directory* `frontend`, *build command* `npm run build`, *publish directory* `frontend/dist/observatorio/browser`. (`public/_redirects` ya contiene la regla SPA.)

El panel envía `ngrok-skip-browser-warning` y la API lo admite en CORS.

## 4. Procedimiento de demostración

1. **En vivo:** abre el panel; verifica mapa, gráficos, tabla y panel de estado (última ingesta, periodo). Cambia «Magnitud mínima» a 5: mapa, recuento, gráficos y tabla cambian a la vez.
2. **Reproducción** (≈ 35 s):
   ```bash
   docker compose run --rm producer python -m observatorio.replay \
     --from 2025-03-28T06:00:00Z --to 2025-03-28T12:00:00Z --speed 600
   ```
   En el panel elige «Datos → Reproducción»: aparece la etiqueta **REPRODUCCIÓN**, 23 eventos únicos (incluye un duplicado y una revisión antigua controlados) y los datos en vivo no cambian.
3. **Caída y vuelta del túnel:** `docker compose stop ngrok` → en ≤ 60 s aparece el banner de fallo conservando la última lectura con su hora; `docker compose start ngrok` → el banner desaparece solo en el siguiente sondeo.
4. **Caída de PostgreSQL:** `docker compose stop postgres` → la API responde 503 explícito y el productor sigue publicando; `docker compose start postgres` → todo se recupera sin intervención.

## API

| Ruta | Descripción |
|---|---|
| `GET /api/eventos` | GeoJSON del estado actual. Filtros: `start`, `end` (UTC, fin exclusivo), `min_mag`, `country_id` (`ADM0_A3` o `SIN_PAIS`), `subregion`, `mode=live\|replay`; sin filtros de fecha devuelve las últimas 24 h. Paginación `limit` (por defecto 2000, máx. 10000) y `offset`. Sigue `docs/CONTRATO-API.md`: `metadata` con `generated`, `last_ingestion` (`replay_loaded_at` en reproducción), `mode`, `count`, `truncated`, `total` y `null_magnitude_excluded` (eventos sin magnitud que no cumplen `min_mag`); fechas en ms Unix UTC; `country_name` nulo = «Sin país asignado». |
| `GET /api/estadisticas` | Total, por país y subregión («Sin país asignado» incluido), ventanas horarias UTC con horas vacías, distribuciones de magnitud y profundidad con `missing`, y comparación 24 h frente a la media diaria de 2025 (365 días). |
| `GET /api/salud` | Última ingesta, periodo cubierto, último sondeo; con `mode=replay`, solo `replay_loaded_at`. |

Filtros mal formados → HTTP 422; `country_id` desconocido → resultado vacío válido; PostgreSQL caído → HTTP 503 con `Retry-After`. No hay WebSocket ni rutas de administración.
