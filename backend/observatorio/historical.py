"""Historical acquisition: USGS FDSN event service, year 2025, M>=4, earthquakes.

Usage (same image as the rest of the stack):
    docker compose run --rm producer python -m observatorio.historical --year 2025 [--refresh]

Rules:
  * One query per month; a query that reaches the 20,000-event service limit is
    NOT used as data: its interval is bisected recursively until every result
    is below the limit (never truncates silently).
  * Responses are saved under ``backend/data/historical/`` (git-ignored) with a
    ``manifest.json``; a rerun reuses existing files with no network access
    unless ``--refresh`` is given.
  * Events returned by two adjacent intervals are stored once (by ``id``).
"""

import argparse
import hashlib
import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Optional

import httpx
import psycopg
from psycopg.types.json import Jsonb

from observatorio.database import postgres_connection_parameters
from observatorio.geo import CountryCatalog, get_catalog
from observatorio.migration import apply_migrations_sync

logger = logging.getLogger(__name__)

FDSN_URL = "https://earthquake.usgs.gov/fdsnws/event/1/query"
SERVICE_LIMIT = 20000
MIN_MAGNITUDE = 4
DEFAULT_DATA_DIR = Path(os.environ.get("HISTORICAL_DATA_DIR", Path(__file__).resolve().parents[1] / "data" / "historical"))

# fetch(params) -> (http_status, geojson_payload)
Fetch = Callable[[dict[str, Any]], tuple[int, dict]]


class CannotSplitError(RuntimeError):
    pass


@dataclass
class QueryRecord:
    start: datetime
    end: datetime
    status: str
    result_count: Optional[int]
    truncated: bool = False
    file: Optional[str] = None
    file_sha256: Optional[str] = None
    executed_at: Optional[str] = None
    url: str = FDSN_URL
    params: dict[str, Any] = field(default_factory=dict)
    reused: bool = False

    def to_json(self) -> dict:
        return {
            "start": self.start.isoformat(),
            "end": self.end.isoformat(),
            "status": self.status,
            "result_count": self.result_count,
            "truncated": self.truncated,
            "file": self.file,
            "file_sha256": self.file_sha256,
            "executed_at": self.executed_at,
            "url": self.url,
            "params": self.params,
        }

    @classmethod
    def from_json(cls, d: dict) -> "QueryRecord":
        return cls(
            start=datetime.fromisoformat(d["start"]),
            end=datetime.fromisoformat(d["end"]),
            status=d["status"],
            result_count=d["result_count"],
            truncated=d.get("truncated", False),
            file=d.get("file"),
            file_sha256=d.get("file_sha256"),
            executed_at=d.get("executed_at"),
            url=d.get("url", FDSN_URL),
            params=d.get("params", {}),
            reused=True,
        )


def month_windows(year: int) -> list[tuple[datetime, datetime]]:
    utc = timezone.utc
    return [
        (
            datetime(year, m, 1, tzinfo=utc),
            datetime(year + (m == 12), 1 if m == 12 else m + 1, 1, tzinfo=utc),
        )
        for m in range(1, 13)
    ]


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")


def window_key(start: datetime, end: datetime) -> str:
    return f"{_iso(start)}_{_iso(end)}"


def query_params(start: datetime, end: datetime) -> dict[str, Any]:
    return {
        "format": "geojson",
        "starttime": _iso(start),
        "endtime": _iso(end),
        "minmagnitude": MIN_MAGNITUDE,
        "eventtype": "earthquake",
        "orderby": "time-asc",
        "limit": SERVICE_LIMIT,
    }


def http_fetch(params: dict[str, Any]) -> tuple[int, dict]:
    response = httpx.get(FDSN_URL, params=params, timeout=120)
    response.raise_for_status()
    return response.status_code, response.json()


