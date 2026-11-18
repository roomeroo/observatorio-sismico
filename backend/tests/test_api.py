import asyncio
import dataclasses
import os
import sys
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

import psycopg
from fastapi.testclient import TestClient
from psycopg import AsyncConnection

from observatorio.database import postgres_connection_parameters
from observatorio.geo import CountryCatalog
from observatorio.migration import apply_migrations_sync
from observatorio.persistence import persist_accepted_event
from test_persistence import PersistenceUnitTests
from test_postgres_integration import is_postgres_available

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

make_event = PersistenceUnitTests.make_event
PREFIX = "apitest-"
NETLIFY = "https://observatorio.netlify.app"
ZZZ = CountryCatalog(
    [
        {
            "type": "Feature",
            "properties": {"ADM0_A3": "ZZZ", "NAME_ES": "Zedlandia", "CONTINENT": "T", "SUBREGION": "Testland"},
            "geometry": {"type": "Polygon", "coordinates": [[[100, 0], [110, 0], [110, 10], [100, 10], [100, 0]]]},
        }
    ]
)
P0 = {"start": "1990-01-01T00:00:00Z", "end": "1990-01-01T06:00:00Z"}


def ms(hour, minute=0, day=1):
    return int(datetime(1990, 1, day, hour, minute, tzinfo=timezone.utc).timestamp() * 1000)


def event(suffix, t, updated=None, mag=4.0, depth=10.0, lon=105.0, lat=5.0):
    e = make_event(PREFIX + suffix, updated=updated or t + 1000, time=t, mag=mag)
    return dataclasses.replace(e, depth=depth, longitude=lon, latitude=lat)


async def seed(events):
    conn = await AsyncConnection.connect(**postgres_connection_parameters(), autocommit=True)
    try:
        for i, e in enumerate(events):
            async with conn.transaction():
                await persist_accepted_event(conn, e, "earthquakes-live", 0, i, b"raw", catalog=ZZZ)
    finally:
        await conn.close()


def cleanup(with_country=True):
    with psycopg.connect(**postgres_connection_parameters(), autocommit=True) as conn:
        conn.execute("DELETE FROM observatorio.dim_country WHERE country_id = 'ZZZ'")
        if with_country:
            conn.execute(
                "INSERT INTO observatorio.dim_country (country_id, name, continent, subregion) "
                "VALUES ('ZZZ', 'Zedlandia', 'T', 'Testland')"
            )
        for t in ("event_versions", "current_events"):
            conn.execute(f"DELETE FROM observatorio.{t} WHERE event_id LIKE %s", (PREFIX + "%",))
        conn.execute("DELETE FROM observatorio.historical_events WHERE event_id LIKE %s", (PREFIX + "%",))


