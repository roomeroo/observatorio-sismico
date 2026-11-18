from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from typing import Any, Optional


REASON_MALFORMED_JSON = "MALFORMED_JSON"
REASON_INVALID_ENVELOPE = "INVALID_ENVELOPE"
REASON_MISSING_OR_INVALID_ID_OR_UPDATED = "MISSING_OR_INVALID_ID_OR_UPDATED"
REASON_NON_EARTHQUAKE_EVENT = "NON_EARTHQUAKE_EVENT"
REASON_INVALID_GEOMETRY_OR_COORDINATES = "INVALID_GEOMETRY_OR_COORDINATES"
REASON_PAYLOAD_CONFLICT_SAME_VERSION = "PAYLOAD_CONFLICT_SAME_VERSION"


@dataclass(frozen=True)
class ValidatedEvent:
    event_id: str
    updated: int
    payload_hash: str
    time: Optional[int]
    time_utc: Optional[datetime]
    updated_utc: datetime
    mag: Optional[float]
    mag_type: Optional[str]
    place: Optional[str]
    status: Optional[str]
    tsunami: Optional[int]
    sig: Optional[int]
    net: Optional[str]
    code: Optional[str]
    ids: Optional[str]
    sources: Optional[str]
    types: Optional[str]
    nst: Optional[int]
    dmin: Optional[float]
    rms: Optional[float]
    gap: Optional[float]
    mag_error: Optional[float]
    mag_nst: Optional[int]
    depth_error: Optional[float]
    horizontal_error: Optional[float]
    event_type: str
    longitude: float
    latitude: float
    depth: float
    original_feature: dict[str, Any]
    source: str
    ingested_at: datetime
    mode: str


@dataclass(frozen=True)
class ValidationResult:
    is_valid: bool
    event: Optional[ValidatedEvent] = None
    rejection_reason: Optional[str] = None
    decoded_envelope: Optional[dict[str, Any]] = None


