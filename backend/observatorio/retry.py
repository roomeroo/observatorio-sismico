import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import TypeVar


Result = TypeVar("Result")
MAX_ATTEMPTS = 3
RETRY_DELAYS_SECONDS = (20.0, 40.0)


async def retry_with_backoff(
    operation: Callable[[], Awaitable[Result]],
    operation_name: str,
    retryable_errors: tuple[type[Exception], ...],
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    should_retry: Callable[[Exception], bool] | None = None,
) -> Result:
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            return await operation()
        except retryable_errors as error:
            retry_allowed = should_retry is None or should_retry(error)
            if not retry_allowed or attempt == MAX_ATTEMPTS:
                logging.error(
                    "%s failed after attempt %s/%s: %s",
                    operation_name,
                    attempt,
                    MAX_ATTEMPTS,
                    error,
                )
                raise

            delay = RETRY_DELAYS_SECONDS[attempt - 1]
            logging.warning(
                "%s failed on attempt %s/%s (%s); retrying in %s seconds.",
                operation_name,
                attempt,
                MAX_ATTEMPTS,
                error,
                delay,
            )
            await sleep(delay)

    raise RuntimeError("Retry loop terminated without a result")
