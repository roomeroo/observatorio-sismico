import asyncio
import json
import logging
import os
import time
from collections.abc import Awaitable, Callable, Mapping

import httpx

from observatorio.retry import retry_with_backoff


GeoJsonFeature = dict[str, object]


USGS_FEED_URL = (
    "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/all_day.geojson"
)
DEFAULT_POLL_INTERVAL_SECONDS = 60.0


class InvalidFeedError(ValueError):
    pass


SOURCE_RETRY_ERRORS = (
    httpx.RequestError,
    httpx.HTTPStatusError,
    json.JSONDecodeError,
    InvalidFeedError,
)


def poll_interval_seconds(environ: Mapping[str, str] = os.environ) -> float:
    value = environ.get("USGS_POLL_INTERVAL_SECONDS")
    interval = DEFAULT_POLL_INTERVAL_SECONDS if value is None else float(value)
    if interval <= 0:
        raise ValueError("USGS_POLL_INTERVAL_SECONDS must be greater than zero")
    return interval


async def fetch_feed(client: httpx.AsyncClient) -> list[GeoJsonFeature]:
    started_at = time.perf_counter()
    try:
        response = await client.get(USGS_FEED_URL)
        response.raise_for_status()
        return parse_feed(response.json())
    finally:
        logging.info(
            "USGS feed request completed in %.3f seconds.",
            time.perf_counter() - started_at,
        )


def retryable_source_error(error: Exception) -> bool:
    if isinstance(error, httpx.HTTPStatusError):
        status = error.response.status_code
        return status == 429 or status >= 500
    return True


async def fetch_feed_with_retries(
    client: httpx.AsyncClient,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> list[GeoJsonFeature]:
    return await retry_with_backoff(
        lambda: fetch_feed(client),
        "USGS feed request",
        SOURCE_RETRY_ERRORS,
        sleep,
        retryable_source_error,
    )


async def fetch_feed_or_skip(
    client: httpx.AsyncClient,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> list[GeoJsonFeature] | None:
    try:
        return await fetch_feed_with_retries(client, sleep)
    except SOURCE_RETRY_ERRORS as error:
        logging.error("Skipping this USGS polling cycle: %s", error)
        return None


async def process_feed_payload(
    payload: object,
    publish_feature: Callable[[GeoJsonFeature], Awaitable[None]],
) -> None:
    features = parse_feed(payload)
    for feature in earthquake_features(features):
        await publish_feature(feature)


def parse_feed(payload: object) -> list[GeoJsonFeature]:
    if not isinstance(payload, dict) or payload.get("type") != "FeatureCollection":
        raise InvalidFeedError("USGS response is not a GeoJSON FeatureCollection")

    features = payload.get("features")
    if not isinstance(features, list):
        raise InvalidFeedError("USGS FeatureCollection has no features array")

    parsed: list[GeoJsonFeature] = []
    for index, feature in enumerate(features):
        if (
            not isinstance(feature, dict)
            or feature.get("type") != "Feature"
            or "geometry" not in feature
            or not isinstance(feature.get("properties"), dict)
        ):
            raise InvalidFeedError(
                f"USGS feature at index {index} has an invalid GeoJSON structure"
            )
        geometry = feature["geometry"]
        if geometry is not None and not isinstance(geometry, dict):
            raise InvalidFeedError(
                f"USGS feature at index {index} has invalid geometry"
            )
        parsed.append(feature)

    return parsed


def earthquake_features(
    features: list[GeoJsonFeature],
) -> list[GeoJsonFeature]:
    eligible: list[GeoJsonFeature] = []
    for index, feature in enumerate(features):
        properties = feature["properties"]
        if not isinstance(properties, dict):
            raise InvalidFeedError(
                f"USGS feature at index {index} has invalid properties"
            )
        if properties.get("type") != "earthquake":
            logging.info(
                "Excluding USGS feature at index %s: type is not earthquake.",
                index,
            )
            continue

        event_id = feature.get("id")
        updated = properties.get("updated")
        if not isinstance(event_id, str) or not event_id:
            logging.warning(
                "Excluding earthquake feature at index %s: missing or invalid id.",
                index,
            )
            continue
        if isinstance(updated, bool) or not isinstance(updated, int):
            logging.warning(
                "Excluding earthquake feature %s: missing or invalid updated.",
                event_id,
            )
            continue
        eligible.append(feature)

    return eligible


async def polling_loop(
    poll_once: Callable[[], Awaitable[None]],
    interval_seconds: float,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    stop_event: asyncio.Event | None = None,
) -> None:
    while stop_event is None or not stop_event.is_set():
        await poll_once()
        await sleep(interval_seconds)
