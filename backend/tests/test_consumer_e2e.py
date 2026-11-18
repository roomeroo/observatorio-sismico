import asyncio
from dataclasses import dataclass
import json
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from aiokafka import TopicPartition

from observatorio.consumer import run_consumer
from observatorio.validation import (
    REASON_MALFORMED_JSON,
    REASON_MISSING_OR_INVALID_ID_OR_UPDATED,
    REASON_PAYLOAD_CONFLICT_SAME_VERSION,
)


@dataclass
class Record:
    topic: str
    partition: int
    offset: int
    value: bytes


class SimulatedPostgresState:
    """In-memory state simulating PostgreSQL tables and transaction constraints."""

    def __init__(self) -> None:
        self.event_versions: dict[tuple[str, int], dict] = {}
        self.current_events: dict[str, dict] = {}
        self.quarantine_records: list[dict] = []
        self.should_fail_next: bool = False

    def reset_failure(self) -> None:
        self.should_fail_next = False


class FakeAsyncCursor:
    def __init__(self, state: SimulatedPostgresState) -> None:
        self.state = state
        self._last_fetchone = None

    async def execute(self, query: str, params: tuple = ()) -> None:
        if self.state.should_fail_next:
            self.state.should_fail_next = False
            raise ConnectionError("Simulated database failure during query execution")

        if "SELECT payload_hash FROM observatorio.event_versions" in query:
            event_id, updated = params[0], params[1]
            key = (event_id, updated)
            if key in self.state.event_versions:
                self._last_fetchone = (self.state.event_versions[key]["payload_hash"],)
            else:
                self._last_fetchone = None

        elif "INSERT INTO observatorio.quarantine_records" in query:
            topic, partition, offset, raw, reason, decoded = (
                params[0],
                params[1],
                params[2],
                params[3],
                params[4],
                params[5],
            )
            # UNIQUE(kafka_topic, kafka_partition, kafka_offset)
            already_exists = any(
                r["topic"] == topic and r["partition"] == partition and r["offset"] == offset
                for r in self.state.quarantine_records
            )
            if not already_exists:
                self.state.quarantine_records.append(
                    {
                        "topic": topic,
                        "partition": partition,
                        "offset": offset,
                        "raw": raw,
                        "reason": reason,
                        "decoded": decoded,
                    }
                )

        elif "INSERT INTO observatorio.event_versions" in query:
            event_id, updated, payload_hash = params[0], params[1], params[2]
            key = (event_id, updated)
            self.state.event_versions[key] = {
                "event_id": event_id,
                "updated": updated,
                "payload_hash": payload_hash,
                "params": params,
            }

        elif "INSERT INTO observatorio.current_events" in query:
            event_id, updated, payload_hash = params[0], params[1], params[2]
            existing = self.state.current_events.get(event_id)
            # WHERE EXCLUDED.updated > current_events.updated
            if existing is None or updated > existing["updated"]:
                self.state.current_events[event_id] = {
                    "event_id": event_id,
                    "updated": updated,
                    "payload_hash": payload_hash,
                    "params": params,
                }

    async def fetchone(self) -> tuple | None:
        return self._last_fetchone


class FakeAsyncConnection:
    def __init__(self, state: SimulatedPostgresState) -> None:
        self.state = state
        self.closed = False

    def cursor(self) -> MagicMock:
        cursor = FakeAsyncCursor(self.state)
        cm = MagicMock()
        cm.__aenter__ = AsyncMock(return_value=cursor)
        cm.__aexit__ = AsyncMock(return_value=None)
        return cm

    def transaction(self) -> MagicMock:
        cm = MagicMock()
        cm.__aenter__ = AsyncMock(return_value=None)
        cm.__aexit__ = AsyncMock(return_value=False)
        return cm

    async def close(self) -> None:
        self.closed = True


