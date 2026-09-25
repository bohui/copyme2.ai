"""Parse the private, text-based place journey contract used by the agent."""
from __future__ import annotations

import json
from typing import Any


MARKER_START = "[[MEMORY_SPARK_PLACE_JOURNEY]]"
MARKER_END = "[[/MEMORY_SPARK_PLACE_JOURNEY]]"
MAX_MARKER_CHARS = 4_000
MAX_PLACE_CHARS = 120
MAX_HIERARCHY_ITEMS = 6
GRANULARITIES = frozenset({"country", "region", "city", "suburb", "landmark"})


def extract_place_journey(text: str) -> tuple[str, dict[str, Any] | None]:
    """Return visible text and a validated journey payload.

    Invalid control markers are removed rather than shown to the storyteller.
    This keeps model formatting mistakes from becoming visible UI content.
    """
    if not isinstance(text, str):
        return "", None
    start = text.find(MARKER_START)
    if start < 0:
        return text.strip(), None
    end = text.find(MARKER_END, start + len(MARKER_START))
    if end < 0:
        return text[:start].strip(), None
    payload_text = text[start + len(MARKER_START):end].strip()
    visible = (text[:start] + text[end + len(MARKER_END):]).strip()
    if len(payload_text) > MAX_MARKER_CHARS:
        return visible, None
    try:
        raw = json.loads(payload_text)
    except (json.JSONDecodeError, TypeError):
        return visible, None
    return visible, validate_place_journey(raw)


def validate_place_journey(raw: Any) -> dict[str, Any] | None:
    """Validate and normalise the browser-facing place journey schema."""
    if not isinstance(raw, dict):
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

    has_coordinates = "latitude" in raw or "longitude" in raw
    latitude = _number(raw.get("latitude"))
    longitude = _number(raw.get("longitude"))
    if has_coordinates and ((latitude is None) or (longitude is None)):
        return None
    if latitude is not None and not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
        return None
    if latitude is not None:
        payload["latitude"] = latitude
        payload["longitude"] = longitude
    return payload


def _text(value: Any, limit: int) -> str | None:
    if not isinstance(value, str):
        return None
    value = " ".join(value.split()).strip()
    return value[:limit] if value else None


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _duration(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    value = int(value)
    return value if 2_800 <= value <= 9_000 else None
