"""Extract explicit storyteller profile context from a Codex reply marker."""

from __future__ import annotations

import json
from copy import deepcopy
from datetime import datetime
from typing import Any


PROFILE_MARKER_START = "[[MEMORY_SPARK_PROFILE]]"
PROFILE_MARKER_END = "[[/MEMORY_SPARK_PROFILE]]"
PROFILE_FIELDS = {
    "name": 120,
    "birth_date_expression": 120,
    "birth_place": 160,
    "childhood_place": 160,
}
LIFE_STAGES = {"baby", "toddler", "childhood", "adolescence", "young_adulthood", "midlife", "later_life"}
STORY_FOCUS_FIELDS = {"who": 500, "where": 300, "when": 160, "what": 1000}


def _text(value: Any, limit: int) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = " ".join(value.split()).strip()
    return cleaned[:limit] if cleaned else None


def _year(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        year = int(value)
    except (TypeError, ValueError):
        return None
    current_year = datetime.now().year
    return year if 1800 <= year <= current_year else None


def validate_profile_updates(raw: Any) -> dict[str, Any] | None:
    """Keep only bounded, explicit profile values emitted by the harness."""
    if not isinstance(raw, dict):
        return None

    updates: dict[str, Any] = {}
    for key, limit in PROFILE_FIELDS.items():
        value = _text(raw.get(key), limit)
        if value is not None:
            updates[key] = value
    if raw.get("avatar_style") in ("male", "female"):
        updates["avatar_style"] = raw["avatar_style"]
    birth_year = _year(raw.get("birth_year"))
    if birth_year is not None:
        updates["birth_year"] = birth_year

    focus = raw.get("story_focus")
    if isinstance(focus, dict):
        story_focus = {}
        for key, limit in STORY_FOCUS_FIELDS.items():
            value = _text(focus.get(key), limit)
            if value is not None:
                story_focus[key] = value
        if isinstance(focus.get("life_stage"), str) and focus["life_stage"] in LIFE_STAGES:
            story_focus["life_stage"] = focus["life_stage"]
        if story_focus:
            updates["story_focus"] = story_focus

    return updates or None


def merge_profile_updates(profile: Any, updates: Any) -> dict[str, Any]:
    """Merge validated updates without erasing previously saved context."""
    current = deepcopy(profile) if isinstance(profile, dict) else {}
    validated = validate_profile_updates(updates) or {}
    for key, value in validated.items():
        if key == "story_focus":
            merged_focus = current.get("story_focus") if isinstance(current.get("story_focus"), dict) else {}
            current["story_focus"] = {**merged_focus, **value}
        else:
            current[key] = value
    return current


def extract_profile_updates(text: str) -> tuple[str, dict[str, Any] | None]:
    """Strip the first profile marker and return its validated payload."""
    start = text.find(PROFILE_MARKER_START)
    if start < 0:
        return text.strip(), None
    payload_start = start + len(PROFILE_MARKER_START)
    end = text.find(PROFILE_MARKER_END, payload_start)
    if end < 0:
        return text[:start].rstrip(), None

    visible = f"{text[:start]}{text[end + len(PROFILE_MARKER_END):]}".strip()
    try:
        raw = json.loads(text[payload_start:end].strip())
    except json.JSONDecodeError:
        return visible, None
    return visible, validate_profile_updates(raw)
