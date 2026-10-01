"""Parse the private, text-based place journey contract used by the agent."""
from __future__ import annotations

import json
import re
import unicodedata
from typing import Any


MARKER_START = "[[MEMORY_SPARK_PLACE_JOURNEY]]"
MARKER_END = "[[/MEMORY_SPARK_PLACE_JOURNEY]]"
MAX_MARKER_CHARS = 4_000
MAX_PLACE_CHARS = 120
MAX_HIERARCHY_ITEMS = 6
GRANULARITIES = frozenset({"country", "region", "city", "suburb", "landmark"})
SCHEMA_VERSION = 1
PERSISTED_FIELDS = (
    "place",
    "hierarchy",
    "granularity",
    "latitude",
    "longitude",
    "duration_ms",
)


def extract_place_journey(text: str) -> tuple[str, dict[str, Any] | None]:
    """Compatibility wrapper returning the first valid journey."""
    visible, journeys = extract_place_journeys(text)
    return visible, journeys[0] if journeys else None


def extract_place_journeys(text: str) -> tuple[str, list[dict[str, Any]]]:
    """Return visible text and every distinct validated journey in marker order.

    Invalid control markers are removed rather than shown to the storyteller.
    This keeps model formatting mistakes from becoming visible UI content.
    """
    if not isinstance(text, str):
        return "", []
    visible, journeys, seen = [], [], set()
    offset = 0
    while (start := text.find(MARKER_START, offset)) >= 0:
        visible.append(text[offset:start])
        payload_start = start + len(MARKER_START)
        end = text.find(MARKER_END, payload_start)
        next_start = text.find(MARKER_START, payload_start)
        if next_start >= 0 and (end < 0 or next_start < end):
            offset = next_start
            continue
        if end < 0:
            offset = len(text)
            break
        offset = end + len(MARKER_END)
        payload_text = text[payload_start:end].strip()
        if len(payload_text) > MAX_MARKER_CHARS:
            continue
        try:
            candidate = validate_place_journey(json.loads(payload_text))
        except (json.JSONDecodeError, TypeError):
            continue
        if candidate is None:
            continue
        key = (_normalize_for_match(candidate['place']),
               tuple(_normalize_for_match(label) for label in candidate['hierarchy']),
               candidate['granularity'])
        if key not in seen:
            seen.add(key)
            journeys.append(candidate)
    visible.append(text[offset:])
    return ''.join(visible).strip(), journeys


def validate_place_journey(raw: Any) -> dict[str, Any] | None:
    """Validate and normalise the browser-facing place journey schema."""
    if not isinstance(raw, dict):
        return None

    schema_version = raw.get("schema_version", SCHEMA_VERSION)
    if isinstance(schema_version, bool) or not isinstance(schema_version, int) or schema_version != SCHEMA_VERSION:
        return None

    place = _text(raw.get("place"), MAX_PLACE_CHARS)
    hierarchy = raw.get("hierarchy")
    granularity = raw.get("granularity")
    if not place or not isinstance(hierarchy, list) or not hierarchy:
        return None
    if len(hierarchy) > MAX_HIERARCHY_ITEMS or not isinstance(granularity, str):
        return None
    labels = [_text(item, MAX_PLACE_CHARS) for item in hierarchy]
    if any(not item for item in labels) or labels[0].casefold() != "earth":
        return None
    labels[0] = "Earth"
    granularity = granularity.strip().casefold()
    if granularity not in GRANULARITIES:
        return None

    payload: dict[str, Any] = {
        "place": place,
        "hierarchy": labels,
        "granularity": granularity,
        "duration_ms": _duration(raw.get("duration_ms", 5200)),
    }
    if payload["duration_ms"] is None:
        return None

    raw_latitude = raw.get("latitude")
    raw_longitude = raw.get("longitude")
    has_latitude = raw_latitude is not None
    has_longitude = raw_longitude is not None
    latitude = _number(raw_latitude)
    longitude = _number(raw_longitude)
    if has_latitude != has_longitude or (has_latitude and (latitude is None or longitude is None)):
        return None
    if latitude is not None and not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
        return None
    if latitude is not None:
        payload["latitude"] = latitude
        payload["longitude"] = longitude
    payload["schema_version"] = SCHEMA_VERSION
    return payload


def normalize_persisted_place_journey(raw: Any) -> dict[str, Any] | None:
    """Return the public record shape from a database row."""
    payload = validate_place_journey(raw)
    if payload is None or not isinstance(raw, dict):
        return None
    status = raw.get("status", "active")
    revision = raw.get("revision")
    updated_at = raw.get("updated_at")
    if status != "active" or isinstance(revision, bool) or not isinstance(revision, int) or revision < 1:
        return None
    if not isinstance(updated_at, str) or not updated_at.strip():
        return None
    payload.setdefault("latitude", None)
    payload.setdefault("longitude", None)
    payload.update({"status": status, "revision": revision, "updated_at": updated_at})
    source_sequence = raw.get("source_sequence")
    if isinstance(source_sequence, int) and not isinstance(source_sequence, bool) and source_sequence >= 0:
        payload["source_sequence"] = source_sequence
    return payload


def place_journey_fingerprint(raw: Any) -> tuple[Any, ...] | None:
    """Return stable place fields used to decide whether a journey changed."""
    payload = validate_place_journey(raw)
    if payload is None:
        return None
    return tuple(payload.get(field) for field in PERSISTED_FIELDS)


def place_journey_matches_message(journey: Any, message: str) -> bool:
    """Require a journey marker to be grounded in the current storyteller turn."""
    payload = validate_place_journey(journey)
    if payload is None or not isinstance(message, str) or not message.strip():
        return False

    normalized_message = _normalize_for_match(message)
    normalized_label = _normalize_for_match(payload["place"])
    if not normalized_label:
        return False
    if normalized_label in normalized_message:
        return True
    # Allow a leading article in a model label to differ from the storyteller's
    # wording, e.g. "the old river town" vs "old river town".
    words = normalized_label.split()
    return len(words) > 1 and " ".join(words[1:]) in normalized_message


def _text(value: Any, limit: int) -> str | None:
    if not isinstance(value, str):
        return None
    value = " ".join(value.split()).strip()
    return value[:limit] if value else None


def _normalize_for_match(value: str) -> str:
    value = unicodedata.normalize("NFKC", value).casefold()
    value = re.sub(r"[^\w\s]+", " ", value, flags=re.UNICODE)
    return " ".join(value.split())


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _duration(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    value = int(value)
    return value if 2_800 <= value <= 9_000 else None
