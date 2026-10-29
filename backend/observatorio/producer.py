import asyncio
import logging
import os

from aiokafka import AIOKafkaProducer

from observatorio.readiness import retry_until_ready


async def main() -> None:
    logging.basicConfig(level=logging.INFO)
    bootstrap_servers = os.environ.get(
        "KAFKA_BOOTSTRAP_SERVERS",
        "kafka:9092",
    )

    async def connect_to_kafka() -> AIOKafkaProducer:
        producer = AIOKafkaProducer(bootstrap_servers=bootstrap_servers)
        await producer.start()
        return producer

    producer = await retry_until_ready("Kafka producer", connect_to_kafka)
    logging.info("Producer scaffold ready; USGS ingestion is not implemented.")
    try:
        await asyncio.Event().wait()
    finally:
        await producer.stop()


if __name__ == "__main__":
    asyncio.run(main())
