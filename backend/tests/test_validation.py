from datetime import datetime, timezone
import json
import unittest

from observatorio.validation import (
    REASON_INVALID_ENVELOPE,
    REASON_INVALID_GEOMETRY_OR_COORDINATES,
    REASON_MALFORMED_JSON,
    REASON_MISSING_OR_INVALID_ID_OR_UPDATED,
    REASON_NON_EARTHQUAKE_EVENT,
    validate_message_bytes,
)


class ValidationTests(unittest.TestCase):
    @staticmethod
    def valid_envelope() -> dict:
        return {
            "source": "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/all_day.geojson",
            "ingested_at": 1700000000000,
            "mode": "live",
            "event": {
                "type": "Feature",
                "id": "nc73940126",
                "geometry": {
                    "type": "Point",
                    "coordinates": [-122.4194, 37.7749, 12.3],
                },
                "properties": {
                    "type": "earthquake",
                    "time": 1700000000000,
                    "updated": 1700000060000,
                    "mag": 3.8,
                    "magType": "mw",
                    "place": "San Francisco, CA",
                    "status": "reviewed",
                },
            },
        }

    def test_valid_envelope_decodes_successfully(self) -> None:
        raw = json.dumps(self.valid_envelope()).encode("utf-8")
        result = validate_message_bytes(raw)
        self.assertTrue(result.is_valid)
        self.assertIsNone(result.rejection_reason)
        self.assertIsNotNone(result.event)
        event = result.event
        self.assertEqual(event.event_id, "nc73940126")
        self.assertEqual(event.updated, 1700000060000)
        self.assertEqual(event.mag, 3.8)
        self.assertEqual(event.longitude, -122.4194)
        self.assertEqual(event.latitude, 37.7749)
        self.assertEqual(event.depth, 12.3)
        self.assertEqual(
            event.updated_utc,
            datetime.fromtimestamp(1700000060, tz=timezone.utc),
        )

    def test_malformed_json_rejected(self) -> None:
        raw = b"this is not { valid json"
        result = validate_message_bytes(raw)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.rejection_reason, REASON_MALFORMED_JSON)

    def test_missing_envelope_fields_rejected(self) -> None:
        envelope = {"source": "usgs"}
        raw = json.dumps(envelope).encode("utf-8")
        result = validate_message_bytes(raw)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.rejection_reason, REASON_INVALID_ENVELOPE)

    def test_missing_or_invalid_id_rejected(self) -> None:
        envelope = self.valid_envelope()
        del envelope["event"]["id"]
        raw = json.dumps(envelope).encode("utf-8")
        result = validate_message_bytes(raw)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.rejection_reason, REASON_MISSING_OR_INVALID_ID_OR_UPDATED)

        # Empty string id
        envelope = self.valid_envelope()
        envelope["event"]["id"] = "   "
        raw = json.dumps(envelope).encode("utf-8")
        result = validate_message_bytes(raw)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.rejection_reason, REASON_MISSING_OR_INVALID_ID_OR_UPDATED)

    def test_missing_or_invalid_updated_rejected(self) -> None:
        envelope = self.valid_envelope()
        del envelope["event"]["properties"]["updated"]
        raw = json.dumps(envelope).encode("utf-8")
        result = validate_message_bytes(raw)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.rejection_reason, REASON_MISSING_OR_INVALID_ID_OR_UPDATED)

        envelope = self.valid_envelope()
        envelope["event"]["properties"]["updated"] = "not-a-timestamp"
        raw = json.dumps(envelope).encode("utf-8")
        result = validate_message_bytes(raw)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.rejection_reason, REASON_MISSING_OR_INVALID_ID_OR_UPDATED)

    def test_non_earthquake_event_rejected(self) -> None:
        envelope = self.valid_envelope()
        envelope["event"]["properties"]["type"] = "quarry blast"
        raw = json.dumps(envelope).encode("utf-8")
        result = validate_message_bytes(raw)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.rejection_reason, REASON_NON_EARTHQUAKE_EVENT)

    def test_invalid_geometry_or_coordinates_rejected(self) -> None:
        # Invalid geometry type
        envelope = self.valid_envelope()
        envelope["event"]["geometry"]["type"] = "Polygon"
        raw = json.dumps(envelope).encode("utf-8")
        result = validate_message_bytes(raw)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.rejection_reason, REASON_INVALID_GEOMETRY_OR_COORDINATES)

        # Invalid longitude > 180
        envelope = self.valid_envelope()
        envelope["event"]["geometry"]["coordinates"] = [185.0, 30.0, 10.0]
        raw = json.dumps(envelope).encode("utf-8")
        result = validate_message_bytes(raw)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.rejection_reason, REASON_INVALID_GEOMETRY_OR_COORDINATES)

        # Invalid latitude > 90
        envelope = self.valid_envelope()
        envelope["event"]["geometry"]["coordinates"] = [10.0, 95.0, 10.0]
        raw = json.dumps(envelope).encode("utf-8")
        result = validate_message_bytes(raw)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.rejection_reason, REASON_INVALID_GEOMETRY_OR_COORDINATES)

    def test_negative_magnitude_and_depth_accepted(self) -> None:
        envelope = self.valid_envelope()
        envelope["event"]["properties"]["mag"] = -0.5
        envelope["event"]["geometry"]["coordinates"] = [-120.0, 35.0, -1.2]
        raw = json.dumps(envelope).encode("utf-8")
        result = validate_message_bytes(raw)
        self.assertTrue(result.is_valid)
        self.assertEqual(result.event.mag, -0.5)
        self.assertEqual(result.event.depth, -1.2)

    def test_absent_magnitude_remains_null(self) -> None:
        envelope = self.valid_envelope()
        envelope["event"]["properties"]["mag"] = None
        raw = json.dumps(envelope).encode("utf-8")
        result = validate_message_bytes(raw)
        self.assertTrue(result.is_valid)
        self.assertIsNone(result.event.mag)


if __name__ == "__main__":
    unittest.main()
