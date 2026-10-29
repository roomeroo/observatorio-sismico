from contextlib import asynccontextmanager
import logging

from fastapi import FastAPI
from psycopg import AsyncConnection

from observatorio.database import postgres_connection_parameters
from observatorio.readiness import retry_until_ready


@asynccontextmanager
async def lifespan(app: FastAPI):
    logging.basicConfig(level=logging.INFO)
    connection = await retry_until_ready(
        "API PostgreSQL",
        lambda: AsyncConnection.connect(
            **postgres_connection_parameters(),
            connect_timeout=3,
        ),
    )
    app.state.database_connection = connection
    try:
        yield
    finally:
        await connection.close()


app = FastAPI(title="Observatorio de actividad sísmica", lifespan=lifespan)
