from contextlib import closing
import sqlite3
import tempfile
import unittest
from pathlib import Path

from observatorio.publication_state import PublicationState


class PublicationStateTests(unittest.TestCase):
    def test_published_versions_are_monotonic_and_persisted(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database_path = Path(directory) / "publication-state.sqlite3"

            with PublicationState(database_path) as state:
                self.assertIsNone(state.latest_updated("usgs-1"))
                self.assertTrue(state.should_publish("usgs-1", 100))
                state.mark_published("usgs-1", 100)

                self.assertEqual(state.latest_updated("usgs-1"), 100)
                self.assertFalse(state.should_publish("usgs-1", 100))
                self.assertTrue(state.should_publish("usgs-1", 101))
                self.assertFalse(state.should_publish("usgs-1", 99))

                state.mark_published("usgs-1", 99)
                self.assertEqual(state.latest_updated("usgs-1"), 100)

                state.mark_published("usgs-1", 101)
                self.assertEqual(state.latest_updated("usgs-1"), 101)

            with PublicationState(database_path) as reopened:
                self.assertEqual(reopened.latest_updated("usgs-1"), 101)

            with closing(sqlite3.connect(database_path)) as connection:
                columns = connection.execute(
                    "PRAGMA table_info(published_events)"
                ).fetchall()
                self.assertEqual([column[1] for column in columns], ["event_id", "updated"])


if __name__ == "__main__":
    unittest.main()
