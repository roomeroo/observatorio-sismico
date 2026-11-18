"""Accelerated historical replay (one-shot command).

    docker compose run --rm producer python -m observatorio.replay \
        --from 2025-03-28T00:00:00Z --to 2025-03-28T06:00:00Z --speed 600

Events of the interval (by occurrence time) are read from ``historical_events``
and published in ascending time order to the replay topic with the original
inter-event gap divided by ``--speed``. Each message carries ``mode: replay`` and a
``replayed_at`` timestamp. One duplicate and one older revision of the first
event are appended so the consumer's idempotency can be demonstrated: the final
replay current-state count equals the number of unique events.

Replay data lives in the isolated ``replay`` PostgreSQL schema and is exposed by
the API only with ``mode=replay``; live tables and ``last_ingestion`` are never touched.
"""

import argparse
import asyncio
import json
import logging
import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Optional

import psycopg

from observatorio.database import postgres_connection_parameters
from observatorio.migration import apply_migrations_sync

logger = logging.getLogger(__name__)

REPLAY_SOURCE = "usgs-historical-replay"
DEFAULT_TOPIC = "earthquakes-replay"


@dataclass(frozen=True)
class ReplayMessage:
    delay_seconds: float  # wait BEFORE publishing this message
    key: bytes
    value: bytes
    kind: str  # "event" | "duplicate" | "older_revision"


def feature_from_row(row: tuple) -> Optional[dict[str, Any]]:
    event_id, time_utc, updated_utc, mag, mag_type, place, event_type, lon, lat, depth = row
    if time_utc is None or updated_utc is None or depth is None:
        return None  # would be quarantined by validation: not replayable
    return {
        "type": "Feature",
        "id": event_id,
        "geometry": {"type": "Point", "coordinates": [lon, lat, depth]},
        "properties": {
            "mag": mag,
            "magType": mag_type,
            "place": place,
            "time": int(time_utc.timestamp() * 1000),
            "updated": int(updated_utc.timestamp() * 1000),
            "type": event_type or "earthquake",
        },
    }


def _envelope(feature: dict, now_ms: int) -> bytes:
    return json.dumps(
        {
            "source": REPLAY_SOURCE,
            "ingested_at": now_ms,
            "replayed_at": now_ms,
            "mode": "replay",
            "event": feature,
        },
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def build_messages(
    features: list[dict[str, Any]],
    speed: float,
    duplicates: int = 1,
    stale_revisions: int = 1,
    now_ms: Callable[[], int] = lambda: time.time_ns() // 1_000_000,
) -> list[ReplayMessage]:
    if speed <= 0:
        raise ValueError("speed must be greater than zero")
    ordered = sorted(features, key=lambda f: (f["properties"]["time"], f["id"]))
    messages: list[ReplayMessage] = []
    previous_time: Optional[int] = None
    for feature in ordered:
        t = feature["properties"]["time"]
        gap = 0.0 if previous_time is None else max(0, t - previous_time) / 1000.0
        previous_time = t
        messages.append(
            ReplayMessage(gap / speed, feature["id"].encode(), _envelope(feature, now_ms()), "event")
        )
    if ordered:
        first = ordered[0]
        for _ in range(duplicates):
            messages.append(ReplayMessage(0.0, first["id"].encode(), _envelope(first, now_ms()), "duplicate"))
        for i in range(stale_revisions):
            older = json.loads(json.dumps(first))
            older["properties"]["updated"] = first["properties"]["updated"] - 1000 * (i + 1)
            older["properties"]["mag"] = (first["properties"]["mag"] or 0) + 1  # visibly different
            messages.append(ReplayMessage(0.0, first["id"].encode(), _envelope(older, now_ms()), "older_revision"))
    return messages


async def publish(
    messages: list[ReplayMessage],
    send: Callable[[bytes, bytes], Awaitable[object]],
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> int:
    sent = 0
    for message in messages:
        if message.delay_seconds > 0:
            await sleep(message.delay_seconds)
        await send(message.key, message.value)
        sent += 1
    return sent


def load_features(conn: psycopg.Connection, start: datetime, end: datetime) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT event_id, time_utc, updated_utc, mag, mag_type, place, event_type,
               longitude, latitude, depth
        FROM observatorio.historical_events
        WHERE time_utc >= %s AND time_utc < %s
        ORDER BY time_utc, event_id
        """,
        (start, end),
    ).fetchall()
    features = [f for f in (feature_from_row(r) for r in rows) if f is not None]
    skipped = len(rows) - len(features)
    if skipped:
        logger.warning("%d historical events skipped (missing time/updated/depth).", skipped)
    return features


def reset_replay_schema(conn: psycopg.Connection) -> None:
    conn.execute("TRUNCATE replay.event_versions, replay.current_events, replay.quarantine_records")


def parse_instant(value: str) -> datetime:
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


async def run(args: argparse.Namespace) -> None:
    from aiokafka import AIOKafkaProducer
    from aiokafka.admin import AIOKafkaAdminClient, NewTopic
    from aiokafka.errors import TopicAlreadyExistsError

    start, end = parse_instant(args.start), parse_instant(args.end)
    bootstrap = os.environ.get("KAFKA_BOOTSTRAP_SERVERS", "kafka:9092")
    topic = args.topic or os.environ.get("KAFKA_REPLAY_TOPIC", DEFAULT_TOPIC)

    with psycopg.connect(**postgres_connection_parameters(), connect_timeout=5, autocommit=True) as conn:
        apply_migrations_sync(conn)
        features = load_features(conn, start, end)
        if not args.keep:
            reset_replay_schema(conn)
    if not features:
        raise SystemExit("No historical events in that interval. Run observatorio.historical first.")

    messages = build_messages(features, args.speed, args.duplicates, args.stale_revisions)
    total_delay = sum(m.delay_seconds for m in messages)
    logger.info(
        "Replaying %d events (%d messages) from %s to %s at x%g; expected duration %.0f s.",
        len(features), len(messages), start.isoformat(), end.isoformat(), args.speed, total_delay,
    )

    admin = AIOKafkaAdminClient(bootstrap_servers=bootstrap)
    await admin.start()
    try:
        await admin.create_topics([NewTopic(topic, num_partitions=1, replication_factor=1)])
    except TopicAlreadyExistsError:
        pass
    finally:
        await admin.close()

    producer = AIOKafkaProducer(bootstrap_servers=bootstrap)
    await producer.start()
    try:
        sent = await publish(messages, lambda k, v: producer.send_and_wait(topic, key=k, value=v))
    finally:
        await producer.stop()
    logger.info("Replay finished: %d messages published to %s (%d unique events expected).",
                sent, topic, len(features))


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--from", dest="start", required=True, help="start of occurrence interval (UTC, inclusive)")
    p.add_argument("--to", dest="end", required=True, help="end of occurrence interval (UTC, exclusive)")
    p.add_argument("--speed", type=float, default=60.0, help="speed factor (60 = one minute of history per second)")
    p.add_argument("--duplicates", type=int, default=1)
    p.add_argument("--stale-revisions", type=int, default=1)
    p.add_argument("--topic", default=None)
    p.add_argument("--keep", action="store_true", help="do not clear the replay schema first")
    asyncio.run(run(p.parse_args()))


if __name__ == "__main__":
    main()
