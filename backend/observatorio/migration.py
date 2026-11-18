import logging
from pathlib import Path
from psycopg import AsyncConnection, Connection

logger = logging.getLogger(__name__)

MIGRATIONS_DIR = Path(__file__).parent / "migrations"


def list_migration_files() -> list[tuple[str, str, Path]]:
    if not MIGRATIONS_DIR.exists():
        return []
    files = sorted(MIGRATIONS_DIR.glob("*.sql"))
    migrations: list[tuple[str, str, Path]] = []
    for path in files:
        version = path.stem.split("_")[0]
        migrations.append((version, path.name, path))
    return migrations


async def ensure_migrations_table(conn: AsyncConnection) -> None:
    async with conn.cursor() as cur:
        await cur.execute(
            """
            SELECT pg_advisory_xact_lock(727001);
            CREATE SCHEMA IF NOT EXISTS observatorio;
            CREATE TABLE IF NOT EXISTS observatorio.schema_migrations (
                version VARCHAR(255) PRIMARY KEY,
                name VARCHAR(255) NOT NULL,
                applied_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
            );
            """
        )


async def get_applied_versions(conn: AsyncConnection) -> set[str]:
    async with conn.cursor() as cur:
        await cur.execute("SELECT version FROM observatorio.schema_migrations")
        rows = await cur.fetchall()
        return {row[0] for row in rows}


async def apply_migrations(conn: AsyncConnection) -> list[str]:
    await ensure_migrations_table(conn)
    applied_versions = await get_applied_versions(conn)
    migrations = list_migration_files()
    newly_applied: list[str] = []

    for version, name, path in migrations:
        if version in applied_versions:
            continue
        logger.info("Applying migration %s (%s)...", version, name)
        sql = path.read_text(encoding="utf-8")
        async with conn.transaction():
            async with conn.cursor() as cur:
                await cur.execute("SELECT pg_advisory_xact_lock(727001)")
                await cur.execute(sql)
                await cur.execute(
                    """
                    INSERT INTO observatorio.schema_migrations (version, name)
                    VALUES (%s, %s)
                    ON CONFLICT (version) DO NOTHING;
                    """,
                    (version, name),
                )
        newly_applied.append(version)
        logger.info("Applied migration %s (%s).", version, name)

    return newly_applied


def ensure_migrations_table_sync(conn: Connection) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT pg_advisory_xact_lock(727001);
            CREATE SCHEMA IF NOT EXISTS observatorio;
            CREATE TABLE IF NOT EXISTS observatorio.schema_migrations (
                version VARCHAR(255) PRIMARY KEY,
                name VARCHAR(255) NOT NULL,
                applied_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
            );
            """
        )


def get_applied_versions_sync(conn: Connection) -> set[str]:
    with conn.cursor() as cur:
        cur.execute("SELECT version FROM observatorio.schema_migrations")
        rows = cur.fetchall()
        return {row[0] for row in rows}


def apply_migrations_sync(conn: Connection) -> list[str]:
    ensure_migrations_table_sync(conn)
    applied_versions = get_applied_versions_sync(conn)
    migrations = list_migration_files()
    newly_applied: list[str] = []

    for version, name, path in migrations:
        if version in applied_versions:
            continue
        logger.info("Applying migration %s (%s)...", version, name)
        sql = path.read_text(encoding="utf-8")
        with conn.transaction():
            with conn.cursor() as cur:
                cur.execute("SELECT pg_advisory_xact_lock(727001)")
                cur.execute(sql)
                cur.execute(
                    """
                    INSERT INTO observatorio.schema_migrations (version, name)
                    VALUES (%s, %s)
                    ON CONFLICT (version) DO NOTHING;
                    """,
                    (version, name),
                )
        newly_applied.append(version)
        logger.info("Applied migration %s (%s).", version, name)

    return newly_applied
