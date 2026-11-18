import logging
from datetime import datetime, timezone
from typing import Any, Optional
from psycopg import AsyncConnection
from psycopg.types.json import Jsonb

from observatorio.geo import CountryCatalog, get_catalog
from observatorio.validation import (
    REASON_PAYLOAD_CONFLICT_SAME_VERSION,
    ValidatedEvent,
)

logger = logging.getLogger(__name__)

LIVE_SCHEMA = "observatorio"
REPLAY_SCHEMA = "replay"
VALID_SCHEMAS = {LIVE_SCHEMA, REPLAY_SCHEMA}


def _sql(statement: str, schema: str) -> str:
    """Point the (live-schema) statements at ``schema``. Only whitelisted names are accepted."""
    if schema not in VALID_SCHEMAS:
        raise ValueError(f"Unknown schema: {schema}")
    return statement if schema == LIVE_SCHEMA else statement.replace("observatorio.", f"{schema}.")


async def record_quarantine(
    conn: AsyncConnection,
    topic: str,
    partition: int,
    offset: int,
    raw_payload: bytes,
    rejection_reason: str,
    decoded_envelope: Optional[dict[str, Any]],
    schema: str = LIVE_SCHEMA,
) -> None:
    async with conn.cursor() as cur:
        await cur.execute(
            _sql(
                """
            INSERT INTO observatorio.quarantine_records (
                kafka_topic, kafka_partition, kafka_offset,
                raw_payload, rejection_reason, decoded_envelope, quarantined_at
            ) VALUES (
                %s, %s, %s, %s, %s, %s, clock_timestamp()
            )
            ON CONFLICT (kafka_topic, kafka_partition, kafka_offset) DO NOTHING;
            """,
                schema,
            ),
            (
                topic,
                partition,
                offset,
                raw_payload,
                rejection_reason,
                Jsonb(decoded_envelope) if decoded_envelope is not None else None,
            ),
        )
    logger.warning(
        "Message at %s:%d:%d quarantined. Reason: %s",
        topic,
        partition,
        offset,
        rejection_reason,
    )


async def load_dim_country(
    conn: AsyncConnection, catalog: Optional[CountryCatalog] = None
) -> int:
    """Load the country dimension from the catalog. Idempotent: one row per ADM0_A3."""
    catalog = catalog or get_catalog()
    rows = [
        (c.country_id, c.name, c.iso_a2, c.continent, c.subregion)
        for c in catalog.countries.values()
    ]
    async with conn.transaction(), conn.cursor() as cur:
        await cur.executemany(
            """
            INSERT INTO observatorio.dim_country (country_id, name, iso_a2, continent, subregion)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (country_id) DO UPDATE SET
                name = EXCLUDED.name,
                iso_a2 = EXCLUDED.iso_a2,
                continent = EXCLUDED.continent,
                subregion = EXCLUDED.subregion;
            """,
            rows,
        )
    return len(rows)


async def upsert_dim_date(cur: Any, when: datetime) -> None:
    d = when.astimezone(timezone.utc).date()
    iso = d.isocalendar()
    await cur.execute(
        """
        INSERT INTO observatorio.dim_date (date_key, year, month, day, iso_week, day_of_week)
        VALUES (%s, %s, %s, %s, %s, %s)
        ON CONFLICT (date_key) DO NOTHING;
        """,
        (d, d.year, d.month, d.day, iso[1], iso[2]),
    )


