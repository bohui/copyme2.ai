"""Parse the private, text-based place journey contract used by the agent."""
from __future__ import annotations

import json
import re
import unicodedata
from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, model_validator
from .place_identity import geographic_label, place_identity, place_path


class PlaceResearchWindow(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    year_start: int = Field(ge=1800, le=2100)
    year_end: int = Field(ge=1800, le=2100)
    anchor_year: int | None
    basis: Literal['explicit_period', 'birth_decade']
    quote: str = Field(min_length=1, max_length=2000)
    char_start: int = Field(ge=0)
    char_end: int = Field(ge=1)

    @model_validator(mode='after')
    def bounds(self, info: ValidationInfo):
        if not 0 <= self.year_end - self.year_start <= 15:
            raise ValueError('Invalid research window')
        if self.anchor_year is not None and not self.year_start <= self.anchor_year <= self.year_end:
            raise ValueError('Research anchor must be inside its window')
        if (info.context or {}).get('derived_source') is not None:
            from .interview_questions import question_span
            source = info.context['derived_source']
            try:
                self.char_start, self.char_end = question_span(source, self.quote, self.char_start, self.char_end)
            except ValueError:
                # Typed Lane B proposals may miscount; only the unchanged unique quote owns its span.
                self.char_start, self.char_end = question_span(source, self.quote)
        if self.char_end - self.char_start != len(self.quote):
            raise ValueError('Invalid research evidence span')
        return self


MARKER_START = "[[MEMORY_SPARK_PLACE_JOURNEY]]"
MARKER_END = "[[/MEMORY_SPARK_PLACE_JOURNEY]]"
MAX_MARKER_CHARS = 4_000
MAX_PLACE_CHARS = 120
MAX_HIERARCHY_ITEMS = 6
GRANULARITIES = frozenset({"country", "region", "city", "suburb"})
GENERIC_PLACES = frozenset({
    "家属院", "市区", "城区", "老家", "故乡", "家乡", "村里", "镇上", "河边", "山里",
    "学校", "医院", "车站", "小区", "附近", "这里", "那里",
    "home", "hometown", "my hometown", "city", "the city", "town", "suburb", "village",
    "the old river town", "school compound", "residential compound", "family compound",
})
DETAILED_PLACE = re.compile(
    r"(?:医院|学校|大学|学院|中学|小学|车站|火车站|家属院|小区|大厦|大楼|街|路|巷)(?:\d+号)?$"
    r"|\b(?:hospital|school|university|college|station|street|road|lane|avenue|building|compound)\b(?:\s+\d+)?$",
    re.IGNORECASE,
)
SCHEMA_VERSION = 1
PERSISTED_FIELDS = (
    "place",
    "hierarchy",
    "granularity",
    "latitude",
    "longitude",
    "research",
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
    if (not place or _normalize_for_match(place) in GENERIC_PLACES
            or DETAILED_PLACE.search(place) or not isinstance(hierarchy, list) or not hierarchy):
        return None
    if len(hierarchy) > MAX_HIERARCHY_ITEMS or not isinstance(granularity, str):
        return None
    labels = [_text(item, MAX_PLACE_CHARS) for item in hierarchy]
    if any(not item for item in labels) or labels[0].casefold() not in {"earth", "地球"}:
        return None
    if any(_normalize_for_match(label) in GENERIC_PLACES or DETAILED_PLACE.search(label)
           for label in labels[1:]):
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
    if raw.get('research') is not None:
        try:
            payload['research'] = PlaceResearchWindow.model_validate(raw['research']).model_dump()
        except ValueError:
            return None
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
    return tuple(geographic_label(payload['place']) if field == 'place'
                 else place_path(payload, normalized=True) if field == 'hierarchy'
                 else payload.get(field) for field in PERSISTED_FIELDS)


def reuse_known_place(current, candidate):
    """Keep a repeat mention's stable identity and independently known pin."""
    known = validate_place_journey(current)
    if known is None or place_identity(known) != place_identity(candidate):
        return candidate
    update = {**candidate, 'place': known['place'], 'hierarchy': list(known['hierarchy'])}
    if candidate.get('latitude') is None and candidate.get('longitude') is None:
        for field in ('latitude', 'longitude'):
            if field in known:
                update[field] = known[field]
    return update


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
    return False


def grounded_place_journeys(journeys: list[dict[str, Any]], message: str, *, source_offset=0) -> list[dict[str, Any]]:
    """Validate source identity/spans; assertion meaning belongs to extraction."""
    distinct = {}
    for raw in journeys:
        place = raw
        if validate_place_journey(raw) is None or not place_journey_matches_message(place, message):
            continue
        evidence = place.get('research')
        if evidence and (evidence['char_start'] < source_offset
                or evidence['char_end'] > source_offset + len(message)
                or message[evidence['char_start']-source_offset:evidence['char_end']-source_offset] != evidence['quote']):
            raise ValueError('Place research evidence must match the current source')
        key = place_identity(place)
        previous = distinct.get(key)
        if previous and place.get('latitude') is None and previous.get('latitude') is not None:
            place = {**place, 'latitude': previous['latitude'], 'longitude': previous['longitude']}
        distinct[key] = place
    return list(distinct.values())


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
