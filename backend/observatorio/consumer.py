import asyncio
import logging
from collections.abc import Awaitable, Callable
import os
from typing import Any, Optional

from aiokafka import AIOKafkaConsumer, TopicPartition
from psycopg import AsyncConnection

from observatorio.database import postgres_connection_parameters
from observatorio.migration import apply_migrations
from observatorio.persistence import (
    LIVE_SCHEMA,
    REPLAY_SCHEMA,
    load_dim_country,
    persist_accepted_event,
    record_quarantine,
)
from observatorio.readiness import retry_until_ready
from observatorio.validation import validate_message_bytes

logger = logging.getLogger(__name__)


def schema_for_topic(topic: str, replay_topic: Optional[str]) -> str:
    """Replay topic -> isolated ``replay`` schema; everything else -> live schema."""
    return REPLAY_SCHEMA if replay_topic and topic == replay_topic else LIVE_SCHEMA


async def process_single_record(
    connection: AsyncConnection,
    topic: str,
    partition: int,
    offset: int,
    raw_payload: bytes,
    schema: str = LIVE_SCHEMA,
) -> None:
    result = validate_message_bytes(raw_payload)
    async with connection.transaction():
        if result.is_valid and result.event is not None:
            await persist_accepted_event(
                connection,
                result.event,
                topic,
                partition,
                offset,
                raw_payload,
                schema=schema,
            )
        else:
            await record_quarantine(
                connection,
                topic,
                partition,
                offset,
                raw_payload,
                result.rejection_reason or "UNKNOWN",
                result.decoded_envelope,
                schema,
            )


async def run_consumer(
    consumer: AIOKafkaConsumer,
    connect_pg: Callable[[], Awaitable[AsyncConnection]],
    topic: str,
    stop_event: Optional[asyncio.Event] = None,
    replay_topic: Optional[str] = None,
) -> None:
    connection = await retry_until_ready("Consumer PostgreSQL", connect_pg)
    try:
        await apply_migrations(connection)
        loaded = await load_dim_country(connection)
        logger.info("Country dimension loaded (%d countries).", loaded)
    except Exception as error:
        logger.error("Failed to apply schema migrations (%s)", error)
        await connection.close()
        raise

    topics = [topic] + ([replay_topic] if replay_topic else [])
    consumer.subscribe(topics)
    logger.info("Subscribed to Kafka topics: %s", ", ".join(topics))

    try:
        while stop_event is None or not stop_event.is_set():
            try:
                if stop_event is not None:
                    try:
                        msg = await asyncio.wait_for(consumer.getone(), timeout=0.5)
                    except asyncio.TimeoutError:
                        continue
                else:
                    msg = await consumer.getone()
            except Exception:
                if stop_event is not None and stop_event.is_set():
                    break
                raise

            processed = False
            while not processed and (stop_event is None or not stop_event.is_set()):
                try:
                    await process_single_record(
                        connection,
                        msg.topic,
                        msg.partition,
                        msg.offset,
                        msg.value,
                        schema_for_topic(msg.topic, replay_topic),
                    )
                    tp = TopicPartition(msg.topic, msg.partition)
                    await consumer.commit({tp: msg.offset + 1})
                    processed = True
                except Exception as error:
                    logger.warning(
                        "PostgreSQL error while processing record %s:%d:%d (%s). Retrying after reconnection...",
                        msg.topic,
                        msg.partition,
                        msg.offset,
                        error,
                    )
                    try:
                        await connection.close()
                    except Exception:
                        pass
                    connection = await retry_until_ready("Consumer PostgreSQL", connect_pg)
    finally:
        await connection.close()


async def main() -> None:
    logging.basicConfig(level=logging.INFO)
    bootstrap_servers = os.environ.get(
        "KAFKA_BOOTSTRAP_SERVERS",
        "kafka:9092",
    )
    topic = os.environ.get("KAFKA_TOPIC", "earthquakes-live")
    replay_topic = os.environ.get("KAFKA_REPLAY_TOPIC", "earthquakes-replay") or None

    async def connect_to_kafka() -> AIOKafkaConsumer:
        consumer = AIOKafkaConsumer(
            bootstrap_servers=bootstrap_servers,
            group_id="observatorio-consumer",
            enable_auto_commit=False,
            auto_offset_reset="earliest",
            metadata_max_age_ms=10000,  # notice the replay topic soon after it is created
        )
        await consumer.start()
        return consumer

    consumer = await retry_until_ready("Kafka consumer", connect_to_kafka)
    try:
        await run_consumer(
            consumer=consumer,
            connect_pg=lambda: AsyncConnection.connect(
                **postgres_connection_parameters(),
                connect_timeout=3,
                autocommit=True,  # transaction() blocks must be real transactions
            ),
            topic=topic,
            replay_topic=replay_topic,
        )
    finally:
        await consumer.stop()


if __name__ == "__main__":
    asyncio.run(main())
