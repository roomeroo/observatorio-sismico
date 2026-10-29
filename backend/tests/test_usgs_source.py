import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock

import httpx

from observatorio.publication_state import PublicationState
from observatorio.usgs_source import (
    DEFAULT_POLL_INTERVAL_SECONDS,
    InvalidFeedError,
    USGS_FEED_URL,
    earthquake_features,
    fetch_feed,
    fetch_feed_or_skip,
    fetch_feed_with_retries,
    parse_feed,
    poll_interval_seconds,
    process_feed_payload,
    polling_loop,
)


class UsgsSourceTests(unittest.IsolatedAsyncioTestCase):
    async def test_fetches_documented_feed_url(self) -> None:
        requested_urls: list[str] = []
        feature = {
            "type": "Feature",
            "id": "fixture-event",
            "geometry": {"type": "Point", "coordinates": [1.0, 2.0, 3.0]},
            "properties": {"type": "earthquake", "updated": 100},
        }

        async def handler(request: httpx.Request) -> httpx.Response:
            requested_urls.append(str(request.url))
            return httpx.Response(
                200,
                json={"type": "FeatureCollection", "features": [feature]},
            )

        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler)
        ) as client:
            result = await fetch_feed(client)

        self.assertEqual(requested_urls, [USGS_FEED_URL])
        self.assertEqual(result, [feature])

    async def test_fetches_valid_empty_feed(self) -> None:
        async def handler(_: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={"type": "FeatureCollection", "features": []},
            )

        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler)
        ) as client:
            self.assertEqual(await fetch_feed(client), [])

    async def test_fetch_feed_rejects_invalid_json_and_structure(self) -> None:
        responses = [
            httpx.Response(200, content=b"{invalid"),
            httpx.Response(200, json={"type": "Feature"}),
        ]
        for response, expected_error in (
            (responses[0], json.JSONDecodeError),
            (responses[1], InvalidFeedError),
        ):
            async def handler(
                _: httpx.Request,
                response: httpx.Response = response,
            ) -> httpx.Response:
                return response

            async with httpx.AsyncClient(
                transport=httpx.MockTransport(handler)
            ) as client:
                with self.subTest(error=expected_error):
                    with self.assertRaises(expected_error):
                        await fetch_feed(client)

    async def test_fetch_feed_propagates_timeout_and_http_errors(self) -> None:
        async def timeout_handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ReadTimeout("fixture timeout", request=request)

        async with httpx.AsyncClient(
            transport=httpx.MockTransport(timeout_handler)
        ) as client:
            with self.assertRaises(httpx.ReadTimeout):
                await fetch_feed(client)

        for status_code in (429, 500):
            async def status_handler(
                request: httpx.Request,
                status_code: int = status_code,
            ) -> httpx.Response:
                return httpx.Response(status_code, request=request)

            async with httpx.AsyncClient(
                transport=httpx.MockTransport(status_handler)
            ) as client:
                with self.subTest(status=status_code):
                    with self.assertRaises(httpx.HTTPStatusError):
                        await fetch_feed(client)

    async def test_source_request_uses_three_attempts_and_progressive_delays(
        self,
    ) -> None:
        attempts = 0
        delays: list[float] = []

        async def handler(request: httpx.Request) -> httpx.Response:
            nonlocal attempts
            attempts += 1
            if attempts < 3:
                return httpx.Response(503, request=request)
            return httpx.Response(
                200,
                json={"type": "FeatureCollection", "features": []},
                request=request,
            )

        async def fake_sleep(seconds: float) -> None:
            delays.append(seconds)

        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler)
        ) as client:
            self.assertEqual(await fetch_feed_with_retries(client, fake_sleep), [])

        self.assertEqual(attempts, 3)
        self.assertEqual(delays, [20.0, 40.0])

    async def test_exhausted_source_failures_preserve_state_and_recover_next_poll(
        self,
    ) -> None:
        failure_kinds = ("timeout", "429", "5xx", "invalid_json", "invalid_geojson")
        for failure_kind in failure_kinds:
            with self.subTest(failure_kind=failure_kind):
                attempts = 0
                delays: list[float] = []

                async def handler(request: httpx.Request) -> httpx.Response:
                    nonlocal attempts
                    attempts += 1
                    if attempts > 3:
                        return httpx.Response(
                            200,
                            json={"type": "FeatureCollection", "features": []},
                            request=request,
                        )
                    if failure_kind == "timeout":
                        raise httpx.ReadTimeout("fixture timeout", request=request)
                    if failure_kind == "429":
                        return httpx.Response(429, request=request)
                    if failure_kind == "5xx":
                        return httpx.Response(503, request=request)
                    if failure_kind == "invalid_json":
                        return httpx.Response(200, content=b"{invalid", request=request)
                    return httpx.Response(200, json={"type": "Feature"}, request=request)

                async def fake_sleep(seconds: float) -> None:
                    delays.append(seconds)

                with tempfile.TemporaryDirectory() as directory:
                    with PublicationState(Path(directory) / "state.sqlite3") as state:
                        state.mark_published("prior-event", 100)
                        async with httpx.AsyncClient(
                            transport=httpx.MockTransport(handler)
                        ) as client:
                            with self.assertLogs("root", level="ERROR"):
                                failed_result = await fetch_feed_or_skip(
                                    client,
                                    fake_sleep,
                                )
                            self.assertIsNone(failed_result)
                            self.assertEqual(
                                state.latest_updated("prior-event"),
                                100,
                            )
                            self.assertEqual(attempts, 3)
                            self.assertEqual(delays, [20.0, 40.0])

                            recovered = await fetch_feed_or_skip(
                                client,
                                fake_sleep,
                            )
                            self.assertEqual(recovered, [])
                            self.assertEqual(attempts, 4)

    def test_rejects_invalid_feature_collection_structure(self) -> None:
        for payload in (
            {},
            {"type": "FeatureCollection"},
            {"type": "FeatureCollection", "features": [None]},
            {
                "type": "FeatureCollection",
                "features": [{"type": "Feature", "properties": {}}],
            },
        ):
            with self.subTest(payload=payload):
                with self.assertRaises(InvalidFeedError):
                    parse_feed(payload)

    def test_empty_collection_is_valid(self) -> None:
        self.assertEqual(
            parse_feed({"type": "FeatureCollection", "features": []}),
            [],
        )

    async def test_empty_and_invalid_feed_do_not_publish_or_change_state(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with PublicationState(Path(directory) / "state.sqlite3") as state:
                state.mark_published("prior-event", 100)
                publisher = AsyncMock()

                await process_feed_payload(
                    {"type": "FeatureCollection", "features": []},
                    publisher,
                )
                self.assertFalse(publisher.await_args_list)
                self.assertEqual(state.latest_updated("prior-event"), 100)

                invalid_json_value = json.loads('{"type": "FeatureCollection"}')
                with self.assertRaises(InvalidFeedError):
                    await process_feed_payload(invalid_json_value, publisher)

                self.assertFalse(publisher.await_args_list)
                self.assertEqual(state.latest_updated("prior-event"), 100)

    def test_excludes_features_without_publication_identity_or_version(self) -> None:
        features = [
            {
                "type": "Feature",
                "id": "valid",
                "geometry": None,
                "properties": {"type": "earthquake", "updated": 100},
            },
            {
                "type": "Feature",
                "geometry": None,
                "properties": {"type": "earthquake", "updated": 100},
            },
            {
                "type": "Feature",
                "id": "missing-updated",
                "geometry": None,
                "properties": {"type": "earthquake"},
            },
        ]

        with self.assertLogs("root", level="WARNING") as logs:
            eligible = earthquake_features(features)

        self.assertEqual([feature["id"] for feature in eligible], ["valid"])
        self.assertIn("missing or invalid id", logs.output[0])
        self.assertIn("missing or invalid updated", logs.output[1])

    def test_selects_only_earthquake_events_and_logs_exclusion_reason(self) -> None:
        features = [
            {
                "type": "Feature",
                "id": "quake",
                "geometry": None,
                "properties": {"type": "earthquake", "updated": 100},
            },
            {
                "type": "Feature",
                "id": "explosion",
                "geometry": None,
                "properties": {"type": "explosion", "updated": 100},
            },
        ]

        with self.assertLogs("root", level="INFO") as logs:
            eligible = earthquake_features(features)

        self.assertEqual([feature["id"] for feature in eligible], ["quake"])
        self.assertIn("type is not earthquake", logs.output[0])

    async def test_poll_interval_defaults_to_sixty_seconds_and_is_configurable(
        self,
    ) -> None:
        self.assertEqual(poll_interval_seconds({}), DEFAULT_POLL_INTERVAL_SECONDS)
        self.assertEqual(
            poll_interval_seconds({"USGS_POLL_INTERVAL_SECONDS": "45"}),
            45.0,
        )

        with self.assertRaises(ValueError):
            poll_interval_seconds({"USGS_POLL_INTERVAL_SECONDS": "0"})

    async def test_polling_loop_uses_injected_clock(self) -> None:
        calls: list[str] = []
        stop_event = asyncio.Event()

        async def poll_once() -> None:
            calls.append("poll")

        async def fake_sleep(seconds: float) -> None:
            calls.append(f"sleep:{seconds}")
            stop_event.set()

        await polling_loop(poll_once, 60.0, fake_sleep, stop_event)

        self.assertEqual(calls, ["poll", "sleep:60.0"])


if __name__ == "__main__":
    unittest.main()