def compute_payload_hash(feature: dict[str, Any]) -> str:
    canonical = json.dumps(feature, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def ms_to_utc(ms: Optional[int | float]) -> Optional[datetime]:
    if ms is None:
        return None
    try:
        return datetime.fromtimestamp(ms / 1000.0, tz=timezone.utc)
    except (ValueError, OSError, OverflowError):
        return None


def validate_message_bytes(raw_bytes: bytes) -> ValidationResult:
    try:
        text = raw_bytes.decode("utf-8")
        envelope = json.loads(text)
    except Exception:
        return ValidationResult(
            is_valid=False,
            rejection_reason=REASON_MALFORMED_JSON,
            decoded_envelope=None,
        )

    if not isinstance(envelope, dict):
        return ValidationResult(
            is_valid=False,
            rejection_reason=REASON_INVALID_ENVELOPE,
            decoded_envelope=None,
        )

    source = envelope.get("source")
    ingested_at_raw = envelope.get("ingested_at")
    mode = envelope.get("mode")
    feature = envelope.get("event")

    if not isinstance(source, str) or not isinstance(mode, str) or not isinstance(feature, dict):
        return ValidationResult(
            is_valid=False,
            rejection_reason=REASON_INVALID_ENVELOPE,
            decoded_envelope=envelope,
        )

    if not isinstance(ingested_at_raw, (int, float)):
        return ValidationResult(
            is_valid=False,
            rejection_reason=REASON_INVALID_ENVELOPE,
            decoded_envelope=envelope,
        )

    ingested_at_utc = ms_to_utc(ingested_at_raw)
    if ingested_at_utc is None:
        return ValidationResult(
            is_valid=False,
            rejection_reason=REASON_INVALID_ENVELOPE,
            decoded_envelope=envelope,
        )

    event_id = feature.get("id")
    properties = feature.get("properties")

    if not isinstance(event_id, str) or not event_id.strip() or not isinstance(properties, dict):
        return ValidationResult(
            is_valid=False,
            rejection_reason=REASON_MISSING_OR_INVALID_ID_OR_UPDATED,
            decoded_envelope=envelope,
        )

    updated_raw = properties.get("updated")
    if updated_raw is None or not isinstance(updated_raw, (int, float)) or isinstance(updated_raw, bool):
        return ValidationResult(
            is_valid=False,
            rejection_reason=REASON_MISSING_OR_INVALID_ID_OR_UPDATED,
            decoded_envelope=envelope,
        )

    updated_utc = ms_to_utc(updated_raw)
    if updated_utc is None:
        return ValidationResult(
            is_valid=False,
            rejection_reason=REASON_MISSING_OR_INVALID_ID_OR_UPDATED,
            decoded_envelope=envelope,
        )

    event_type = properties.get("type")
    if event_type != "earthquake":
        return ValidationResult(
            is_valid=False,
            rejection_reason=REASON_NON_EARTHQUAKE_EVENT,
            decoded_envelope=envelope,
        )

    geometry = feature.get("geometry")
    if not isinstance(geometry, dict) or geometry.get("type") != "Point":
        return ValidationResult(
            is_valid=False,
            rejection_reason=REASON_INVALID_GEOMETRY_OR_COORDINATES,
            decoded_envelope=envelope,
        )

    coordinates = geometry.get("coordinates")
    if (
        not isinstance(coordinates, (list, tuple))
        or len(coordinates) < 3
        or not all(isinstance(c, (int, float)) and not isinstance(c, bool) for c in coordinates[:3])
    ):
        return ValidationResult(
            is_valid=False,
            rejection_reason=REASON_INVALID_GEOMETRY_OR_COORDINATES,
            decoded_envelope=envelope,
        )

    longitude = float(coordinates[0])
    latitude = float(coordinates[1])
    depth = float(coordinates[2])

    if not (-180.0 <= longitude <= 180.0 and -90.0 <= latitude <= 90.0):
        return ValidationResult(
            is_valid=False,
            rejection_reason=REASON_INVALID_GEOMETRY_OR_COORDINATES,
            decoded_envelope=envelope,
        )

    time_raw = properties.get("time")
    time_val: Optional[int] = None
    time_utc: Optional[datetime] = None
    if isinstance(time_raw, (int, float)) and not isinstance(time_raw, bool):
        time_val = int(time_raw)
        time_utc = ms_to_utc(time_val)

    def to_float(val: Any) -> Optional[float]:
        if val is not None and isinstance(val, (int, float)) and not isinstance(val, bool):
            return float(val)
        return None

    def to_int(val: Any) -> Optional[int]:
        if val is not None and isinstance(val, (int, float)) and not isinstance(val, bool):
            return int(val)
        return None

    def to_str(val: Any) -> Optional[str]:
        if val is not None and isinstance(val, str):
            return val
        return None

    validated_event = ValidatedEvent(
        event_id=str(event_id),
        updated=int(updated_raw),
        payload_hash=compute_payload_hash(feature),
        time=time_val,
        time_utc=time_utc,
        updated_utc=updated_utc,
        mag=to_float(properties.get("mag")),
        mag_type=to_str(properties.get("magType")),
        place=to_str(properties.get("place")),
        status=to_str(properties.get("status")),
        tsunami=to_int(properties.get("tsunami")),
        sig=to_int(properties.get("sig")),
        net=to_str(properties.get("net")),
        code=to_str(properties.get("code")),
        ids=to_str(properties.get("ids")),
        sources=to_str(properties.get("sources")),
        types=to_str(properties.get("types")),
        nst=to_int(properties.get("nst")),
        dmin=to_float(properties.get("dmin")),
        rms=to_float(properties.get("rms")),
        gap=to_float(properties.get("gap")),
        mag_error=to_float(properties.get("magError")),
        mag_nst=to_int(properties.get("magNst")),
        depth_error=to_float(properties.get("depthError")),
        horizontal_error=to_float(properties.get("horizontalError")),
        event_type="earthquake",
        longitude=longitude,
        latitude=latitude,
        depth=depth,
        original_feature=feature,
        source=str(source),
        ingested_at=ingested_at_utc,
        mode=str(mode),
    )

    return ValidationResult(
        is_valid=True,
        event=validated_event,
        rejection_reason=None,
        decoded_envelope=envelope,
    )
