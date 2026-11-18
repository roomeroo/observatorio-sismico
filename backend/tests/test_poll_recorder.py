import asyncio
import sys
import tempfile
import unittest
from pathlib import Path

import httpx
import psycopg

from observatorio.database import postgres_connection_parameters
from observatorio.migration import apply_migrations_sync
from observatorio.poll_recorder import PollRecorder, payload_sha256
from observatorio.producer import poll_once
from observatorio.publication_state import PublicationState
from observatorio.usgs_source import exclusion_details
from test_postgres_integration import is_postgres_available

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


def feed(*features):
    return {"type": "FeatureCollection", "metadata": {"count": len(features)}, "features": list(features)}


def feature(event_id, event_type="earthquake", updated=1700000000000, place="Somewhere"):
    return {
        "type": "Feature",
        "id": event_id,
        "geometry": {"type": "Point", "coordinates": [1.0, 2.0, 3.0]},
        "properties": {"type": event_type, "updated": updated, "time": updated, "mag": 3.0, "place": place},
    }


FEED = feed(
    feature("rec-quake-1"),
    feature("rec-quarry-1", event_type="quarry blast", place="Quarry X"),
)


class ExclusionDetailsTests(unittest.TestCase):
    def test_quarry_blast_is_excluded_with_reason(self):
        details = exclusion_details(FEED["features"])
        self.assertEqual(len(details), 1)
        self.assertEqual(details[0]["event_id"], "rec-quarry-1")
        self.assertEqual(details[0]["reason"], "EVENT_TYPE_QUARRY BLAST")
        self.assertEqual(details[0]["place"], "Quarry X")


async def run_poll(recorder, payload=FEED, status=200):
    def handler(request):
        return httpx.Response(status, json=payload)

    async def send(topic, key, value):
        return None

    async def nosleep(_):
        return None

    with tempfile.TemporaryDirectory() as tmp:
        with PublicationState(Path(tmp) / "s.sqlite3") as state:
            async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
                await poll_once(
                    client, state, "t", send, (RuntimeError,),
                    source_retry_sleep=nosleep, send_retry_sleep=nosleep, recorder=recorder,
                )


class FailingRecorderTests(unittest.IsolatedAsyncioTestCase):
    async def test_database_down_does_not_stop_publication(self):
        def broken():
            raise psycopg.OperationalError("database is down")

        recorder = PollRecorder(connect=broken)
        sent = []

        def handler(request):
            return httpx.Response(200, json=FEED)

        async def send(topic, key, value):
            sent.append(key)

        async def nosleep(_):
            return None

        with tempfile.TemporaryDirectory() as tmp:
            with PublicationState(Path(tmp) / "s.sqlite3") as state:
                async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
                    with self.assertLogs("observatorio.poll_recorder", level="ERROR"):
                        await poll_once(
                            client, state, "t", send, (RuntimeError,),
                            source_retry_sleep=nosleep, send_retry_sleep=nosleep, recorder=recorder,
                        )
        self.assertEqual(sent, [b"rec-quake-1"])


@unittest.skipUnless(is_postgres_available(), "PostgreSQL is not reachable")
class PollRecorderIntegrationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        with psycopg.connect(**postgres_connection_parameters()) as conn:
            apply_migrations_sync(conn)
        self._clean()
        self.recorder = PollRecorder(retention_days=7)

    def tearDown(self):
        self._clean()

    def _clean(self):
        with psycopg.connect(**postgres_connection_parameters()) as conn:
            conn.execute("DELETE FROM observatorio.poll_exclusions")
            conn.execute("DELETE FROM observatorio.poll_log")
            conn.execute("DELETE FROM observatorio.raw_payloads")

    def _q(self, sql, params=()):
        with psycopg.connect(**postgres_connection_parameters()) as conn:
            return conn.execute(sql, params).fetchall()

    async def test_poll_log_and_exclusions_are_persisted(self):
        await run_poll(self.recorder)
        rows = self._q("SELECT status, feed_count, published_count, excluded_count, error, latency_ms FROM observatorio.poll_log")
        self.assertEqual(len(rows), 1)
        status, feed_count, published, excluded, error, latency = rows[0]
        self.assertEqual((status, feed_count, published, excluded, error), ("ok", 2, 1, 1, None))
        self.assertIsNotNone(latency)
        ex = self._q("SELECT event_id, reason, event_type, place FROM observatorio.poll_exclusions")
        self.assertEqual(ex, [("rec-quarry-1", "EVENT_TYPE_QUARRY BLAST", "quarry blast", "Quarry X")])

    async def test_failed_poll_is_logged_with_error(self):
        await run_poll(self.recorder, payload={"oops": True})
        rows = self._q("SELECT status, error FROM observatorio.poll_log")
        self.assertEqual(rows[0][0], "error")
        self.assertIn("GeoJSON", rows[0][1])

    async def test_identical_payload_is_stored_once(self):
        await run_poll(self.recorder)
        await run_poll(self.recorder)
        self.assertEqual(self._q("SELECT count(*) FROM observatorio.poll_log")[0][0], 2)
        self.assertEqual(self._q("SELECT count(*) FROM observatorio.raw_payloads")[0][0], 1)
        stored = self._q("SELECT payload_hash, payload FROM observatorio.raw_payloads")[0]
        self.assertEqual(stored[0], payload_sha256(FEED))
        self.assertEqual(stored[1], FEED)  # original payload, metadata included

    async def test_retention_deletes_old_payloads_only(self):
        await run_poll(self.recorder)
        await run_poll(self.recorder, payload=feed(feature("rec-quake-2")))
        old_hash = payload_sha256(FEED)
        with psycopg.connect(**postgres_connection_parameters()) as conn:
            conn.execute(
                "UPDATE observatorio.raw_payloads SET last_seen_at = now() - interval '30 days' WHERE payload_hash = %s",
                (old_hash,),
            )
        deleted = await self.recorder.purge()
        self.assertEqual(deleted, 1)
        self.assertEqual(self._q("SELECT count(*) FROM observatorio.raw_payloads")[0][0], 1)
        # poll metadata survives, only the payload reference is cleared
        self.assertEqual(self._q("SELECT count(*) FROM observatorio.poll_log")[0][0], 2)
        self.assertEqual(self._q("SELECT count(*) FROM observatorio.poll_log WHERE payload_hash IS NULL")[0][0], 1)


if __name__ == "__main__":
    unittest.main()
