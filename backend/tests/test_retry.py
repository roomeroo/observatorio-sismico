import unittest

from observatorio.retry import retry_with_backoff


class RetryPolicyTests(unittest.IsolatedAsyncioTestCase):
    async def test_retries_three_times_with_progressive_delays(self) -> None:
        attempts = 0
        delays: list[float] = []

        async def operation() -> str:
            nonlocal attempts
            attempts += 1
            if attempts < 3:
                raise ConnectionError("temporary failure")
            return "acknowledged"

        async def fake_sleep(seconds: float) -> None:
            delays.append(seconds)

        result = await retry_with_backoff(
            operation,
            "test operation",
            (ConnectionError,),
            fake_sleep,
        )

        self.assertEqual(result, "acknowledged")
        self.assertEqual(attempts, 3)
        self.assertEqual(delays, [20.0, 40.0])


if __name__ == "__main__":
    unittest.main()
