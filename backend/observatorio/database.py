import os


def postgres_connection_parameters() -> dict[str, str]:
    return {
        "host": "postgres",
        "port": "5432",
        "dbname": os.environ["POSTGRES_DB"],
        "user": os.environ["POSTGRES_USER"],
        "password": os.environ["POSTGRES_PASSWORD"],
    }
