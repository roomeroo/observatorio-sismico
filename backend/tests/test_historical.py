import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import psycopg

from observatorio import historical
from observatorio.database import postgres_connection_parameters
from observatorio.geo import get_catalog
from observatorio.migration import apply_migrations_sync
from test_postgres_integration import is_postgres_available


def ms(year, month, day, hour=0, minute=0, second=0):
    return int(datetime(year, month, day, hour, minute, second, tzinfo=timezone.utc).timestamp() * 1000)


def feat(event_id, t_ms, mag=4.5, lon=139.7, lat=35.7, updated=None):
    return {
        "type": "Feature",
        "id": event_id,
        "geometry": {"type": "Point", "coordinates": [lon, lat, 10.0]},
        "properties": {"time": t_ms, "updated": updated or t_ms, "mag": mag, "magType": "mb",
                       "place": "Test", "type": "earthquake"},
    }


class FakeUsgs:
    """Simulated FDSN service: filters a fixed event list by interval and honours limit."""

    def __init__(self, features):
        self.features = features
        self.calls = []

    def __call__(self, params):
        self.calls.append(params)
        start = datetime.fromisoformat(params["starttime"]).replace(tzinfo=timezone.utc).timestamp() * 1000
        end = datetime.fromisoformat(params["endtime"]).replace(tzinfo=timezone.utc).timestamp() * 1000
        # USGS includes both ends of the interval -> boundary events appear twice
        selected = [f for f in self.features if start <= f["properties"]["time"] <= end]
        selected.sort(key=lambda f: f["properties"]["time"])
        return 200, {"type": "FeatureCollection", "features": selected[: params["limit"]]}


class MonthWindowsTests(unittest.TestCase):
    def test_twelve_contiguous_months(self):
        w = historical.month_windows(2025)
        self.assertEqual(len(w), 12)
        self.assertEqual(w[0][0], datetime(2025, 1, 1, tzinfo=timezone.utc))
        self.assertEqual(w[-1][1], datetime(2026, 1, 1, tzinfo=timezone.utc))
        for (_, e), (s, _) in zip(w, w[1:]):
            self.assertEqual(e, s)


