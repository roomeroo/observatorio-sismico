import sqlite3
from pathlib import Path


class PublicationState:
    def __init__(self, database_path: str | Path) -> None:
        self._connection = sqlite3.connect(database_path)
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS published_events (
                event_id TEXT PRIMARY KEY,
                updated INTEGER NOT NULL
            )
            """
        )
        self._connection.commit()

    def latest_updated(self, event_id: str) -> int | None:
        row = self._connection.execute(
            "SELECT updated FROM published_events WHERE event_id = ?",
            (event_id,),
        ).fetchone()
        return None if row is None else int(row[0])

    def should_publish(self, event_id: str, updated: int) -> bool:
        latest = self.latest_updated(event_id)
        return latest is None or updated > latest

    def mark_published(self, event_id: str, updated: int) -> None:
        self._connection.execute(
            """
            INSERT INTO published_events (event_id, updated)
            VALUES (?, ?)
            ON CONFLICT(event_id) DO UPDATE SET updated = excluded.updated
            WHERE excluded.updated > published_events.updated
            """,
            (event_id, updated),
        )
        self._connection.commit()

    def close(self) -> None:
        self._connection.close()

    def __enter__(self) -> "PublicationState":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
