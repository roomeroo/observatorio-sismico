import os


def postgres_connection_parameters() -> dict[str, str]:
    return {
        "host": os.environ.get("POSTGRES_HOST", "postgres"),
        "port": os.environ.get("POSTGRES_PORT", "5432"),
        "dbname": os.environ["POSTGRES_DB"],
        "user": os.environ["POSTGRES_USER"],
        "password": os.environ["POSTGRES_PASSWORD"],
    }
