import dataclasses
import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import Annotated, Literal, Optional

import psycopg
from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from psycopg.conninfo import make_conninfo
from psycopg_pool import AsyncConnectionPool, PoolTimeout

from observatorio import queries
from observatorio.database import postgres_connection_parameters

logger = logging.getLogger(__name__)

DEFAULT_ORIGINS = "http://localhost:4200"
DEFAULT_LIMIT = 2000  # documented maximum of points per response unless `limit` is given
MAX_LIMIT = 10000


def allowed_origins() -> list[str]:
    raw = os.environ.get("CORS_ALLOWED_ORIGINS", DEFAULT_ORIGINS)
    return [o.strip().rstrip("/") for o in raw.split(",") if o.strip() and o.strip() != "*"]


def create_pool() -> AsyncConnectionPool:
    return AsyncConnectionPool(
        make_conninfo("", **postgres_connection_parameters(), connect_timeout=3),
        min_size=1,
        max_size=5,
        open=False,
        timeout=3,
        reconnect_timeout=5,
        check=AsyncConnectionPool.check_connection,
        kwargs={"autocommit": True},
        name="api-pool",
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    logging.basicConfig(level=logging.INFO)
    pool = create_pool()
    # Do not block start-up on PostgreSQL: requests answer 503 until it is reachable.
    await pool.open(wait=False)
    app.state.pool = pool
    try:
        yield
    finally:
        await pool.close()


app = FastAPI(title="Observatorio de actividad sísmica", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins(),
    allow_methods=["GET", "OPTIONS"],
    allow_headers=["ngrok-skip-browser-warning", "content-type"],
    allow_credentials=False,
)


@app.exception_handler(psycopg.OperationalError)
@app.exception_handler(PoolTimeout)
async def database_unavailable(request: Request, exc: Exception) -> JSONResponse:
    logger.error("Database unavailable: %s", type(exc).__name__)
    return JSONResponse(
        status_code=503,
        content={"detail": "La base de datos no está disponible. Reintenta en unos segundos."},
        headers={"Retry-After": "5"},
    )


@app.exception_handler(queries.FilterError)
async def invalid_filters(request: Request, exc: queries.FilterError) -> JSONResponse:
    return JSONResponse(status_code=422, content={"detail": str(exc)})


async def get_connection(request: Request):
    async with request.app.state.pool.connection() as conn:
        yield conn


Conn = Annotated[psycopg.AsyncConnection, Depends(get_connection)]


def _aware(value: Optional[datetime]) -> Optional[datetime]:
    if value is not None and value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def get_filters(
    start: Optional[datetime] = Query(None, description="Inicio (UTC, inclusive)"),
    end: Optional[datetime] = Query(None, description="Fin (UTC, exclusivo)"),
    min_mag: Optional[float] = Query(None, ge=-10, le=10),
    country_id: Optional[str] = Query(None, min_length=1, max_length=16, description="ADM0_A3 o SIN_PAIS"),
    subregion: Optional[str] = Query(None, min_length=1, max_length=64),
    mode: Literal["live", "replay"] = "live",
) -> queries.Filters:
    start, end = _aware(start), _aware(end)
    if start is not None and end is not None and end <= start:
        raise queries.FilterError("end must be later than start")
    return queries.Filters(start, end, min_mag, country_id, subregion, mode)


Filters = Annotated[queries.Filters, Depends(get_filters)]


@app.get("/api/eventos")
async def eventos(
    conn: Conn,
    filters: Filters,
    limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    offset: int = Query(0, ge=0),
):
    now = datetime.now(timezone.utc)
    if filters.start is None and filters.end is None:  # contract: last 24 hours by default
        filters = dataclasses.replace(filters, start=now - timedelta(hours=24), end=now)
    page = await queries.events_page(conn, filters, limit, offset)
    ingestion = await queries.last_ingestion(conn, filters)
    count = len(page["features"])
    return {
        "type": "FeatureCollection",
        "metadata": {
            "generated": queries._ms(now),
            **queries.freshness(filters, ingestion),
            "mode": filters.mode,
            "count": count,
            "truncated": offset + count < page["total"],
            "total": page["total"],
            "limit": limit,
            "offset": offset,
            "unit": "eventos (terremotos en su versión actual)",
            "period": {"start": queries._iso(filters.start), "end": queries._iso(filters.end)},
            "null_magnitude_excluded": page["null_magnitude_excluded"],
        },
        "features": page["features"],
    }


@app.get("/api/estadisticas")
async def estadisticas(conn: Conn, filters: Filters):
    result = await queries.statistics(conn, filters)
    result["generated"] = queries._ms(datetime.now(timezone.utc))
    return result


@app.get("/api/salud")
async def salud(conn: Conn, mode: Literal["live", "replay"] = "live"):
    if mode == "replay":
        data = await queries.replay_health(conn)
        return {
            "status": "ok",
            "database": "up",
            "mode": "replay",
            "generated": queries._ms(datetime.now(timezone.utc)),
            **data,
        }
    data = await queries.health(conn)
    return {
        "status": "ok",
        "database": "up",
        "generated": queries._ms(datetime.now(timezone.utc)),
        **data,
    }
