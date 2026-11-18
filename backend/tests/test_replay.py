import asyncio
import json
import os
import sys
import unittest
from datetime import datetime, timezone

import psycopg
from fastapi.testclient import TestClient
from psycopg import AsyncConnection

from observatorio.consumer import process_single_record, schema_for_topic
from observatorio.database import postgres_connection_parameters
from observatorio.migration import apply_migrations_sync
from observatorio.replay import build_messages, feature_from_row, publish
from test_postgres_integration import is_postgres_available

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

PREFIX = "rp-"


def t_ms(minute, second=0):
    return int(datetime(1991, 1, 1, 0, minute, second, tzinfo=timezone.utc).timestamp() * 1000)


def feature(suffix, t, mag=5.0):
    return {
        "type": "Feature",
        "id": PREFIX + suffix,
        "geometry": {"type": "Point", "coordinates": [139.7, 35.7, 12.0]},
        "properties": {"type": "earthquake", "time": t, "updated": t + 5000, "mag": mag, "magType": "mb", "place": "Replay"},
    }


FEATURES = [feature("c", t_ms(30)), feature("a", t_ms(0)), feature("b", t_ms(10))]  # unordered on purpose


class BuildMessagesTests(unittest.TestCase):
    def test_ascending_order_scaled_delays_and_envelope(self):
        msgs = build_messages(FEATURES, speed=60, duplicates=0, stale_revisions=0, now_ms=lambda: 1234)
        ids = [json.loads(m.value)["event"]["id"] for m in msgs]
        self.assertEqual(ids, [PREFIX + "a", PREFIX + "b", PREFIX + "c"])
        # gaps are 0, 600 s and 1200 s of history; at x60 -> 0, 10 s, 20 s
        self.assertEqual([m.delay_seconds for m in msgs], [0.0, 10.0, 20.0])
        for m in msgs:
            env = json.loads(m.value)
            self.assertEqual(env["mode"], "replay")
            self.assertEqual(env["replayed_at"], 1234)
            self.assertIn("source", env)

    def test_controlled_duplicate_and_older_revision(self):
        msgs = build_messages(FEATURES, speed=60)
        self.assertEqual([m.kind for m in msgs], ["event"] * 3 + ["duplicate", "older_revision"])
        first, dup, older = (json.loads(msgs[i].value)["event"] for i in (0, 3, 4))
        self.assertEqual(first["id"], dup["id"])
        self.assertEqual(first["properties"]["updated"], dup["properties"]["updated"])
        self.assertLess(older["properties"]["updated"], first["properties"]["updated"])

    def test_invalid_speed(self):
        with self.assertRaises(ValueError):
            build_messages(FEATURES, speed=0)

    def test_publish_sleeps_scaled_delays_in_order(self):
        msgs = build_messages(FEATURES, speed=600, duplicates=0, stale_revisions=0)
        slept, sent = [], []

        async def sleep(s):
            slept.append(s)

        async def send(k, v):
            sent.append(k)

        asyncio.run(publish(msgs, send, sleep))
        self.assertEqual(slept, [1.0, 2.0])
        self.assertEqual(sent, [PREFIX.encode() + s for s in (b"a", b"b", b"c")])

    def test_row_without_depth_is_not_replayable(self):
        t = datetime(1991, 1, 1, tzinfo=timezone.utc)
        self.assertIsNone(feature_from_row(("x", t, t, 4.0, "mb", "p", "earthquake", 1.0, 2.0, None)))

    def test_topic_selects_schema(self):
        self.assertEqual(schema_for_topic("earthquakes-replay", "earthquakes-replay"), "replay")
        self.assertEqual(schema_for_topic("earthquakes-live", "earthquakes-replay"), "observatorio")
        self.assertEqual(schema_for_topic("earthquakes-replay", None), "observatorio")


def q(sql, params=()):
    with psycopg.connect(**postgres_connection_parameters(), autocommit=True) as conn:
        return conn.execute(sql, params).fetchall()


def cleanup():
    with psycopg.connect(**postgres_connection_parameters(), autocommit=True) as conn:
        for schema in ("observatorio", "replay"):
            for t in ("event_versions", "current_events"):
                conn.execute(f"DELETE FROM {schema}.{t} WHERE event_id LIKE %s", (PREFIX + "%",))