class ConsumerIntegratedPathTests(unittest.IsolatedAsyncioTestCase):
    @staticmethod
    def envelope(
        event_id: str,
        updated: int,
        mag: float = 3.0,
        place: str = "Test Area",
    ) -> bytes:
        doc = {
            "source": "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/all_day.geojson",
            "ingested_at": 1700000000000,
            "mode": "live",
            "event": {
                "type": "Feature",
                "id": event_id,
                "geometry": {"type": "Point", "coordinates": [-120.0, 35.0, 10.0]},
                "properties": {
                    "type": "earthquake",
                    "time": 1700000000000,
                    "updated": updated,
                    "mag": mag,
                    "place": place,
                },
            },
        }
        return json.dumps(doc).encode("utf-8")

    async def test_end_to_end_sequence_and_recovery(self) -> None:
        state = SimulatedPostgresState()
        committed_offsets: list[int] = []

        # Construct message sequence
        records = [
            # 0: E1 version 1000
            Record("earthquakes-live", 0, 0, self.envelope("E1", 1000, 3.0, "Place 1")),
            # 1: E1 identical redelivery at 1000
            Record("earthquakes-live", 0, 1, self.envelope("E1", 1000, 3.0, "Place 1")),
            # 2: E1 conflicting payload at same updated=1000
            Record("earthquakes-live", 0, 2, self.envelope("E1", 1000, 4.5, "Altered Place")),
            # 3: E1 revision at updated=2000
            Record("earthquakes-live", 0, 3, self.envelope("E1", 2000, 3.2, "Place 2")),
            # 4: E1 older redelivery at updated=500
            Record("earthquakes-live", 0, 4, self.envelope("E1", 500, 2.9, "Place 0")),
            # 5: Malformed JSON
            Record("earthquakes-live", 0, 5, b"not json"),
            # 6: Missing id
            Record(
                "earthquakes-live",
                0,
                6,
                json.dumps(
                    {
                        "source": "usgs",
                        "ingested_at": 1700000000000,
                        "mode": "live",
                        "event": {
                            "type": "Feature",
                            "properties": {"type": "earthquake", "updated": 1000},
                        },
                    }
                ).encode("utf-8"),
            ),
            # 7: E2 at updated=1500 (will test DB failure recovery on this record)
            Record("earthquakes-live", 0, 7, self.envelope("E2", 1500, 5.0, "Place E2")),
        ]

        idx = 0
        stop_event = asyncio.Event()

        mock_consumer = MagicMock()
        mock_consumer.subscribe = MagicMock()

        async def getone() -> Record:
            nonlocal idx
            if idx < len(records):
                rec = records[idx]
                idx += 1
                return rec
            stop_event.set()
            await asyncio.sleep(10)
            raise asyncio.CancelledError()

        mock_consumer.getone = AsyncMock(side_effect=getone)

        async def commit(offsets: dict[TopicPartition, int]) -> None:
            tp = TopicPartition("earthquakes-live", 0)
            committed_offsets.append(offsets[tp])
            if offsets[tp] == 8:
                stop_event.set()

        mock_consumer.commit = AsyncMock(side_effect=commit)

        async def connect_pg() -> FakeAsyncConnection:
            return FakeAsyncConnection(state)

        # Trigger DB failure right before record 7 is processed
        # We hook into cursor to fail on offset 7 first attempt
        def fail_on_record_7() -> None:
            if idx == 8:  # after record 7 is read (idx is incremented)
                state.should_fail_next = True

        with patch("observatorio.consumer.apply_migrations", new=AsyncMock(return_value=[])), patch(
            "observatorio.consumer.load_dim_country", new=AsyncMock(return_value=0)
        ):
            # Set failure for record 7
            state.should_fail_next = True

            await run_consumer(
                consumer=mock_consumer,
                connect_pg=connect_pg,
                topic="earthquakes-live",
                stop_event=stop_event,
            )

        # Verification:
        # 1. All records 0 through 7 were committed in order (committed_offsets has 1..8)
        self.assertIn(8, committed_offsets)

        # 2. Event versions for E1:
        # - (E1, 1000) exists
        # - (E1, 2000) exists
        # - (E1, 500) exists
        self.assertIn(("E1", 1000), state.event_versions)
        self.assertIn(("E1", 2000), state.event_versions)
        self.assertIn(("E1", 500), state.event_versions)
        # E2 version exists
        self.assertIn(("E2", 1500), state.event_versions)

        # 3. Current projection:
        # E1 current projection must have updated=2000 (not regressed by updated=500!)
        self.assertEqual(state.current_events["E1"]["updated"], 2000)
        # E2 current projection has updated=1500
        self.assertEqual(state.current_events["E2"]["updated"], 1500)

        # 4. Quarantine records:
        # - offset 2 (conflicting payload at 1000) -> PAYLOAD_CONFLICT_SAME_VERSION
        # - offset 5 (malformed JSON) -> MALFORMED_JSON
        # - offset 6 (missing id) -> MISSING_OR_INVALID_ID_OR_UPDATED
        reasons = {r["offset"]: r["reason"] for r in state.quarantine_records}
        self.assertEqual(reasons[2], REASON_PAYLOAD_CONFLICT_SAME_VERSION)
        self.assertEqual(reasons[5], REASON_MALFORMED_JSON)
        self.assertEqual(reasons[6], REASON_MISSING_OR_INVALID_ID_OR_UPDATED)


if __name__ == "__main__":
    unittest.main()
