import asyncio
import logging
import os

from aiokafka import AIOKafkaConsumer
from psycopg import AsyncConnection

from observatorio.database import postgres_connection_parameters
from observatorio.readiness import retry_until_ready


async def main() -> None:
    logging.basicConfig(level=logging.INFO)
    bootstrap_servers = os.environ.get(
        "KAFKA_BOOTSTRAP_SERVERS",
        "kafka:9092",
    )
    async def connect_to_kafka() -> AIOKafkaConsumer:
        consumer = AIOKafkaConsumer(
            bootstrap_servers=bootstrap_servers,
            group_id="observatorio-consumer",
            enable_auto_commit=False,
        )
        await consumer.start()
        return consumer

    consumer = await retry_until_ready("Kafka consumer", connect_to_kafka)
    try:
        connection = await retry_until_ready(
            "Consumer PostgreSQL",
            lambda: AsyncConnection.connect(
                **postgres_connection_parameters(),
                connect_timeout=3,
            ),
        )
    except BaseException:
        await consumer.stop()
        raise

    logging.info(
        "Consumer scaffold ready; event processing is not implemented."
    )
    try:
        await asyncio.Event().wait()
    finally:
        await connection.close()
        await consumer.stop()


if __name__ == "__main__":
    asyncio.run(main())