@unittest.skipUnless(is_postgres_available(), "PostgreSQL is not reachable")
class ApiIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with psycopg.connect(**postgres_connection_parameters()) as conn:
            apply_migrations_sync(conn)
        cleanup()
        os.environ["CORS_ALLOWED_ORIGINS"] = f"{NETLIFY},http://localhost:4200"
        import importlib
        import observatorio.api as api

        cls.api = importlib.reload(api)
        cls.client_cm = TestClient(cls.api.app)
        cls.client = cls.client_cm.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.client_cm.__exit__(None, None, None)
        cleanup(with_country=False)

    def setUp(self):
        cleanup()

    # --- events ---
    def test_events_geojson_filters_pagination_and_nulls(self):
        asyncio.run(seed([
            event("a", ms(0, 10), mag=5.0),
            event("b", ms(1, 20), mag=None),
            event("c", ms(2, 30), mag=3.0, lon=-140.0, lat=0.0),  # offshore
        ]))
        r = self.client.get("/api/eventos", params={**P0, "limit": 2})
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["type"], "FeatureCollection")
        md = body["metadata"]
        self.assertEqual(md["total"], 3)
        self.assertEqual(len(body["features"]), 2)
        self.assertEqual((md["limit"], md["offset"], md["count"]), (2, 0, 2))
        self.assertTrue(md["truncated"])
        self.assertIsInstance(md["generated"], int)
        self.assertIn("last_ingestion", md)
        self.assertEqual(md["null_magnitude_excluded"], 0)
        page2 = self.client.get("/api/eventos", params={**P0, "limit": 2, "offset": 2}).json()
        self.assertEqual(len(page2["features"]), 1)
        self.assertFalse(page2["metadata"]["truncated"])
        by_id = {f["id"]: f for f in self.client.get("/api/eventos", params=P0).json()["features"]}
        self.assertIsNone(by_id[PREFIX + "b"]["properties"]["mag"])  # null magnitude kept
        self.assertIsNone(by_id[PREFIX + "c"]["properties"]["country_name"])
        self.assertEqual(by_id[PREFIX + "a"]["properties"]["country_name"], "Zedlandia")
        self.assertIsInstance(by_id[PREFIX + "a"]["properties"]["time"], int)
        self.assertEqual(by_id[PREFIX + "a"]["properties"]["magType"], "mw")
        self.assertEqual(by_id[PREFIX + "a"]["properties"]["country_id"], "ZZZ")
        self.assertEqual(by_id[PREFIX + "a"]["geometry"]["coordinates"][:2], [105.0, 5.0])
        # filters
        mag = self.client.get("/api/eventos", params={**P0, "min_mag": 4.5}).json()
        self.assertEqual([f["id"] for f in mag["features"]], [PREFIX + "a"])
        # the null-magnitude event cannot satisfy min_mag: counted separately, not dropped silently
        self.assertEqual(mag["metadata"]["null_magnitude_excluded"], 1)
        stats_mag = self.client.get("/api/estadisticas", params={**P0, "min_mag": 4.5}).json()
        self.assertEqual(stats_mag["missing"]["null_magnitude_excluded_by_min_mag"], 1)
        none = self.client.get("/api/eventos", params={**P0, "country_id": "SIN_PAIS"}).json()
        self.assertEqual([f["id"] for f in none["features"]], [PREFIX + "c"])
        sub = self.client.get("/api/eventos", params={**P0, "subregion": "Testland"}).json()
        self.assertEqual(sub["metadata"]["total"], 2)

    def test_default_period_is_last_24_hours_and_contract_shape(self):
        r = self.client.get("/api/eventos")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.headers["content-type"].startswith("application/json"))
        md = r.json()["metadata"]
        self.assertEqual(md["mode"], "live")
        self.assertEqual(md["period"]["end"][:10] >= md["period"]["start"][:10], True)
        start = datetime.fromisoformat(md["period"]["start"].replace("Z", "+00:00"))
        end = datetime.fromisoformat(md["period"]["end"].replace("Z", "+00:00"))
        self.assertEqual((end - start).total_seconds(), 86400)
        for key in ("generated", "count", "truncated"):
            self.assertIn(key, md)
        # 1990 events never appear in the default window
        asyncio.run(seed([event("old", ms(0, 10))]))
        ids = [f["id"] for f in self.client.get("/api/eventos").json()["features"]]
        self.assertNotIn(PREFIX + "old", ids)

    def test_statistics_report_period_unit_and_missing(self):
        asyncio.run(seed([event("p1", ms(0, 10), mag=None)]))
        s = self.client.get("/api/estadisticas", params=P0).json()
        self.assertIn("unit", s)
        self.assertEqual(s["period"]["start"], "1990-01-01T00:00:00Z")
        self.assertEqual(s["missing"]["magnitude"], 1)
        self.assertIn("filters", s)
        self.assertIsInstance(s["generated"], int)

    def test_unknown_country_is_empty_valid_result(self):
        r = self.client.get("/api/eventos", params={**P0, "country_id": "QQQ"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["metadata"]["total"], 0)
        self.assertEqual(r.json()["features"], [])
        s = self.client.get("/api/estadisticas", params={**P0, "country_id": "QQQ"})
        self.assertEqual(s.status_code, 200)
        self.assertEqual(s.json()["total"], 0)

    def test_invalid_filters_yield_422(self):
        for params in (
            {"min_mag": "abc"}, {"limit": 0}, {"offset": -1}, {"start": "no-es-fecha"},
            {"mode": "otro"}, {"start": P0["end"], "end": P0["start"]},
        ):
            self.assertEqual(self.client.get("/api/eventos", params=params).status_code, 422, params)
        self.assertEqual(
            self.client.get("/api/estadisticas", params={"start": "2020-01-01T00:00:00Z", "end": "2021-01-01T00:00:00Z"}).status_code,
            422,
        )

    # --- statistics ---
    def test_revision_does_not_inflate_counts(self):
        asyncio.run(seed([
            event("rev", ms(0, 10), updated=ms(0, 11)),
            event("rev", ms(3, 40), updated=ms(5, 0)),  # later revision moved the event time
        ]))
        s = self.client.get("/api/estadisticas", params=P0).json()
        self.assertEqual(s["total"], 1)
        counts = {h["hour_utc"]: h["count"] for h in s["hourly"]}
        self.assertEqual(counts["1990-01-01T03:00:00Z"], 1)
        self.assertEqual(counts["1990-01-01T00:00:00Z"], 0)
        self.assertEqual(sum(counts.values()), 1)

    def test_hourly_windows_include_empty_hours(self):
        asyncio.run(seed([event("h", ms(1, 5)), event("h2", ms(1, 55)), event("h3", ms(4, 0))]))
        s = self.client.get("/api/estadisticas", params=P0).json()
        self.assertEqual(len(s["hourly"]), 6)
        counts = [h["count"] for h in s["hourly"]]
        self.assertEqual(counts, [0, 2, 0, 0, 1, 0])
        self.assertTrue(s["hourly"][0]["hour_utc"].endswith("T00:00:00Z"))

    def test_distributions_and_country_breakdown_with_missing(self):
        asyncio.run(seed([
            event("m1", ms(0, 1), mag=4.2, depth=5.0),
            event("m2", ms(0, 2), mag=4.9, depth=50.0),
            event("m3", ms(0, 3), mag=None, depth=400.0),
            event("m4", ms(0, 4), mag=6.1, depth=800.0, lon=-140.0, lat=0.0),
        ]))
        s = self.client.get("/api/estadisticas", params=P0).json()
        self.assertEqual(s["total"], 4)
        mags = {b["from"]: b["count"] for b in s["magnitude"]["bins"]}
        self.assertEqual(mags, {4: 2, 6: 1})
        self.assertEqual(s["magnitude"]["missing"], 1)
        depth = {b["label"]: b["count"] for b in s["depth"]["bins"]}
        self.assertEqual(depth["<10 km"], 1)
        self.assertEqual(depth["35 a <70 km"], 1)
        self.assertEqual(depth["300 a <700 km"], 1)
        self.assertEqual(depth[">=700 km"], 1)
        self.assertEqual(s["depth"]["missing"], 0)
        countries = {c["country_id"]: c["count"] for c in s["by_country"]}
        self.assertEqual(countries, {"ZZZ": 3, None: 1})
        names = {c["country"] for c in s["by_country"]}
        self.assertIn("Sin país asignado", names)
        subs = {c["subregion"]: c["count"] for c in s["by_subregion"]}
        self.assertEqual(subs, {"Testland": 3, "Sin país asignado": 1})

    def test_historical_comparison_uses_365_days(self):
        with psycopg.connect(**postgres_connection_parameters(), autocommit=True) as conn:
            for i in range(73):
                conn.execute(
                    "INSERT INTO observatorio.historical_events (event_id, time_utc, updated_utc, mag, longitude, latitude, country_id) "
                    "VALUES (%s, '2025-06-01T00:00:00Z', '2025-06-01T00:00:00Z', 4.5, 105, 5, 'ZZZ')",
                    (f"{PREFIX}hist{i}",),
                )
        s = self.client.get("/api/estadisticas", params={**P0, "country_id": "ZZZ", "min_mag": 4}).json()
        c = s["comparison"]
        self.assertEqual(c["historical_count"], 73)
        self.assertEqual(c["historical_days"], 365)
        self.assertAlmostEqual(c["historical_daily_mean"], 0.2)
        self.assertEqual(c["last_24h_count"], 0)
        self.assertEqual(c["ratio"], 0.0)
        self.assertIn("incompleto", c["note"])

    # --- health, surface, CORS ---
    def test_health_has_ingestion_and_no_credentials(self):
        asyncio.run(seed([event("s", ms(0, 1))]))
        r = self.client.get("/api/salud")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        for key in ("status", "last_ingestion", "period", "events", "generated"):
            self.assertIn(key, body)
        self.assertIsInstance(body["last_ingestion"], int)
        text = r.text
        params = postgres_connection_parameters()
        self.assertNotIn(params["password"], text)
        self.assertNotIn("password", text.lower())

    def test_cors_allowed_and_unlisted_origins(self):
        headers = {
            "Origin": NETLIFY,
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "ngrok-skip-browser-warning",
        }
        ok = self.client.options("/api/eventos", headers=headers)
        self.assertEqual(ok.status_code, 200)
        self.assertEqual(ok.headers["access-control-allow-origin"], NETLIFY)
        self.assertIn("ngrok-skip-browser-warning", ok.headers["access-control-allow-headers"].lower())
        bad = self.client.options("/api/eventos", headers={**headers, "Origin": "https://evil.example"})
        self.assertNotIn("access-control-allow-origin", bad.headers)
        get = self.client.get("/api/salud", headers={"Origin": "https://evil.example"})
        self.assertNotIn("access-control-allow-origin", get.headers)
        self.assertNotEqual(ok.headers["access-control-allow-origin"], "*")

    def test_websocket_and_broadcast_routes_are_gone(self):
        self.assertEqual(self.client.get("/ws/earthquakes").status_code, 404)
        self.assertEqual(self.client.post("/ws/earthquakes/broadcast", json={}).status_code, 404)

    def test_only_expected_public_routes(self):
        paths = {r.path for r in self.api.app.routes if hasattr(r, "methods")}
        self.assertTrue({"/api/eventos", "/api/estadisticas", "/api/salud"} <= paths)
        self.assertFalse([p for p in paths if p.startswith(("/ws", "/admin"))])


class DatabaseDownTests(unittest.TestCase):
    def test_unreachable_postgres_yields_explicit_503(self):
        env = {**postgres_connection_parameters_for_test(), "POSTGRES_PORT": "1", "POSTGRES_HOST": "127.0.0.1"}
        with patch.dict(os.environ, env):
            import observatorio.api as api

            with TestClient(api.app) as client:
                for path in ("/api/eventos", "/api/estadisticas", "/api/salud"):
                    r = client.get(path)
                    self.assertEqual(r.status_code, 503, path)
                    self.assertIn("base de datos", r.json()["detail"])
                    self.assertEqual(r.headers.get("retry-after"), "5")


def postgres_connection_parameters_for_test():
    return {
        "POSTGRES_DB": os.environ.get("POSTGRES_DB", "x"),
        "POSTGRES_USER": os.environ.get("POSTGRES_USER", "x"),
        "POSTGRES_PASSWORD": os.environ.get("POSTGRES_PASSWORD", "x"),
    }


if __name__ == "__main__":
    unittest.main()
