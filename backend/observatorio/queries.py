"""Parametrised SQL for the read API. All aggregates come from the current-state
table (``current_events``), never from message counts."""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

SCHEMAS = {"live": "observatorio", "replay": "replay"}
NO_COUNTRY_LABEL = "Sin país asignado"
NO_COUNTRY_FILTER = "SIN_PAIS"
HISTORICAL_YEAR = 2025
HISTORICAL_DAYS = 365
HISTORICAL_MIN_MAG = 4.0
MAX_HOURLY_SPAN = timedelta(days=31)

DEPTH_BINS = [(None, 10), (10, 35), (35, 70), (70, 300), (300, 700), (700, None)]


class FilterError(ValueError):
    """Semantically invalid filter combination (mapped to HTTP 422)."""


@dataclass(frozen=True)
class Filters:
    start: Optional[datetime] = None
    end: Optional[datetime] = None
    min_mag: Optional[float] = None
    country_id: Optional[str] = None
    subregion: Optional[str] = None
    mode: str = "live"

    @property
    def schema(self) -> str:
        return SCHEMAS[self.mode]


def _where(f: Filters, alias: str = "e", with_time: bool = True) -> tuple[str, list[Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    if with_time and f.start is not None:
        clauses.append(f"{alias}.time_utc >= %s")
        params.append(f.start)
    if with_time and f.end is not None:
        clauses.append(f"{alias}.time_utc < %s")
        params.append(f.end)
    if f.min_mag is not None:
        clauses.append(f"{alias}.mag >= %s")
        params.append(f.min_mag)
    if f.country_id is not None:
        if f.country_id == NO_COUNTRY_FILTER:
            clauses.append(f"{alias}.country_id IS NULL")
        else:
            clauses.append(f"{alias}.country_id = %s")
            params.append(f.country_id)
    if f.subregion is not None:
        if f.subregion == NO_COUNTRY_FILTER:
            clauses.append(f"{alias}.country_id IS NULL")
        else:
            clauses.append("c.subregion = %s")
            params.append(f.subregion)
    return (" AND ".join(clauses) if clauses else "TRUE"), params


def _from(f: Filters) -> str:
    return (
        f"{f.schema}.current_events e "
        "LEFT JOIN observatorio.dim_country c ON c.country_id = e.country_id"
    )


def _ms(value: Optional[datetime]) -> Optional[int]:
    """Unix milliseconds UTC (the contract's date format for events and freshness)."""
    return int(value.timestamp() * 1000) if value else None


def _iso(value: Optional[datetime]) -> Optional[str]:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z") if value else None


async def last_ingestion(conn, f: Filters) -> Optional[datetime]:
    async with conn.cursor() as cur:
        await cur.execute(f"SELECT max(last_processed_at) FROM {f.schema}.current_events")
        return (await cur.fetchone())[0]


def freshness(f: Filters, value: Optional[datetime]) -> dict[str, Optional[int]]:
    """``last_ingestion`` for live data, ``replay_loaded_at`` for replay data."""
    key = "last_ingestion" if f.mode == "live" else "replay_loaded_at"
    return {key: _ms(value)}


async def events_page(conn, f: Filters, limit: int, offset: int) -> dict[str, Any]:
    where, params = _where(f)
    base = _from(f)
    async with conn.cursor() as cur:
        await cur.execute(f"SELECT count(*) FROM {base} WHERE {where}", params)
        total = (await cur.fetchone())[0]
        null_excluded = await _null_mag_excluded(cur, f)
        await cur.execute(
            f"""
            SELECT e.event_id, e.time_utc, e.updated, e.mag, e.mag_type, e.place, e.status,
                   e.longitude, e.latitude, e.depth, e.country_id, c.name, c.subregion,
                   e.geo_ambiguous, e.tsunami, e.sig
            FROM {base} WHERE {where}
            ORDER BY e.time_utc DESC, e.event_id
            LIMIT %s OFFSET %s
            """,
            [*params, limit, offset],
        )
        rows = await cur.fetchall()
    features = [
        {
            "type": "Feature",
            "id": r[0],
            "geometry": {"type": "Point", "coordinates": [r[7], r[8], r[9]]},
            "properties": {
                "time": _ms(r[1]),
                "updated": r[2],
                "mag": r[3],
                "magType": r[4],
                "place": r[5],
                "status": r[6],
                "depth": r[9],
                "country_id": r[10],
                "country_name": r[11] if r[10] else None,
                "subregion": r[12],
                "geo_ambiguous": r[13],
                "tsunami": r[14],
                "sig": r[15],
            },
        }
        for r in rows
    ]
    return {"features": features, "total": total, "null_magnitude_excluded": null_excluded}


async def _null_mag_excluded(cur, f: Filters) -> int:
    """Events matching every other filter whose magnitude is null: they cannot satisfy
    ``min_mag`` and are reported separately instead of being silently dropped."""
    if f.min_mag is None:
        return 0
    where, params = _where(Filters(f.start, f.end, None, f.country_id, f.subregion, f.mode))
    await cur.execute(
        f"SELECT count(*) FROM {_from(f)} WHERE {where} AND e.mag IS NULL", params
    )
    return (await cur.fetchone())[0]


def _mag_label(lo: int) -> str:
    return f"{lo} a <{lo + 1}"


def _depth_label(lo, hi) -> str:
    if lo is None:
        return f"<{hi} km"
    if hi is None:
        return f">={lo} km"
    return f"{lo} a <{hi} km"


async def statistics(conn, f: Filters, now: Optional[datetime] = None) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    end = f.end or now
    start = f.start or (end - timedelta(hours=24))
    if end <= start:
        raise FilterError("end must be later than start")
    if end - start > MAX_HOURLY_SPAN:
        raise FilterError("period is too long for hourly windows (maximum 31 days)")
    f = Filters(start, end, f.min_mag, f.country_id, f.subregion, f.mode)
    where, params = _where(f)
    base = _from(f)

    async with conn.cursor() as cur:
        await cur.execute(f"SELECT count(*) FROM {base} WHERE {where}", params)
        total = (await cur.fetchone())[0]

        await cur.execute(
            f"""
            SELECT e.country_id, max(c.name), max(c.subregion), count(*)
            FROM {base} WHERE {where}
            GROUP BY e.country_id ORDER BY count(*) DESC, e.country_id NULLS LAST
            """,
            params,
        )
        by_country = [
            {
                "country_id": r[0],
                "country": r[1] if r[0] else NO_COUNTRY_LABEL,
                "subregion": r[2],
                "count": r[3],
            }
            for r in await cur.fetchall()
        ]

        await cur.execute(
            f"""
            SELECT c.subregion, count(*) FROM {base} WHERE {where}
            GROUP BY c.subregion ORDER BY count(*) DESC, c.subregion NULLS LAST
            """,
            params,
        )
        by_subregion = [
            {"subregion": r[0] if r[0] else NO_COUNTRY_LABEL, "count": r[1]}
            for r in await cur.fetchall()
        ]

        # Hourly windows (UTC, by event time) including empty hours.
        await cur.execute(
            f"""
            SELECT g.hour, count(e.event_id)
            FROM generate_series(
                    date_trunc('hour', %s::timestamptz AT TIME ZONE 'UTC'),
                    date_trunc('hour', (%s::timestamptz - interval '1 microsecond') AT TIME ZONE 'UTC'),
                    interval '1 hour') AS g(hour)
            LEFT JOIN (
                SELECT e.event_id, date_trunc('hour', e.time_utc AT TIME ZONE 'UTC') AS hour
                FROM {base} WHERE {where}
            ) e ON e.hour = g.hour
            GROUP BY g.hour ORDER BY g.hour
            """,
            [start, end, *params],
        )
        hourly = [
            {"hour_utc": r[0].replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z"), "count": r[1]}
            for r in await cur.fetchall()
        ]

        await cur.execute(
            f"""
            SELECT floor(e.mag)::int AS b, count(*) FROM {base}
            WHERE {where} AND e.mag IS NOT NULL GROUP BY b ORDER BY b
            """,
            params,
        )
        mag_bins = [
            {"from": r[0], "to": r[0] + 1, "label": _mag_label(r[0]), "count": r[1]}
            for r in await cur.fetchall()
        ]
        await cur.execute(
            f"SELECT count(*) FROM {base} WHERE {where} AND e.mag IS NULL", params
        )
        mag_missing = (await cur.fetchone())[0]

        case = " ".join(
            f"WHEN e.depth {'<' if lo is None else '>='} {hi if lo is None else lo}"
            + (f" AND e.depth < {hi}" if lo is not None and hi is not None else "")
            + f" THEN {i}"
            for i, (lo, hi) in enumerate(DEPTH_BINS)
        )
        await cur.execute(
            f"""
            SELECT CASE {case} END AS b, count(*) FROM {base}
            WHERE {where} AND e.depth IS NOT NULL GROUP BY b ORDER BY b
            """,
            params,
        )
        depth_counts = {r[0]: r[1] for r in await cur.fetchall()}
        depth_bins = [
            {"from": lo, "to": hi, "label": _depth_label(lo, hi), "count": depth_counts.get(i, 0)}
            for i, (lo, hi) in enumerate(DEPTH_BINS)
        ]
        await cur.execute(
            f"SELECT count(*) FROM {base} WHERE {where} AND e.depth IS NULL", params
        )
        depth_missing = (await cur.fetchone())[0]

        # Comparison: like for like. The 2025 history only holds M >= 4, so the recent
        # window is counted with the same minimum magnitude and the same geography.
        hist_min = max(f.min_mag if f.min_mag is not None else 0.0, HISTORICAL_MIN_MAG)
        last24 = Filters(now - timedelta(hours=24), now, hist_min, f.country_id, f.subregion, f.mode)
        w24, p24 = _where(last24)
        await cur.execute(f"SELECT count(*) FROM {_from(last24)} WHERE {w24}", p24)
        last_24h = (await cur.fetchone())[0]

        h_clauses = ["h.mag >= %s", "h.time_utc >= %s", "h.time_utc < %s"]
        h_params: list[Any] = [
            hist_min,
            datetime(HISTORICAL_YEAR, 1, 1, tzinfo=timezone.utc),
            datetime(HISTORICAL_YEAR + 1, 1, 1, tzinfo=timezone.utc),
        ]
        if f.country_id is not None:
            if f.country_id == NO_COUNTRY_FILTER:
                h_clauses.append("h.country_id IS NULL")
            else:
                h_clauses.append("h.country_id = %s")
                h_params.append(f.country_id)
        if f.subregion is not None:
            if f.subregion == NO_COUNTRY_FILTER:
                h_clauses.append("h.country_id IS NULL")
            else:
                h_clauses.append("c.subregion = %s")
                h_params.append(f.subregion)
        await cur.execute(
            "SELECT count(*) FROM observatorio.historical_events h "
            "LEFT JOIN observatorio.dim_country c ON c.country_id = h.country_id "
            f"WHERE {' AND '.join(h_clauses)}",
            h_params,
        )
        hist_count = (await cur.fetchone())[0]
        ingestion = await last_ingestion(conn, f)
        null_excluded = await _null_mag_excluded(cur, f)

    daily_mean = hist_count / HISTORICAL_DAYS
    comparison = {
        "last_24h_count": last_24h,
        "last_24h_min_mag": hist_min,
        "historical_year": HISTORICAL_YEAR,
        "historical_count": hist_count,
        "historical_days": HISTORICAL_DAYS,
        "historical_daily_mean": daily_mean,
        "historical_min_mag": hist_min,
        "ratio": (last_24h / daily_mean) if daily_mean > 0 else None,
        "note": (
            "El último periodo puede estar incompleto (USGS revisa y añade eventos con retraso). "
            f"La media histórica usa {HISTORICAL_DAYS} días (los días sin eventos cuentan como cero) "
            f"y solo contiene eventos con magnitud >= {HISTORICAL_MIN_MAG:g}."
        ),
    }
    return {
        "filters": {
            "start": _iso(start),
            "end": _iso(end),
            "min_mag": f.min_mag,
            "country_id": f.country_id,
            "subregion": f.subregion,
            "mode": f.mode,
        },
        "unit": "eventos (terremotos en su versión actual)",
        "period": {"start": _iso(start), "end": _iso(end), "window": "hora UTC fija, por hora de ocurrencia"},
        "missing": {
            "magnitude": mag_missing,
            "depth": depth_missing,
            "country": next((c["count"] for c in by_country if c["country_id"] is None), 0),
            "null_magnitude_excluded_by_min_mag": null_excluded,
        },
        "total": total,
        "by_country": by_country,
        "by_subregion": by_subregion,
        "hourly": hourly,
        "magnitude": {"bins": mag_bins, "missing": mag_missing},
        "depth": {"bins": depth_bins, "missing": depth_missing},
        "comparison": comparison,
        **freshness(f, ingestion),
    }


async def health(conn) -> dict[str, Any]:
    async with conn.cursor() as cur:
        await cur.execute(
            "SELECT max(last_processed_at), min(time_utc), max(time_utc), count(*) "
            "FROM observatorio.current_events"
        )
        last, first, latest, count = await cur.fetchone()
        await cur.execute(
            "SELECT polled_at, status, latency_ms, error FROM observatorio.poll_log "
            "ORDER BY polled_at DESC LIMIT 1"
        )
        poll = await cur.fetchone()
        await cur.execute("SELECT count(*) FROM observatorio.quarantine_records")
        quarantined = (await cur.fetchone())[0]
    return {
        "last_ingestion": _ms(last),
        "period": {"from": _iso(first), "to": _iso(latest)},
        "events": count,
        "quarantined": quarantined,
        "last_poll": (
            {"polled_at": _iso(poll[0]), "status": poll[1], "latency_ms": poll[2]} if poll else None
        ),
    }


async def replay_health(conn) -> dict[str, Any]:
    """Replay status: reports ``replay_loaded_at``; never the live ``last_ingestion``."""
    async with conn.cursor() as cur:
        await cur.execute(
            "SELECT max(last_processed_at), min(time_utc), max(time_utc), count(*) FROM replay.current_events"
        )
        loaded, first, latest, count = await cur.fetchone()
    return {
        "replay_loaded_at": _ms(loaded),
        "period": {"from": _iso(first), "to": _iso(latest)},
        "events": count,
    }