async def persist_accepted_event(
    conn: AsyncConnection,
    event: ValidatedEvent,
    topic: str,
    partition: int,
    offset: int,
    raw_payload: bytes,
    catalog: Optional[CountryCatalog] = None,
    schema: str = LIVE_SCHEMA,
) -> bool:
    """
    Persist accepted event version and advance current event projection if newer.
    If the same (event_id, updated) already exists:
      - If payload_hash matches: treated as duplicate delivery (idempotent, returns True).
      - If payload_hash differs: payload conflict -> quarantined with PAYLOAD_CONFLICT_SAME_VERSION, returns False.
    """
    async with conn.cursor() as cur:
        await cur.execute(
            _sql(
                """
            SELECT payload_hash FROM observatorio.event_versions
            WHERE event_id = %s AND updated = %s;
            """,
                schema,
            ),
            (event.event_id, event.updated),
        )
        existing = await cur.fetchone()

        if existing is not None:
            existing_hash = existing[0]
            if existing_hash == event.payload_hash:
                logger.info(
                    "Duplicate delivery of event %s updated %d with matching payload. Skipping version insert.",
                    event.event_id,
                    event.updated,
                )
                return True
            else:
                logger.warning(
                    "Payload conflict for event %s updated %d: existing hash %s != incoming hash %s",
                    event.event_id,
                    event.updated,
                    existing_hash,
                    event.payload_hash,
                )
                await record_quarantine(
                    conn,
                    topic,
                    partition,
                    offset,
                    raw_payload,
                    REASON_PAYLOAD_CONFLICT_SAME_VERSION,
                    event.original_feature,
                    schema,
                )
                return False

        geo = (catalog or get_catalog()).locate(event.longitude, event.latitude)
        await upsert_dim_date(cur, event.time_utc)  # shared dimension (live schema)

        # Insert new version
        await cur.execute(
            _sql(
                """
            INSERT INTO observatorio.event_versions (
                event_id, updated, payload_hash, time, time_utc, updated_utc,
                mag, mag_type, place, status, tsunami, sig, net, code, ids,
                sources, types, nst, dmin, rms, gap, mag_error, mag_nst,
                depth_error, horizontal_error, event_type, longitude, latitude,
                depth, original_feature, source, ingested_at, mode, kafka_topic,
                kafka_partition, kafka_offset, country_id, geo_ambiguous, received_at
            ) VALUES (
                %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s, clock_timestamp()
            );
            """,
                schema,
            ),
            (
                event.event_id,
                event.updated,
                event.payload_hash,
                event.time,
                event.time_utc,
                event.updated_utc,
                event.mag,
                event.mag_type,
                event.place,
                event.status,
                event.tsunami,
                event.sig,
                event.net,
                event.code,
                event.ids,
                event.sources,
                event.types,
                event.nst,
                event.dmin,
                event.rms,
                event.gap,
                event.mag_error,
                event.mag_nst,
                event.depth_error,
                event.horizontal_error,
                event.event_type,
                event.longitude,
                event.latitude,
                event.depth,
                Jsonb(event.original_feature),
                event.source,
                event.ingested_at,
                event.mode,
                topic,
                partition,
                offset,
                geo.country_id,
                geo.ambiguous,
            ),
        )

        # Upsert current projection only if EXCLUDED.updated > current_events.updated
        await cur.execute(
            _sql(
                """
            INSERT INTO observatorio.current_events (
                event_id, updated, payload_hash, time, time_utc, updated_utc,
                mag, mag_type, place, status, tsunami, sig, net, code, ids,
                sources, types, nst, dmin, rms, gap, mag_error, mag_nst,
                depth_error, horizontal_error, event_type, longitude, latitude,
                depth, original_feature, source, ingested_at, mode, kafka_topic,
                kafka_partition, kafka_offset, country_id, geo_ambiguous, last_processed_at
            ) VALUES (
                %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s, clock_timestamp()
            )
            ON CONFLICT (event_id) DO UPDATE SET
                updated = EXCLUDED.updated,
                payload_hash = EXCLUDED.payload_hash,
                time = EXCLUDED.time,
                time_utc = EXCLUDED.time_utc,
                updated_utc = EXCLUDED.updated_utc,
                mag = EXCLUDED.mag,
                mag_type = EXCLUDED.mag_type,
                place = EXCLUDED.place,
                status = EXCLUDED.status,
                tsunami = EXCLUDED.tsunami,
                sig = EXCLUDED.sig,
                net = EXCLUDED.net,
                code = EXCLUDED.code,
                ids = EXCLUDED.ids,
                sources = EXCLUDED.sources,
                types = EXCLUDED.types,
                nst = EXCLUDED.nst,
                dmin = EXCLUDED.dmin,
                rms = EXCLUDED.rms,
                gap = EXCLUDED.gap,
                mag_error = EXCLUDED.mag_error,
                mag_nst = EXCLUDED.mag_nst,
                depth_error = EXCLUDED.depth_error,
                horizontal_error = EXCLUDED.horizontal_error,
                event_type = EXCLUDED.event_type,
                longitude = EXCLUDED.longitude,
                latitude = EXCLUDED.latitude,
                depth = EXCLUDED.depth,
                original_feature = EXCLUDED.original_feature,
                source = EXCLUDED.source,
                ingested_at = EXCLUDED.ingested_at,
                mode = EXCLUDED.mode,
                kafka_topic = EXCLUDED.kafka_topic,
                kafka_partition = EXCLUDED.kafka_partition,
                kafka_offset = EXCLUDED.kafka_offset,
                country_id = EXCLUDED.country_id,
                geo_ambiguous = EXCLUDED.geo_ambiguous,
                last_processed_at = clock_timestamp()
            WHERE EXCLUDED.updated > observatorio.current_events.updated;
            """,
                schema,
            ),
            (
                event.event_id,
                event.updated,
                event.payload_hash,
                event.time,
                event.time_utc,
                event.updated_utc,
                event.mag,
                event.mag_type,
                event.place,
                event.status,
                event.tsunami,
                event.sig,
                event.net,
                event.code,
                event.ids,
                event.sources,
                event.types,
                event.nst,
                event.dmin,
                event.rms,
                event.gap,
                event.mag_error,
                event.mag_nst,
                event.depth_error,
                event.horizontal_error,
                event.event_type,
                event.longitude,
                event.latitude,
                event.depth,
                Jsonb(event.original_feature),
                event.source,
                event.ingested_at,
                event.mode,
                topic,
                partition,
                offset,
                geo.country_id,
                geo.ambiguous,
            ),
        )

        return True
