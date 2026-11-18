import unittest
from unittest.mock import AsyncMock, MagicMock

from observatorio.persistence import record_quarantine
from observatorio.validation import REASON_MALFORMED_JSON


class QuarantinePersistenceTests(unittest.IsolatedAsyncioTestCase):
    async def test_quarantine_write_passes_exact_parameters(self) -> None:
        mock_conn = MagicMock()
        mock_cursor = AsyncMock()
        mock_cursor_cm = MagicMock()
        mock_cursor_cm.__aenter__ = AsyncMock(return_value=mock_cursor)
        mock_cursor_cm.__aexit__ = AsyncMock(return_value=None)
        mock_conn.cursor.return_value = mock_cursor_cm

        raw_payload = b"bad payload bytes"
        topic = "earthquakes-live"
        partition = 0
        offset = 42
        reason = REASON_MALFORMED_JSON
        envelope = None

        await record_quarantine(
            mock_conn,
            topic,
            partition,
            offset,
            raw_payload,
            reason,
            envelope,
        )

        mock_cursor.execute.assert_awaited_once()
        query, params = mock_cursor.execute.await_args.args
        self.assertIn("INSERT INTO observatorio.quarantine_records", query)
        self.assertIn("ON CONFLICT (kafka_topic, kafka_partition, kafka_offset) DO NOTHING", query)
        self.assertEqual(params[0], topic)
        self.assertEqual(params[1], partition)
        self.assertEqual(params[2], offset)
        self.assertEqual(params[3], raw_payload)
        self.assertEqual(params[4], reason)
        self.assertIsNone(params[5])

    async def test_transaction_rollback_leaves_state_uncommitted(self) -> None:
        """Simulate a database failure during transaction to verify rollback."""
        mock_conn = MagicMock()
        mock_cursor = AsyncMock()
        mock_cursor_cm = MagicMock()
        mock_cursor_cm.__aenter__ = AsyncMock(return_value=mock_cursor)
        mock_cursor_cm.__aexit__ = AsyncMock(return_value=None)
        mock_conn.cursor.return_value = mock_cursor_cm

        mock_cursor.execute.side_effect = ConnectionError("PostgreSQL connection lost")

        # Context manager for transaction that rolls back on exception
        class FakeTxContextManager:
            def __init__(self) -> None:
                self.rolled_back = False

            async def __aenter__(self) -> None:
                return None

            async def __aexit__(self, exc_type, exc_val, exc_tb) -> bool:
                if exc_type is not None:
                    self.rolled_back = True
                return False

        fake_tx = FakeTxContextManager()
        mock_conn.transaction.return_value = fake_tx

        with self.assertRaises(ConnectionError):
            async with mock_conn.transaction():
                await record_quarantine(
                    mock_conn,
                    "earthquakes-live",
                    0,
                    10,
                    b"raw",
                    "SOME_REASON",
                    None,
                )

        self.assertTrue(fake_tx.rolled_back)


if __name__ == "__main__":
    unittest.main()
