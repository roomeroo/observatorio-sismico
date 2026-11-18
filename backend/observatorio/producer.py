from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import TYPE_CHECKING

import httpx

from observatorio.poll_recorder import PollRecorder
from observatorio.publication_state import PublicationState
from observatorio.readiness import retry_until_ready
from observatorio.retry import retry_with_backoff
from observatorio.usgs_source import (
    GeoJsonFeature,
    USGS_FEED_URL,
    earthquake_features,
    exclusion_details,
    fetch_feed_or_skip,
    poll_interval_seconds,
    polling_loop,
)

if TYPE_CHECKING:
    from aiokafka import AIOKafkaProducer


KafkaSend = Callable[[str, bytes, bytes], Awaitable[object]]


async def publish_events(
    features: list[GeoJsonFeature],
    state: PublicationState,
    topic: str,
    send: KafkaSend,
    retryable_send_errors: tuple[type[Exception], ...],
    ingested_at_ms: Callable[[], int] = lambda: time.time_ns() // 1_000_000,
    retry_sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> int:
    published = 0
    for feature in earthquake_features(features):
        event_id = feature["id"]
        properties = feature["properties"]
        if not isinstance(event_id, str) or not isinstance(properties, dict):
            continue
        updated = properties.get("updated")
        if isinstance(updated, bool) or not isinstance(updated, int):
            continue
        if not state.should_publish(event_id, updated):
            continue

        envelope = {
            "source": USGS_FEED_URL,
            "ingested_at": ingested_at_ms(),
            "mode": "live",
            "event": feature,
        }
        key = event_id.encode("utf-8")
        value = json.dumps(
            envelope,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
        try:
            await retry_with_backoff(
                lambda: send(topic, key, value),
                f"Kafka publish for event {event_id}",
                retryable_send_errors,
                retry_sleep,
            )
        except retryable_send_errors as error:
            logging.error(
                "Leaving event %s unpublished after retry exhaustion: %s",
                event_id,
                error,
            )
            continue
        state.mark_published(event_id, updated)
        published += 1
    return published


async def poll_once(
    client: httpx.AsyncClient,
    state: PublicationState,
    topic: str,
    send: KafkaSend,
    retryable_send_errors: tuple[type[Exception], ...],
    source_retry_sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    send_retry_sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    recorder: PollRecorder | None = None,
) -> None:
    capture: dict = {}
    features = await fetch_feed_or_skip(client, source_retry_sleep, capture)
    if features is None:
        if recorder is not None:
            await recorder.record(
                "error",
                capture.get("latency_ms"),
                None,
                None,
                [],
                capture.get("error", "unknown error"),
                capture.get("payload"),
            )
        return
    published = await publish_events(
        features,
        state,
        topic,
        send,
        retryable_send_errors,
        retry_sleep=send_retry_sleep,
    )
    if recorder is not None:
        await recorder.record(
            "ok",
            capture.get("latency_ms"),
            len(features),
            published,
            exclusion_details(features),
            None,
            capture.get("payload"),
        )


async def main() -> None:
    from aiokafka import AIOKafkaProducer
    from aiokafka.errors import KafkaError

    logging.basicConfig(level=logging.INFO)
    bootstrap_servers = os.environ.get(
        "KAFKA_BOOTSTRAP_SERVERS",
        "kafka:9092",
    )
    topic = os.environ.get("KAFKA_TOPIC", "earthquakes-live")
    state_path = os.environ.get(
        "PRODUCER_STATE_PATH",
        "/var/lib/observatorio/publication-state.sqlite3",
    )

    async def connect_to_kafka() -> AIOKafkaProducer:
        producer = AIOKafkaProducer(bootstrap_servers=bootstrap_servers)
        await producer.start()
        return producer

    try:  # best effort: poll records are not critical for publication
        import psycopg
        from observatorio.database import postgres_connection_parameters
        from observatorio.migration import apply_migrations_sync

        with psycopg.connect(**postgres_connection_parameters(), connect_timeout=3) as conn:
            apply_migrations_sync(conn)
    except Exception as error:
        logging.error("Could not prepare poll log schema (publication continues): %s", error)

    with PublicationState(Path(state_path)) as state:
        producer = await retry_until_ready("Kafka producer", connect_to_kafka)
        try:
            async with httpx.AsyncClient() as client:
                async def send(
                    destination: str,
                    key: bytes,
                    value: bytes,
                ) -> object:
                    return await producer.send_and_wait(
                        destination,
                        key=key,
                        value=value,
                    )

                recorder = PollRecorder()
                last_purge = 0.0

                async def poll_cycle() -> None:
                    nonlocal last_purge
                    await poll_once(
                        client,
                        state,
                        topic,
                        send,
                        (KafkaError,),
                        recorder=recorder,
                    )
                    if time.monotonic() - last_purge >= 86400:
                        last_purge = time.monotonic()
                        await recorder.purge()

                await polling_loop(
                    poll_cycle,
                    poll_interval_seconds(),
                )
        finally:
            await producer.stop()


if __name__ == "__main__":
    asyncio.run(main())
