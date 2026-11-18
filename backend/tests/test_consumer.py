import asyncio
from dataclasses import dataclass
import json
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from aiokafka import TopicPartition

from observatorio.consumer import process_single_record, run_consumer


@dataclass
class FakeMessage:
    topic: str
    partition: int
    offset: int
    value: bytes


class ConsumerPipelineTests(unittest.IsolatedAsyncioTestCase):
    @staticmethod
    def valid_message(offset: int = 10) -> FakeMessage:
        payload = {
            "source": "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/all_day.geojson",
            "ingested_at": 1700000000000,
            "mode": "live",
            "event": {
                "type": "Feature",
                "id": "quake-order-test",
                "geometry": {"type": "Point", "coordinates": [-120.0, 35.0, 5.0]},
                "properties": {
                    "type": "earthquake",
                    "time": 1700000000000,
                    "updated": 1700000010000,
                    "mag": 2.5,
                },
            },
        }
        return FakeMessage(
            topic="earthquakes-live",
            partition=0,
            offset=offset,
            value=json.dumps(payload).encode("utf-8"),
        )

    async def test_db_commit_strictly_precedes_kafka_offset_commit(self) -> None:
        call_order: list[str] = []

        mock_conn = MagicMock()
        mock_conn.close = AsyncMock()
        mock_cursor = AsyncMock()
        mock_cursor.fetchone.return_value = None

        mock_cursor_cm = MagicMock()
        mock_cursor_cm.__aenter__ = AsyncMock(return_value=mock_cursor)
        mock_cursor_cm.__aexit__ = AsyncMock(return_value=None)
        mock_conn.cursor.return_value = mock_cursor_cm

        class TrackedTx:
            async def __aenter__(self) -> None:
                call_order.append("db_tx_start")
                return None

            async def __aexit__(self, exc_type, exc_val, exc_tb) -> bool:
                if exc_type is None:
                    call_order.append("db_tx_commit")
                return False

        mock_conn.transaction.return_value = TrackedTx()

        mock_consumer = MagicMock()
        mock_consumer.subscribe = MagicMock()

        msg = self.valid_message(offset=5)
        # return msg once then wait for stop
        stop_event = asyncio.Event()

        async def fake_getone() -> FakeMessage:
            if not stop_event.is_set():
                return msg
            await asyncio.sleep(10)
            raise asyncio.CancelledError()

        mock_consumer.getone = AsyncMock(side_effect=fake_getone)

        async def fake_commit(offsets: dict[TopicPartition, int]) -> None:
            call_order.append("kafka_commit")
            stop_event.set()

        mock_consumer.commit = AsyncMock(side_effect=fake_commit)

        async def fake_connect_pg() -> MagicMock:
            return mock_conn

        with patch("observatorio.consumer.apply_migrations", new=AsyncMock(return_value=[])), patch(
            "observatorio.consumer.load_dim_country", new=AsyncMock(return_value=0)
        ):
            await run_consumer(
                consumer=mock_consumer,
                connect_pg=fake_connect_pg,
                topic="earthquakes-live",
                stop_event=stop_event,
            )

        self.assertEqual(
            call_order,
            ["db_tx_start", "db_tx_commit", "kafka_commit"],
        )
        mock_consumer.commit.assert_awaited_once_with(
            {TopicPartition("earthquakes-live", 0): 6}
        )

    async def test_postgres_failure_does_not_commit_kafka_and_reconnects(self) -> None:
        attempts = 0
        committed_offsets: list[dict] = []

        mock_consumer = MagicMock()
        mock_consumer.subscribe = MagicMock()

        msg = self.valid_message(offset=10)
        stop_event = asyncio.Event()

        mock_consumer.getone = AsyncMock(return_value=msg)

        async def fake_commit(offsets: dict[TopicPartition, int]) -> None:
            committed_offsets.append(offsets)
            stop_event.set()

        mock_consumer.commit = AsyncMock(side_effect=fake_commit)

        # Connection 1 fails inside transaction, Connection 2 succeeds
        mock_conn1 = MagicMock()
        mock_conn1.close = AsyncMock()
        mock_cursor1 = AsyncMock()
        mock_cursor1.fetchone.return_value = None
        mock_cursor1.execute.side_effect = ConnectionError("DB died")
        mock_cursor_cm1 = MagicMock()
        mock_cursor_cm1.__aenter__ = AsyncMock(return_value=mock_cursor1)
        mock_cursor_cm1.__aexit__ = AsyncMock(return_value=None)
        mock_conn1.cursor.return_value = mock_cursor_cm1
        mock_conn1.transaction.return_value = MagicMock(
            __aenter__=AsyncMock(return_value=None),
            __aexit__=AsyncMock(return_value=False),
        )

        mock_conn2 = MagicMock()
        mock_conn2.close = AsyncMock()
        mock_cursor2 = AsyncMock()
        mock_cursor2.fetchone.return_value = None
        mock_cursor2.execute.return_value = None
        mock_cursor_cm2 = MagicMock()
        mock_cursor_cm2.__aenter__ = AsyncMock(return_value=mock_cursor2)
        mock_cursor_cm2.__aexit__ = AsyncMock(return_value=None)
        mock_conn2.cursor.return_value = mock_cursor_cm2
        mock_conn2.transaction.return_value = MagicMock(
            __aenter__=AsyncMock(return_value=None),
            __aexit__=AsyncMock(return_value=False),
        )

        async def fake_connect_pg() -> MagicMock:
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                return mock_conn1
            return mock_conn2

        with patch("observatorio.consumer.apply_migrations", new=AsyncMock(return_value=[])), patch(
            "observatorio.consumer.load_dim_country", new=AsyncMock(return_value=0)
        ):
            await run_consumer(
                consumer=mock_consumer,
                connect_pg=fake_connect_pg,
                topic="earthquakes-live",
                stop_event=stop_event,
            )

        # Verified: consumer retried the record after recovery and committed offset + 1
        self.assertGreaterEqual(attempts, 2)
        self.assertEqual(len(committed_offsets), 1)
        self.assertEqual(
            committed_offsets[0],
            {TopicPartition("earthquakes-live", 0): 11},
        )


if __name__ == "__main__":
    unittest.main()
