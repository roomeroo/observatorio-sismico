from datetime import datetime, timezone
import unittest
from unittest.mock import AsyncMock, MagicMock, call

from observatorio.persistence import persist_accepted_event
from observatorio.validation import (
    REASON_PAYLOAD_CONFLICT_SAME_VERSION,
    ValidatedEvent,
    compute_payload_hash,
)


class PersistenceUnitTests(unittest.IsolatedAsyncioTestCase):
    @staticmethod
    def make_event(
        event_id: str = "quake-100",
        updated: int = 1700000010000,
        time: int = 1700000000000,
        mag: float | None = 4.2,
        place: str = "Test Location",
    ) -> ValidatedEvent:
        feature = {
            "type": "Feature",
            "id": event_id,
            "geometry": {"type": "Point", "coordinates": [-120.0, 35.0, 10.0]},
            "properties": {
                "type": "earthquake",
                "time": time,
                "updated": updated,
                "mag": mag,
                "place": place,
            },
        }
        return ValidatedEvent(
            event_id=event_id,
            updated=updated,
            payload_hash=compute_payload_hash(feature),
            time=time,
            time_utc=datetime.fromtimestamp(time / 1000.0, tz=timezone.utc),
            updated_utc=datetime.fromtimestamp(updated / 1000.0, tz=timezone.utc),
            mag=mag,
            mag_type="mw",
            place=place,
            status="reviewed",
            tsunami=0,
            sig=100,
            net="us",
            code="100",
            ids="us100",
            sources="us",
            types="origin,phase-data",
            nst=20,
            dmin=0.5,
            rms=0.2,
            gap=45.0,
            mag_error=0.1,
            mag_nst=15,
            depth_error=1.0,
            horizontal_error=0.5,
            event_type="earthquake",
            longitude=-120.0,
            latitude=35.0,
            depth=10.0,
            original_feature=feature,
            source="https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/all_day.geojson",
            ingested_at=datetime.fromtimestamp(1700000020, tz=timezone.utc),
            mode="live",
        )

    async def test_first_version_inserts_version_and_current(self) -> None:
        mock_conn = MagicMock()
        mock_cursor = AsyncMock()
        mock_cursor_cm = MagicMock()
        mock_cursor_cm.__aenter__ = AsyncMock(return_value=mock_cursor)
        mock_cursor_cm.__aexit__ = AsyncMock(return_value=None)
        mock_conn.cursor.return_value = mock_cursor_cm

        # No existing row
        mock_cursor.fetchone.return_value = None

        event = self.make_event()
        result = await persist_accepted_event(
            mock_conn, event, "earthquakes-live", 0, 100, b"raw"
        )
        self.assertTrue(result)

        # Check queries executed: select, dim_date upsert, insert version, insert current
        self.assertEqual(mock_cursor.execute.await_count, 4)
        select_call, date_call, insert_v_call, insert_c_call = mock_cursor.execute.await_args_list
        self.assertIn("INSERT INTO observatorio.dim_date", date_call.args[0])
        # Event at (-120, 35) lies in the United States catalog polygon
        self.assertEqual(insert_v_call.args[1][-2:], ("USA", False))

        self.assertIn("SELECT payload_hash FROM observatorio.event_versions", select_call.args[0])
        self.assertIn("INSERT INTO observatorio.event_versions", insert_v_call.args[0])
        self.assertIn("INSERT INTO observatorio.current_events", insert_c_call.args[0])
        self.assertIn("WHERE EXCLUDED.updated > observatorio.current_events.updated", insert_c_call.args[0])

    async def test_duplicate_delivery_with_matching_payload_is_idempotent(self) -> None:
        mock_conn = MagicMock()
        mock_cursor = AsyncMock()
        mock_cursor_cm = MagicMock()
        mock_cursor_cm.__aenter__ = AsyncMock(return_value=mock_cursor)
        mock_cursor_cm.__aexit__ = AsyncMock(return_value=None)
        mock_conn.cursor.return_value = mock_cursor_cm

        event = self.make_event()
        # Existing row with matching hash
        mock_cursor.fetchone.return_value = (event.payload_hash,)

        result = await persist_accepted_event(
            mock_conn, event, "earthquakes-live", 0, 101, b"raw"
        )
        self.assertTrue(result)
        # Only the SELECT query is executed, no INSERTs
        self.assertEqual(mock_cursor.execute.await_count, 1)

    async def test_conflicting_payload_same_version_enters_quarantine(self) -> None:
        mock_conn = MagicMock()
        mock_cursor = AsyncMock()
        mock_cursor_cm = MagicMock()
        mock_cursor_cm.__aenter__ = AsyncMock(return_value=mock_cursor)
        mock_cursor_cm.__aexit__ = AsyncMock(return_value=None)
        mock_conn.cursor.return_value = mock_cursor_cm

        event = self.make_event()
        # Existing row with a DIFFERENT hash
        mock_cursor.fetchone.return_value = ("different-hash-456",)

        result = await persist_accepted_event(
            mock_conn, event, "earthquakes-live", 0, 102, b"raw"
        )
        self.assertFalse(result)
        # Executed SELECT then INSERT INTO quarantine_records
        self.assertEqual(mock_cursor.execute.await_count, 2)
        quarantine_call = mock_cursor.execute.await_args_list[1]
        self.assertIn("INSERT INTO observatorio.quarantine_records", quarantine_call.args[0])
        self.assertEqual(quarantine_call.args[1][4], REASON_PAYLOAD_CONFLICT_SAME_VERSION)

    async def test_transaction_rollback_preserves_state(self) -> None:
        mock_conn = MagicMock()
        mock_cursor = AsyncMock()
        mock_cursor_cm = MagicMock()
        mock_cursor_cm.__aenter__ = AsyncMock(return_value=mock_cursor)
        mock_cursor_cm.__aexit__ = AsyncMock(return_value=None)
        mock_conn.cursor.return_value = mock_cursor_cm

        mock_cursor.fetchone.return_value = None
        mock_cursor.execute.side_effect = [None, RuntimeError("DB error on version insert")]

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

        event = self.make_event()
        with self.assertRaises(RuntimeError):
            async with mock_conn.transaction():
                await persist_accepted_event(
                    mock_conn, event, "earthquakes-live", 0, 103, b"raw"
                )

        self.assertTrue(fake_tx.rolled_back)


if __name__ == "__main__":
    unittest.main()
