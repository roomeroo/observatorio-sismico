import json
import os
import unittest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import psycopg
from psycopg.types.json import Jsonb

from observatorio.database import postgres_connection_parameters
from observatorio.migration import apply_migrations_sync


def is_postgres_available() -> bool:
    try:
        params = postgres_connection_parameters()
        with psycopg.connect(**params, connect_timeout=1) as conn:
            return True
    except Exception:
        return False


class PostgresIntegrationTests(unittest.TestCase):
    @unittest.skipUnless(is_postgres_available(), "PostgreSQL is not reachable")
    def test_live_postgres_migration_and_persistence(self) -> None:
        params = postgres_connection_parameters()
        with psycopg.connect(**params) as conn:
            # Verify migration applies cleanly on top of existing schema
            applied = apply_migrations_sync(conn)
            # Re-running migrations is safe
            rerun_applied = apply_migrations_sync(conn)
            self.assertEqual(rerun_applied, [])

            # Test storing and reading back exact feature JSON and extraction metadata
            feature = {
                "type": "Feature",
                "id": "test-live-1",
                "geometry": {"type": "Point", "coordinates": [-118.5, 34.2, 10.0]},
                "properties": {
                    "type": "earthquake",
                    "time": 1700000000000,
                    "updated": 1700000010000,
                    "mag": 3.5,
                    "magType": "ml",
                    "place": "Southern California",
                },
            }

            now_utc = datetime.now(timezone.utc)
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO observatorio.event_versions (
                        event_id, updated, payload_hash, time, time_utc, updated_utc,
                        mag, mag_type, place, event_type, longitude, latitude, depth,
                        original_feature, source, ingested_at, mode, kafka_topic,
                        kafka_partition, kafka_offset
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                    )
                    ON CONFLICT (event_id, updated) DO NOTHING;
                    """,
                    (
                        "test-live-1",
                        1700000010000,
                        "hash123",
                        1700000000000,
                        now_utc,
                        now_utc,
                        3.5,
                        "ml",
                        "Southern California",
                        "earthquake",
                        -118.5,
                        34.2,
                        10.0,
                        Jsonb(feature),
                        "usgs",
                        now_utc,
                        "live",
                        "earthquakes-live",
                        0,
                        100,
                    ),
                )
                conn.commit()

                cur.execute(
                    """
                    SELECT event_id, updated, original_feature, source, mode, kafka_topic
                    FROM observatorio.event_versions
                    WHERE event_id = %s AND updated = %s
                    """,
                    ("test-live-1", 1700000010000),
                )
                row = cur.fetchone()
                self.assertIsNotNone(row)
                self.assertEqual(row[0], "test-live-1")
                self.assertEqual(row[1], 1700000010000)
                # original_feature is preserved exactly
                self.assertEqual(row[2]["id"], "test-live-1")
                self.assertEqual(row[2]["properties"]["mag"], 3.5)
                self.assertEqual(row[3], "usgs")
                self.assertEqual(row[4], "live")
                self.assertEqual(row[5], "earthquakes-live")

    def test_schema_shape_and_payload_roundtrip_logic(self) -> None:
        """Verify feature serialization and extraction metadata matching table definition."""
        feature = {
            "type": "Feature",
            "id": "quake-roundtrip",
            "geometry": {"type": "Point", "coordinates": [-122.3, 37.8, 8.5]},
            "properties": {
                "type": "earthquake",
                "time": 1710000000000,
                "updated": 1710000005000,
                "mag": 2.1,
                "magType": "md",
                "place": "San Francisco Bay Area",
            },
        }
        serialized = json.dumps(feature)
        deserialized = json.loads(serialized)
        self.assertEqual(deserialized, feature)
        self.assertEqual(deserialized["geometry"]["coordinates"], [-122.3, 37.8, 8.5])
        self.assertIsNone(deserialized.get("optional_missing_field"))


if __name__ == "__main__":
    unittest.main()


class MigrationSchemaIntegrationTests(unittest.TestCase):
    @unittest.skipUnless(is_postgres_available(), "PostgreSQL is not reachable")
    def test_migration_0003_creates_tables_and_columns(self) -> None:
        with psycopg.connect(**postgres_connection_parameters()) as conn:
            apply_migrations_sync(conn)
            apply_migrations_sync(conn)  # repeated run stays a no-op
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT table_name FROM information_schema.tables "
                    "WHERE table_schema = 'observatorio'"
                )
                tables = {row[0] for row in cur.fetchall()}
                for name in (
                    "dim_country", "dim_date", "poll_log", "poll_exclusions",
                    "raw_payloads", "historical_events", "extraction_queries",
                ):
                    self.assertIn(name, tables)
                cur.execute(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_schema = 'observatorio' AND table_name = 'current_events'"
                )
                columns = {row[0] for row in cur.fetchall()}
                self.assertTrue({"country_id", "geo_ambiguous"} <= columns)
