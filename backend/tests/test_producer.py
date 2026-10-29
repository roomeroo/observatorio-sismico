import json
import tempfile
import unittest
from pathlib import Path

import httpx

from observatorio.producer import poll_once, publish_events
from observatorio.publication_state import PublicationState
from observatorio.usgs_source import USGS_FEED_URL


class ProducerPublicationTests(unittest.IsolatedAsyncioTestCase):
    @staticmethod
    def event(updated: int) -> dict[str, object]:
        return {
            "type": "Feature",
            "id": "quake-1",
            "geometry": {"type": "Point", "coordinates": [10.5, -20.25, 30]},
            "properties": {"type": "earthquake", "updated": updated},
        }

    async def test_publishes_utf8_json_envelope_with_original_feature(self) -> None:
        feature = {
            "type": "Feature",
            "id": "quake-1",
            "geometry": {"type": "Point", "coordinates": [10.5, -20.25, 30]},
            "properties": {
                "type": "earthquake",
                "time": 1000,
                "updated": 2000,
                "mag": 4.1,
                "magType": "mw",
                "place": "Synthetic test event",
            },
        }
        sent: list[tuple[str, bytes, bytes]] = []

        async def send(topic: str, key: bytes, value: bytes) -> object:
            sent.append((topic, key, value))
            return object()

        with tempfile.TemporaryDirectory() as directory:
            with PublicationState(Path(directory) / "state.sqlite3") as state:
                await publish_events(
                    [feature],
                    state,
                    "earthquakes-live",
                    send,
                    (ConnectionError,),
                    ingested_at_ms=lambda: 3000,
                )

        self.assertEqual(len(sent), 1)
        topic, key, value = sent[0]
        self.assertEqual(topic, "earthquakes-live")
        self.assertEqual(key, b"quake-1")
        self.assertEqual(
            json.loads(value.decode("utf-8")),
            {
                "source": USGS_FEED_URL,
                "ingested_at": 3000,
                "mode": "live",
                "event": feature,
            },
        )

    async def test_poll_once_smoke_uses_fake_feed_and_marks_after_ack(self) -> None:
        feature = self.event(100)
        requests: list[str] = []
        sent: list[tuple[str, bytes, bytes]] = []
        state_at_send: list[int | None] = []

        async def handler(request: httpx.Request) -> httpx.Response:
            requests.append(str(request.url))
            return httpx.Response(
                200,
                json={"type": "FeatureCollection", "features": [feature]},
                request=request,
            )

        async def send(topic: str, key: bytes, value: bytes) -> object:
            sent.append((topic, key, value))
            state_at_send.append(state.latest_updated("quake-1"))
            return object()

        with tempfile.TemporaryDirectory() as directory:
            with PublicationState(Path(directory) / "state.sqlite3") as state:
                async with httpx.AsyncClient(
                    transport=httpx.MockTransport(handler)
                ) as client:
                    await poll_once(
                        client,
                        state,
                        "earthquakes-live",
                        send,
                        (ConnectionError,),
                    )

                self.assertEqual(state.latest_updated("quake-1"), 100)

        self.assertEqual(requests, [USGS_FEED_URL])
        self.assertEqual(len(sent), 1)
        topic, key, value = sent[0]
        self.assertEqual(topic, "earthquakes-live")
        self.assertEqual(key, b"quake-1")
        envelope = json.loads(value.decode("utf-8"))
        self.assertEqual(
            {name: envelope[name] for name in ("source", "mode", "event")},
            {"source": USGS_FEED_URL, "mode": "live", "event": feature},
        )
        self.assertIsInstance(envelope["ingested_at"], int)
        self.assertEqual(state_at_send, [None])

    async def test_publishes_only_new_and_later_versions(self) -> None:
        published_updates: list[int] = []

        async def send(_: str, __: bytes, value: bytes) -> object:
            event = json.loads(value.decode("utf-8"))["event"]
            published_updates.append(event["properties"]["updated"])
            return object()

        with tempfile.TemporaryDirectory() as directory:
            with PublicationState(Path(directory) / "state.sqlite3") as state:
                await publish_events(
                    [self.event(100)], state, "topic", send, (ConnectionError,)
                )
                await publish_events(
                    [self.event(100)], state, "topic", send, (ConnectionError,)
                )
                await publish_events(
                    [self.event(101)], state, "topic", send, (ConnectionError,)
                )
                await publish_events(
                    [self.event(99)], state, "topic", send, (ConnectionError,)
                )

                self.assertEqual(published_updates, [100, 101])
                self.assertEqual(state.latest_updated("quake-1"), 101)

    async def test_state_advances_only_after_send_acknowledgement(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with PublicationState(Path(directory) / "state.sqlite3") as state:
                delays: list[float] = []

                async def failed_send(_: str, __: bytes, ___: bytes) -> object:
                    raise ConnectionError("broker unavailable")

                async def fake_sleep(seconds: float) -> None:
                    delays.append(seconds)

                with self.assertLogs("root", level="ERROR"):
                    await publish_events(
                        [self.event(100)],
                        state,
                        "topic",
                        failed_send,
                        (ConnectionError,),
                        retry_sleep=fake_sleep,
                    )

                self.assertIsNone(state.latest_updated("quake-1"))
                self.assertEqual(delays, [20.0, 40.0])
                observations: list[int | None] = []

                async def acknowledged_send(
                    _: str,
                    __: bytes,
                    ___: bytes,
                ) -> object:
                    observations.append(state.latest_updated("quake-1"))
                    return object()

                await publish_events(
                    [self.event(100)],
                    state,
                    "topic",
                    acknowledged_send,
                    (ConnectionError,),
                    retry_sleep=fake_sleep,
                )

                self.assertEqual(observations, [None])
                self.assertEqual(state.latest_updated("quake-1"), 100)

    async def test_failed_event_does_not_block_and_retries_after_kafka_recovers(
        self,
    ) -> None:
        first_event = self.event(100)
        later_event = self.event(200)
        later_event["id"] = "quake-2"
        request_count = 0
        send_attempts: list[bytes] = []
        delays: list[float] = []

        async def handler(request: httpx.Request) -> httpx.Response:
            nonlocal request_count
            request_count += 1
            return httpx.Response(
                200,
                json={
                    "type": "FeatureCollection",
                    "features": [first_event, later_event],
                },
                request=request,
            )

        async def send(_: str, key: bytes, __: bytes) -> object:
            send_attempts.append(key)
            if key == b"quake-1" and send_attempts.count(key) <= 3:
                raise ConnectionError("broker unavailable")
            return object()

        async def fake_sleep(seconds: float) -> None:
            delays.append(seconds)

        with tempfile.TemporaryDirectory() as directory:
            with PublicationState(Path(directory) / "state.sqlite3") as state:
                async with httpx.AsyncClient(
                    transport=httpx.MockTransport(handler)
                ) as client:
                    with self.assertLogs("root", level="ERROR"):
                        await poll_once(
                            client,
                            state,
                            "topic",
                            send,
                            (ConnectionError,),
                            send_retry_sleep=fake_sleep,
                        )

                    self.assertIsNone(state.latest_updated("quake-1"))
                    self.assertEqual(state.latest_updated("quake-2"), 200)

                    await poll_once(
                        client,
                        state,
                        "topic",
                        send,
                        (ConnectionError,),
                        send_retry_sleep=fake_sleep,
                    )

                self.assertEqual(state.latest_updated("quake-1"), 100)
                self.assertEqual(state.latest_updated("quake-2"), 200)

        self.assertEqual(request_count, 2)
        self.assertEqual(
            send_attempts,
            [b"quake-1", b"quake-1", b"quake-1", b"quake-2", b"quake-1"],
        )
        self.assertEqual(delays, [20.0, 40.0])

    async def test_event_send_uses_three_attempts_and_progressive_delays(self) -> None:
        attempts = 0
        delays: list[float] = []

        async def send(_: str, __: bytes, ___: bytes) -> object:
            nonlocal attempts
            attempts += 1
            if attempts < 3:
                raise ConnectionError("temporary broker failure")
            return object()

        async def fake_sleep(seconds: float) -> None:
            delays.append(seconds)

        with tempfile.TemporaryDirectory() as directory:
            with PublicationState(Path(directory) / "state.sqlite3") as state:
                await publish_events(
                    [self.event(100)],
                    state,
                    "topic",
                    send,
                    (ConnectionError,),
                    retry_sleep=fake_sleep,
                )
                self.assertEqual(state.latest_updated("quake-1"), 100)

        self.assertEqual(attempts, 3)
        self.assertEqual(delays, [20.0, 40.0])

    async def test_later_poll_recovers_after_exhausted_source_failures(self) -> None:
        request_attempts = 0
        source_delays: list[float] = []
        published_keys: list[bytes] = []
        feature = self.event(101)

        async def handler(request: httpx.Request) -> httpx.Response:
            nonlocal request_attempts
            request_attempts += 1
            if request_attempts <= 3:
                return httpx.Response(503, request=request)
            return httpx.Response(
                200,
                json={"type": "FeatureCollection", "features": [feature]},
                request=request,
            )

        async def fake_source_sleep(seconds: float) -> None:
            source_delays.append(seconds)

        async def send(_: str, key: bytes, __: bytes) -> object:
            published_keys.append(key)
            return object()

        with tempfile.TemporaryDirectory() as directory:
            with PublicationState(Path(directory) / "state.sqlite3") as state:
                state.mark_published("prior-event", 100)
                async with httpx.AsyncClient(
                    transport=httpx.MockTransport(handler)
                ) as client:
                    with self.assertLogs("root", level="ERROR"):
                        await poll_once(
                            client,
                            state,
                            "topic",
                            send,
                            (ConnectionError,),
                            source_retry_sleep=fake_source_sleep,
                        )

                    self.assertEqual(published_keys, [])
                    self.assertEqual(state.latest_updated("prior-event"), 100)

                    await poll_once(
                        client,
                        state,
                        "topic",
                        send,
                        (ConnectionError,),
                        source_retry_sleep=fake_source_sleep,
                    )

                self.assertEqual(published_keys, [b"quake-1"])
                self.assertEqual(state.latest_updated("quake-1"), 101)

        self.assertEqual(request_attempts, 4)
        self.assertEqual(source_delays, [20.0, 40.0])


if __name__ == "__main__":
    unittest.main()