async def consume_as_replay(messages):
    conn = await AsyncConnection.connect(**postgres_connection_parameters(), autocommit=True)
    try:
        for i, m in enumerate(messages):
            await process_single_record(conn, "earthquakes-replay", 0, i, m.value, schema_for_topic("earthquakes-replay", "earthquakes-replay"))
    finally:
        await conn.close()


@unittest.skipUnless(is_postgres_available(), "PostgreSQL is not reachable")
class ReplayIsolationIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with psycopg.connect(**postgres_connection_parameters()) as conn:
            apply_migrations_sync(conn)
        import observatorio.api as api

        cls.client_cm = TestClient(api.app)
        cls.client = cls.client_cm.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.client_cm.__exit__(None, None, None)
        cleanup()

    def setUp(self):
        cleanup()

    def test_replay_counts_unique_events_keeps_newest_and_leaves_live_intact(self):
        live_before = q("SELECT count(*), max(last_processed_at) FROM observatorio.current_events")[0]
        live_versions_before = q("SELECT count(*) FROM observatorio.event_versions")[0][0]
        messages = build_messages(FEATURES, speed=60)
        self.assertEqual(len(messages), 5)  # 3 events + 1 duplicate + 1 older revision
        asyncio.run(consume_as_replay(messages))

        self.assertEqual(q("SELECT count(*) FROM replay.current_events WHERE event_id LIKE %s", (PREFIX + "%",))[0][0], 3)
        # duplicate stored once; older revision recorded as history but never current
        self.assertEqual(q("SELECT count(*) FROM replay.event_versions WHERE event_id = %s", (PREFIX + "a",))[0][0], 2)
        current = q("SELECT updated, mag FROM replay.current_events WHERE event_id = %s", (PREFIX + "a",))[0]
        self.assertEqual(current, (t_ms(0) + 5000, 5.0))
        self.assertEqual(q("SELECT count(*) FROM replay.quarantine_records")[0][0], 0)

        # live schema untouched
        self.assertEqual(q("SELECT count(*), max(last_processed_at) FROM observatorio.current_events")[0], live_before)
        self.assertEqual(q("SELECT count(*) FROM observatorio.event_versions")[0][0], live_versions_before)
        self.assertEqual(q("SELECT count(*) FROM observatorio.current_events WHERE event_id LIKE %s", (PREFIX + "%",))[0][0], 0)

    def test_api_exposes_replay_only_when_requested(self):
        asyncio.run(consume_as_replay(build_messages(FEATURES, speed=60)))
        window = {"start": "1991-01-01T00:00:00Z", "end": "1991-01-01T01:00:00Z"}
        live = self.client.get("/api/eventos", params=window).json()
        self.assertEqual(live["metadata"]["total"], 0)
        replay = self.client.get("/api/eventos", params={**window, "mode": "replay"}).json()
        self.assertEqual(replay["metadata"]["total"], 3)
        self.assertEqual(replay["metadata"]["mode"], "replay")
        self.assertIn("replay_loaded_at", replay["metadata"])
        self.assertNotIn("last_ingestion", replay["metadata"])
        stats = self.client.get("/api/estadisticas", params={**window, "mode": "replay"}).json()
        self.assertEqual(stats["total"], 3)
        self.assertIn("replay_loaded_at", stats)
        self.assertEqual(self.client.get("/api/estadisticas", params=window).json()["total"], 0)

    def test_replay_health_does_not_report_live_ingestion(self):
        live_ingestion = self.client.get("/api/salud").json()["last_ingestion"]
        asyncio.run(consume_as_replay(build_messages(FEATURES, speed=60)))
        health = self.client.get("/api/salud", params={"mode": "replay"}).json()
        self.assertEqual(health["mode"], "replay")
        self.assertIsNotNone(health["replay_loaded_at"])
        self.assertNotIn("last_ingestion", health)
        self.assertEqual(self.client.get("/api/salud").json()["last_ingestion"], live_ingestion)


if __name__ == "__main__":
    unittest.main()