class Manifest:
    def __init__(self, data_dir: Path):
        self.data_dir = data_dir
        self.path = data_dir / "manifest.json"
        self.records: dict[str, QueryRecord] = {}
        if self.path.exists():
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            for item in raw.get("queries", []):
                rec = QueryRecord.from_json(item)
                self.records[window_key(rec.start, rec.end)] = rec

    def save(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        ordered = sorted(self.records.values(), key=lambda r: (r.start, r.end))
        self.path.write_text(
            json.dumps({"queries": [r.to_json() for r in ordered]}, indent=2),
            encoding="utf-8",
        )


def acquire_window(
    start: datetime,
    end: datetime,
    fetch: Fetch,
    manifest: Manifest,
    events: dict[str, dict],
    refresh: bool = False,
) -> list[QueryRecord]:
    """Acquire one interval, bisecting when it reaches the service limit.

    Returns the query records in the order executed/reused (including
    truncated parents, which carry no data)."""
    key = window_key(start, end)
    known = None if refresh else manifest.records.get(key)
    records: list[QueryRecord] = []

    if known is not None and known.truncated:
        known.reused = True
        record = known
    elif known is not None and known.file and (manifest.data_dir / known.file).exists():
        payload = json.loads((manifest.data_dir / known.file).read_text(encoding="utf-8"))
        known.reused = True
        _collect(payload, events)
        return [known]
    else:
        params = query_params(start, end)
        status, payload = fetch(params)
        count = len(payload.get("features", []))
        executed_at = datetime.now(timezone.utc).isoformat()
        record = QueryRecord(
            start=start, end=end, status=str(status), result_count=count,
            params=params, executed_at=executed_at,
        )
        if count >= SERVICE_LIMIT:
            record.truncated = True
        else:
            manifest.data_dir.mkdir(parents=True, exist_ok=True)
            name = f"usgs_{key.replace(':', '')}.geojson"
            text = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
            (manifest.data_dir / name).write_text(text, encoding="utf-8")
            record.file = name
            record.file_sha256 = hashlib.sha256(text.encode("utf-8")).hexdigest()
            _collect(payload, events)
        manifest.records[key] = record
        manifest.save()

    records.append(record)
    if record.truncated:
        span = end - start
        if span <= timedelta(seconds=2):
            raise CannotSplitError(f"{key} still reaches the {SERVICE_LIMIT} limit and cannot be split")
        mid = start + span / 2
        mid = mid.replace(microsecond=0)
        logger.warning("Interval %s reached %d events; splitting at %s", key, SERVICE_LIMIT, mid)
        records += acquire_window(start, mid, fetch, manifest, events, refresh)
        records += acquire_window(mid, end, fetch, manifest, events, refresh)
    return records


def _collect(payload: dict, events: dict[str, dict]) -> None:
    for feature in payload.get("features", []):
        event_id = feature.get("id")
        if not event_id:
            continue
        current = events.get(event_id)
        new_updated = (feature.get("properties") or {}).get("updated") or 0
        if current is None or new_updated > ((current.get("properties") or {}).get("updated") or 0):
            events[event_id] = feature


def acquire_year(
    year: int,
    fetch: Fetch = http_fetch,
    data_dir: Path = DEFAULT_DATA_DIR,
    refresh: bool = False,
) -> tuple[list[QueryRecord], dict[str, dict]]:
    manifest = Manifest(data_dir)
    events: dict[str, dict] = {}
    records: list[QueryRecord] = []
    for start, end in month_windows(year):
        records += acquire_window(start, end, fetch, manifest, events, refresh)
    return records, events


def event_row(feature: dict, catalog: CountryCatalog) -> tuple:
    props = feature.get("properties") or {}
    lon, lat, *rest = feature["geometry"]["coordinates"]
    depth = rest[0] if rest else None
    geo = catalog.locate(lon, lat)
    t = props.get("time")
    u = props.get("updated")
    to_dt = lambda ms: datetime.fromtimestamp(ms / 1000.0, tz=timezone.utc) if ms is not None else None
    return (
        feature["id"], to_dt(t), to_dt(u), props.get("mag"), props.get("magType"),
        props.get("place"), props.get("type"), lon, lat, depth, geo.country_id, geo.ambiguous,
    )


def load_to_db(
    conn: psycopg.Connection,
    records: list[QueryRecord],
    events: dict[str, dict],
    catalog: Optional[CountryCatalog] = None,
) -> dict[str, int]:
    """Persist query provenance and events (one row per event id)."""
    catalog = catalog or get_catalog()
    query_ids: dict[str, int] = {}
    with conn.transaction():
        with conn.cursor() as cur:
            for rec in records:
                key = window_key(rec.start, rec.end)
                cur.execute(
                    """
                    SELECT id FROM observatorio.extraction_queries
                    WHERE source = 'usgs-fdsn' AND starttime = %s AND endtime = %s
                      AND file_sha256 IS NOT DISTINCT FROM %s AND result_count IS NOT DISTINCT FROM %s
                    """,
                    (rec.start, rec.end, rec.file_sha256, rec.result_count),
                )
                row = cur.fetchone()
                if row is None:
                    params = dict(rec.params)
                    if rec.truncated:
                        params["truncated"] = True
                    cur.execute(
                        """
                        INSERT INTO observatorio.extraction_queries
                            (source, url, params, starttime, endtime, status, result_count,
                             file_path, file_sha256, executed_at)
                        VALUES ('usgs-fdsn', %s, %s, %s, %s, %s, %s, %s, %s,
                                COALESCE(%s::timestamptz, clock_timestamp()))
                        RETURNING id
                        """,
                        (rec.url, Jsonb(params), rec.start, rec.end, rec.status,
                         rec.result_count, rec.file, rec.file_sha256, rec.executed_at),
                    )
                    row = cur.fetchone()
                query_ids[key] = row[0]
            inserted = 0
            for event_id, feature in events.items():
                t = (feature.get("properties") or {}).get("time")
                qid = _query_for(t, records, query_ids)
                cur.execute(
                    """
                    INSERT INTO observatorio.historical_events
                        (event_id, time_utc, updated_utc, mag, mag_type, place, event_type,
                         longitude, latitude, depth, country_id, geo_ambiguous, query_id)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT (event_id) DO UPDATE SET
                        updated_utc = EXCLUDED.updated_utc, mag = EXCLUDED.mag,
                        mag_type = EXCLUDED.mag_type, place = EXCLUDED.place,
                        event_type = EXCLUDED.event_type, longitude = EXCLUDED.longitude,
                        latitude = EXCLUDED.latitude, depth = EXCLUDED.depth,
                        country_id = EXCLUDED.country_id, geo_ambiguous = EXCLUDED.geo_ambiguous,
                        query_id = EXCLUDED.query_id
                    WHERE EXCLUDED.updated_utc > observatorio.historical_events.updated_utc
                    """,
                    (*event_row(feature, catalog), qid),
                )
                inserted += 1
    return {"queries": len(query_ids), "events": inserted}


def _query_for(time_ms: Optional[int], records: list[QueryRecord], ids: dict[str, int]) -> Optional[int]:
    if time_ms is None:
        return None
    t = datetime.fromtimestamp(time_ms / 1000.0, tz=timezone.utc)
    best = None
    for rec in records:
        if rec.truncated or rec.file is None:
            continue
        if rec.start <= t < rec.end:
            best = ids[window_key(rec.start, rec.end)]
    return best


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--year", type=int, default=2025)
    parser.add_argument("--refresh", action="store_true", help="ignore saved files and query USGS again")
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    args = parser.parse_args()

    records, events = acquire_year(args.year, data_dir=args.data_dir, refresh=args.refresh)
    executed = sum(1 for r in records if not r.reused)
    logger.info("Acquired %d unique events from %d queries (%d executed, %d reused).",
                len(events), len(records), executed, len(records) - executed)
    with psycopg.connect(**postgres_connection_parameters(), connect_timeout=5) as conn:
        apply_migrations_sync(conn)
        result = load_to_db(conn, records, events)
    logger.info("Loaded into PostgreSQL: %s", result)


if __name__ == "__main__":
    main()
