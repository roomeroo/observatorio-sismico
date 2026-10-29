import asyncio
import unittest
from unittest.mock import patch

from observatorio.readiness import retry_until_ready


class RetryUntilReadyTests(unittest.IsolatedAsyncioTestCase):
    async def test_retries_after_connection_failure(self) -> None:
        attempts = 0

        async def connect() -> str:
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise ConnectionError("dependency not ready")
            return "connected"

        async def no_wait(_: float) -> None:
            return None

        with patch("observatorio.readiness.asyncio.sleep", new=no_wait):
            result = await retry_until_ready("test service", connect, 0)

        self.assertEqual(result, "connected")
        self.assertEqual(attempts, 2)


if __name__ == "__main__":
    unittest.main()
