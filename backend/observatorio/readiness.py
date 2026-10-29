import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import TypeVar


Connection = TypeVar("Connection")


async def retry_until_ready(
    service_name: str,
    connect: Callable[[], Awaitable[Connection]],
    retry_seconds: float = 2,
) -> Connection:
    while True:
        try:
            connection = await connect()
        except Exception as error:
            logging.warning(
                "%s is not ready (%s); retrying in %s seconds.",
                service_name,
                error,
                retry_seconds,
            )
            await asyncio.sleep(retry_seconds)
        else:
            logging.info("%s connection is ready.", service_name)
            return connection
