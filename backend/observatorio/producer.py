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

from observatorio.publication_state import PublicationState
from observatorio.readiness import retry_until_ready
from observatorio.retry import retry_with_backoff
from observatorio.usgs_source import (
    GeoJsonFeature,
    USGS_FEED_URL,
    earthquake_features,
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
) -> None:
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


async def poll_once(
    client: httpx.AsyncClient,
    state: PublicationState,
    topic: str,
    send: KafkaSend,
    retryable_send_errors: tuple[type[Exception], ...],
    source_retry_sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    send_retry_sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> None:
    features = await fetch_feed_or_skip(client, source_retry_sleep)
    if features is None:
        return
    await publish_events(
        features,
        state,
        topic,
        send,
        retryable_send_errors,
        retry_sleep=send_retry_sleep,
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

                async def poll_cycle() -> None:
                    await poll_once(
                        client,
                        state,
                        topic,
                        send,
                        (KafkaError,),
                    )

                await polling_loop(
                    poll_cycle,
                    poll_interval_seconds(),
                )
        finally:
            await producer.stop()


if __name__ == "__main__":
    asyncio.run(main())
