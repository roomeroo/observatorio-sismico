"""Integration tests (real PostgreSQL) for acceptance cases not covered elsewhere:
older version does not replace the current one, null magnitude stays null (ND, never 0),
and a consumer restart re-reading the same Kafka records changes nothing."""

import asyncio
import dataclasses
import json
import sys
import unittest

import psycopg
from psycopg import AsyncConnection

from observatorio.consumer import process_single_record
from observatorio.database import postgres_connection_parameters
from observatorio.migration import apply_migrations_sync
from test_persistence import PersistenceUnitTests
from test_postgres_integration import is_postgres_available

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

PREFIX = "acc-"
T = 1_000_000_000_000  # 2001-09-09, well away from real data


def envelope(event_id, updated, mag, lon=139.7, lat=35.7):
    feature = {
        "type": "Feature",
        "id": event_id,
        "geometry": {"type": "Point", "coordinates": [lon, lat, 10.0]},
        "properties": {"type": "earthquake", "time": T, "updated": updated, "mag": mag, "place": "Acceptance"},
    }
    return json.dumps(
        {"source": "test", "ingested_at": T + 5000, "mode": "live", "event": feature}
    ).encode("utf-8")


def q(sql, params=()):
    with psycopg.connect(**postgres_connection_parameters(), autocommit=True) as conn:
        return conn.execute(sql, params).fetchall()


def cleanup():
    with psycopg.connect(**postgres_connection_parameters(), autocommit=True) as conn:
        for t in ("event_versions", "current_events"):
            conn.execute(f"DELETE FROM observatorio.{t} WHERE event_id LIKE %s", (PREFIX + "%",))
        conn.execute("DELETE FROM observatorio.quarantine_records WHERE kafka_topic = 'acc-topic'")


async def feed(records):
    """records: list of (offset, payload). Opens a fresh connection like a restarted consumer."""
    conn = await AsyncConnection.connect(**postgres_connection_parameters(), autocommit=True)
    try:
        for offset, payload in records:
            await process_single_record(conn, "acc-topic", 0, offset, payload)
    finally:
        await conn.close()


@unittest.skipUnless(is_postgres_available(), "PostgreSQL is not reachable")
class AcceptanceGapTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with psycopg.connect(**postgres_connection_parameters()) as conn:
            apply_migrations_sync(conn)

    def setUp(self):
        cleanup()

    def tearDown(self):
        cleanup()

    def test_older_version_does_not_replace_current(self):
        eid = PREFIX + "old"
        asyncio.run(feed([(0, envelope(eid, T + 20_000, 5.0)), (1, envelope(eid, T + 10_000, 3.0))]))  # newer first, older after
        current = q("SELECT updated, mag FROM observatorio.current_events WHERE event_id = %s", (eid,))
        self.assertEqual(current, [(T + 20_000, 5.0)])
        # the older revision is kept as history, never as current state
        self.assertEqual(q("SELECT count(*) FROM observatorio.event_versions WHERE event_id = %s", (eid,))[0][0], 2)

    def test_newer_version_replaces_current(self):
        eid = PREFIX + "new"
        asyncio.run(feed([(0, envelope(eid, T + 10_000, 3.0)), (1, envelope(eid, T + 20_000, 5.0))]))
        self.assertEqual(q("SELECT updated, mag FROM observatorio.current_events WHERE event_id = %s", (eid,)), [(T + 20_000, 5.0)])

    def test_null_magnitude_is_stored_as_null_not_zero(self):
        eid = PREFIX + "nomag"
        asyncio.run(feed([(0, envelope(eid, T + 10_000, None))]))
        self.assertEqual(q("SELECT mag, mag IS NULL FROM observatorio.current_events WHERE event_id = %s", (eid,)), [(None, True)])
        # a magnitude filter must not treat NULL as 0 nor include it
        self.assertEqual(q("SELECT count(*) FROM observatorio.current_events WHERE event_id = %s AND mag >= 0", (eid,))[0][0], 0)

    def test_consumer_restart_rereading_same_records_changes_nothing(self):
        eid = PREFIX + "restart"
        records = [(0, envelope(eid, T + 10_000, 4.0)), (1, b"not json at all"), (2, envelope(eid, T + 20_000, 4.5))]
        asyncio.run(feed(records))
        before = (
            q("SELECT count(*) FROM observatorio.event_versions WHERE event_id = %s", (eid,))[0][0],
            q("SELECT updated, mag FROM observatorio.current_events WHERE event_id = %s", (eid,)),
            q("SELECT count(*) FROM observatorio.quarantine_records WHERE kafka_topic = 'acc-topic'")[0][0],
        )
        # Kafka redelivers from the last committed offset after a crash: same records, new connection
        asyncio.run(feed(records))
        after = (
            q("SELECT count(*) FROM observatorio.event_versions WHERE event_id = %s", (eid,))[0][0],
            q("SELECT updated, mag FROM observatorio.current_events WHERE event_id = %s", (eid,)),
            q("SELECT count(*) FROM observatorio.quarantine_records WHERE kafka_topic = 'acc-topic'")[0][0],
        )
        self.assertEqual(before, after)
        self.assertEqual(before, (2, [(T + 20_000, 4.5)], 1))


if __name__ == "__main__":
    unittest.main()
