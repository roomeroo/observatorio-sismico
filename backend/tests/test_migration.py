import unittest
from unittest.mock import AsyncMock, MagicMock

from observatorio.migration import (
    apply_migrations,
    apply_migrations_sync,
    list_migration_files,
)


class MigrationUnitTests(unittest.TestCase):
    def test_list_migration_files_in_order(self) -> None:
        files = list_migration_files()
        self.assertGreaterEqual(len(files), 3)
        versions = [f[0] for f in files]
        self.assertEqual(versions[:3], ["0001", "0002", "0003"])
        names = [f[1] for f in files]
        self.assertEqual(names[:3], ["0001_initial_schema.sql", "0002_event_tables.sql", "0003_geo_history_logging.sql"])

    def test_apply_migrations_sync_applies_and_is_idempotent(self) -> None:
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        mock_conn.transaction.return_value.__enter__.return_value = None

        # First run: no applied versions
        mock_cursor.fetchall.return_value = []
        applied = apply_migrations_sync(mock_conn)
        self.assertIn("0001", applied)
        self.assertIn("0002", applied)
        self.assertIn("0003", applied)
        self.assertIn("0004", applied)

        # Second run: all versions already applied
        mock_cursor.fetchall.return_value = [("0001",), ("0002",), ("0003",), ("0004",)]
        re_applied = apply_migrations_sync(mock_conn)
        self.assertEqual(re_applied, [])


class MigrationAsyncUnitTests(unittest.IsolatedAsyncioTestCase):
    async def test_apply_migrations_async_applies_and_is_idempotent(self) -> None:
        mock_conn = MagicMock()
        mock_cursor = AsyncMock()

        # Context manager for cursor
        mock_cursor_cm = MagicMock()
        mock_cursor_cm.__aenter__ = AsyncMock(return_value=mock_cursor)
        mock_cursor_cm.__aexit__ = AsyncMock(return_value=None)
        mock_conn.cursor.return_value = mock_cursor_cm

        # Context manager for transaction
        mock_tx_cm = MagicMock()
        mock_tx_cm.__aenter__ = AsyncMock(return_value=None)
        mock_tx_cm.__aexit__ = AsyncMock(return_value=None)
        mock_conn.transaction.return_value = mock_tx_cm

        # First run: no versions
        mock_cursor.fetchall.return_value = []
        applied = await apply_migrations(mock_conn)
        self.assertIn("0001", applied)
        self.assertIn("0002", applied)
        self.assertIn("0003", applied)
        self.assertIn("0004", applied)

        # Second run: already applied
        mock_cursor.fetchall.return_value = [("0001",), ("0002",), ("0003",), ("0004",)]
        re_applied = await apply_migrations(mock_conn)
        self.assertEqual(re_applied, [])


if __name__ == "__main__":
    unittest.main()
