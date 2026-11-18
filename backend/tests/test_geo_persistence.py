import asyncio
import dataclasses
import sys
import unittest

from psycopg import AsyncConnection

from observatorio.database import postgres_connection_parameters
from observatorio.geo import get_catalog
from observatorio.migration import apply_migrations
from observatorio.persistence import load_dim_country, persist_accepted_event
from test_persistence import PersistenceUnitTests
from test_postgres_integration import is_postgres_available

make_event = PersistenceUnitTests.make_event

if sys.platform == "win32":  # psycopg async cannot run on the Proactor loop
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

TEST_IDS = ("geo-test-sea", "geo-test-land")


@unittest.skipUnless(is_postgres_available(), "PostgreSQL is not reachable")
class GeoPersistenceIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.conn = await AsyncConnection.connect(**postgres_connection_parameters())
        await apply_migrations(self.conn)
        await self.conn.commit()
        await self._cleanup()

    async def asyncTearDown(self) -> None:
        await self._cleanup()
        await self.conn.close()

    async def _cleanup(self) -> None:
        async with self.conn.cursor() as cur:
            for table in ("event_versions", "current_events"):
                await cur.execute(
                    f"DELETE FROM observatorio.{table} WHERE event_id = ANY(%s)",
                    (list(TEST_IDS),),
                )
        await self.conn.commit()

    async def test_dim_country_is_idempotent_across_restarts(self) -> None:
        expected = len(get_catalog().countries)
        await load_dim_country(self.conn)
        await load_dim_country(self.conn)  # simulated consumer restart
        async with self.conn.cursor() as cur:
            await cur.execute("SELECT count(*), count(DISTINCT country_id) FROM observatorio.dim_country")
            total, distinct = await cur.fetchone()
        self.assertEqual(total, expected)
        self.assertEqual(distinct, expected)

    async def test_offshore_event_has_null_country_and_stays_current(self) -> None:
        # Open Pacific, outside every catalog polygon
        event = dataclasses.replace(make_event("geo-test-sea"), longitude=-140.0, latitude=0.0)
        async with self.conn.transaction():
            await persist_accepted_event(self.conn, event, "earthquakes-live", 0, 1, b"raw")
        async with self.conn.cursor() as cur:
            await cur.execute(
                "SELECT country_id, geo_ambiguous FROM observatorio.current_events WHERE event_id = %s",
                ("geo-test-sea",),
            )
            self.assertEqual(await cur.fetchone(), (None, False))
            await cur.execute(
                "SELECT country_id FROM observatorio.event_versions WHERE event_id = %s",
                ("geo-test-sea",),
            )
            self.assertEqual(await cur.fetchone(), (None,))

    async def test_land_event_is_enriched_and_populates_dim_date(self) -> None:
        event = dataclasses.replace(make_event("geo-test-land"), longitude=139.7, latitude=35.7)
        async with self.conn.transaction():
            await persist_accepted_event(self.conn, event, "earthquakes-live", 0, 2, b"raw")
            # Reprocessing the same message keeps the same assignment
            await persist_accepted_event(self.conn, event, "earthquakes-live", 0, 3, b"raw")
        async with self.conn.cursor() as cur:
            await cur.execute(
                "SELECT country_id FROM observatorio.current_events WHERE event_id = %s",
                ("geo-test-land",),
            )
            self.assertEqual(await cur.fetchone(), ("JPN",))
            await cur.execute(
                "SELECT count(*) FROM observatorio.dim_date WHERE date_key = %s",
                (event.time_utc.date(),),
            )
            self.assertEqual((await cur.fetchone())[0], 1)


if __name__ == "__main__":
    unittest.main()
