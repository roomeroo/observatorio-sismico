"""Persistent, failure-tolerant record of producer polls (poll_log, exclusions, raw payloads).

Nothing here may stop publication: every database error is logged and swallowed.
"""

import asyncio
import hashlib
import json
import logging
from typing import Any, Optional

import psycopg
from psycopg.types.json import Jsonb

from observatorio.database import postgres_connection_parameters

logger = logging.getLogger(__name__)

DEFAULT_RETENTION_DAYS = 7


def payload_sha256(payload: Any) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class PollRecorder:
    def __init__(self, connect=None, retention_days: int = DEFAULT_RETENTION_DAYS):
        self._connect = connect or (
            lambda: psycopg.connect(**postgres_connection_parameters(), connect_timeout=3)
        )
        self.retention_days = retention_days

    def record_sync(
        self,
        status: str,
        latency_ms: Optional[int],
        feed_count: Optional[int],
        published_count: Optional[int],
        excluded: list[dict],
        error: Optional[str],
        payload: Any,
    ) -> Optional[int]:
        digest = payload_sha256(payload) if payload is not None else None
        with self._connect() as conn:
            with conn.transaction():
                with conn.cursor() as cur:
                    if digest is not None:
                        cur.execute(
                            """
                            INSERT INTO observatorio.raw_payloads (payload_hash, payload)
                            VALUES (%s, %s)
                            ON CONFLICT (payload_hash) DO UPDATE
                                SET last_seen_at = clock_timestamp();
                            """,
                            (digest, Jsonb(payload)),
                        )
                    cur.execute(
                        """
                        INSERT INTO observatorio.poll_log (
                            status, latency_ms, feed_count, published_count,
                            excluded_count, error, payload_hash
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id;
                        """,
                        (status, latency_ms, feed_count, published_count, len(excluded), error, digest),
                    )
                    poll_id = cur.fetchone()[0]
                    for item in excluded:
                        cur.execute(
                            """
                            INSERT INTO observatorio.poll_exclusions
                                (poll_id, event_id, reason, event_type, place)
                            VALUES (%s, %s, %s, %s, %s);
                            """,
                            (
                                poll_id,
                                item.get("event_id"),
                                item["reason"],
                                item.get("event_type"),
                                item.get("place"),
                            ),
                        )
        return poll_id

    def purge_sync(self) -> int:
        """Delete raw payloads not seen within the retention window.

        ``poll_log`` rows are kept (their ``payload_hash`` is cleared) so the
        metadata survives payload retention.
        """
        cond = "last_seen_at < clock_timestamp() - make_interval(days => %s)"
        with self._connect() as conn:
            with conn.transaction():
                with conn.cursor() as cur:
                    cur.execute(
                        "UPDATE observatorio.poll_log SET payload_hash = NULL WHERE payload_hash IN "
                        f"(SELECT payload_hash FROM observatorio.raw_payloads WHERE {cond})",
                        (self.retention_days,),
                    )
                    cur.execute(
                        f"DELETE FROM observatorio.raw_payloads WHERE {cond}",
                        (self.retention_days,),
                    )
                    return cur.rowcount

    async def record(self, *args, **kwargs) -> Optional[int]:
        try:
            return await asyncio.to_thread(self.record_sync, *args, **kwargs)
        except Exception as error:  # never block publication
            logger.error("Could not record poll in PostgreSQL (publication continues): %s", error)
            return None

    async def purge(self) -> Optional[int]:
        try:
            return await asyncio.to_thread(self.purge_sync)
        except Exception as error:
            logger.error("Could not purge old raw payloads: %s", error)
            return None