class AcquisitionTests(unittest.TestCase):
    def test_normal_month_is_saved_and_counted(self):
        usgs = FakeUsgs([feat("a", ms(2025, 3, 5)), feat("b", ms(2025, 3, 9))])
        with tempfile.TemporaryDirectory() as tmp:
            records, events = historical.acquire_year(2025, fetch=usgs, data_dir=Path(tmp))
            self.assertEqual(len(usgs.calls), 12)
            self.assertEqual(set(events), {"a", "b"})
            march = [r for r in records if r.start.month == 3][0]
            self.assertEqual(march.result_count, 2)
            self.assertFalse(march.truncated)
            self.assertTrue((Path(tmp) / march.file).exists())
            self.assertEqual(march.status, "200")

    def test_saturated_month_is_split_and_truncated_data_not_used(self):
        feats = [feat(f"e{i}", ms(2025, 2, 1 + i)) for i in range(8)]  # 8 events in February
        usgs = FakeUsgs(feats)
        with patch.object(historical, "SERVICE_LIMIT", 5):
            with tempfile.TemporaryDirectory() as tmp:
                records, events = historical.acquire_year(2025, fetch=usgs, data_dir=Path(tmp))
        self.assertEqual(set(events), {f["id"] for f in feats})  # nothing lost
        truncated = [r for r in records if r.truncated]
        self.assertGreaterEqual(len(truncated), 1)
        self.assertTrue(all(r.file is None for r in truncated))  # never stored as data
        self.assertGreater(len(usgs.calls), 12)  # extra sub-queries were issued
        self.assertTrue(all(r.result_count < 5 for r in records if not r.truncated))

    def test_boundary_event_is_stored_once(self):
        boundary = feat("edge", ms(2025, 4, 1))  # exactly the April/March boundary
        usgs = FakeUsgs([boundary])
        with tempfile.TemporaryDirectory() as tmp:
            records, events = historical.acquire_year(2025, fetch=usgs, data_dir=Path(tmp))
        returned = sum(r.result_count for r in records)
        self.assertEqual(returned, 2)  # both adjacent queries returned it
        self.assertEqual(list(events), ["edge"])

    def test_rerun_uses_files_without_network(self):
        usgs = FakeUsgs([feat("a", ms(2025, 3, 5))])
        with tempfile.TemporaryDirectory() as tmp:
            historical.acquire_year(2025, fetch=usgs, data_dir=Path(tmp))

            def no_network(params):
                raise AssertionError("network used on rerun")

            records, events = historical.acquire_year(2025, fetch=no_network, data_dir=Path(tmp))
            self.assertEqual(list(events), ["a"])
            self.assertTrue(all(r.reused for r in records))

    def test_rerun_after_split_needs_no_network(self):
        feats = [feat(f"e{i}", ms(2025, 2, 1 + i)) for i in range(8)]
        usgs = FakeUsgs(feats)
        with patch.object(historical, "SERVICE_LIMIT", 5):
            with tempfile.TemporaryDirectory() as tmp:
                historical.acquire_year(2025, fetch=usgs, data_dir=Path(tmp))

                def no_network(params):
                    raise AssertionError("network used on rerun")

                _, events = historical.acquire_year(2025, fetch=no_network, data_dir=Path(tmp))
        self.assertEqual(len(events), 8)

    def test_refresh_queries_again(self):
        usgs = FakeUsgs([feat("a", ms(2025, 3, 5))])
        with tempfile.TemporaryDirectory() as tmp:
            historical.acquire_year(2025, fetch=usgs, data_dir=Path(tmp))
            historical.acquire_year(2025, fetch=usgs, data_dir=Path(tmp), refresh=True)
        self.assertEqual(len(usgs.calls), 24)

    def test_unsplittable_interval_raises(self):
        feats = [feat(f"e{i}", ms(2025, 5, 1, 0, 0, 0)) for i in range(6)]  # same instant
        usgs = FakeUsgs(feats)
        with patch.object(historical, "SERVICE_LIMIT", 5):
            with tempfile.TemporaryDirectory() as tmp:
                with self.assertRaises(historical.CannotSplitError):
                    historical.acquire_year(2025, fetch=usgs, data_dir=Path(tmp))


@unittest.skipUnless(is_postgres_available(), "PostgreSQL is not reachable")
class HistoricalLoadIntegrationTests(unittest.TestCase):
    def setUp(self):
        with psycopg.connect(**postgres_connection_parameters()) as conn:
            apply_migrations_sync(conn)
            conn.execute("DELETE FROM observatorio.historical_events")
            conn.execute("DELETE FROM observatorio.extraction_queries")

    def tearDown(self):
        self.setUp()

    def test_load_provenance_and_unique_rows(self):
        usgs = FakeUsgs([feat("edge", ms(2025, 4, 1)), feat("sea", ms(2025, 6, 15), lon=-140.0, lat=0.0)])
        with tempfile.TemporaryDirectory() as tmp:
            records, events = historical.acquire_year(2025, fetch=usgs, data_dir=Path(tmp))
            with psycopg.connect(**postgres_connection_parameters()) as conn:
                result = historical.load_to_db(conn, records, events, get_catalog())
                historical.load_to_db(conn, records, events, get_catalog())  # rerun is idempotent
            with psycopg.connect(**postgres_connection_parameters()) as conn:
                rows = conn.execute(
                    "SELECT event_id, country_id, query_id IS NOT NULL FROM observatorio.historical_events ORDER BY 1"
                ).fetchall()
                queries = conn.execute("SELECT count(*), sum(result_count) FROM observatorio.extraction_queries").fetchone()
        self.assertEqual(rows, [("edge", "JPN", True), ("sea", None, True)])
        self.assertEqual(result["events"], 2)
        self.assertEqual(queries[0], 12)
        self.assertEqual(queries[1], 3)  # 'edge' counted in two adjacent queries, 'sea' in one


if __name__ == "__main__":
    unittest.main()
