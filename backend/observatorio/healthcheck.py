import argparse
import asyncio
import os
import socket

from aiokafka import AIOKafkaProducer
from psycopg import AsyncConnection

from observatorio.database import postgres_connection_parameters


async def check_kafka() -> None:
    producer = AIOKafkaProducer(
        bootstrap_servers=os.environ.get(
            "KAFKA_BOOTSTRAP_SERVERS",
            "kafka:9092",
        )
    )
    await producer.start()
    await producer.stop()


async def check_postgres() -> None:
    connection = await AsyncConnection.connect(
        **postgres_connection_parameters(),
        connect_timeout=3,
    )
    try:
        await connection.execute("SELECT 1")
    finally:
        await connection.close()


async def check_service(service: str) -> None:
    if service in {"producer", "consumer"}:
        await check_kafka()
    if service in {"consumer", "api"}:
        await check_postgres()
    if service == "api":
        with socket.create_connection(("127.0.0.1", 8000), timeout=2):
            pass


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("service", choices=("producer", "consumer", "api"))
    args = parser.parse_args()
    asyncio.run(check_service(args.service))


if __name__ == "__main__":
    main()
