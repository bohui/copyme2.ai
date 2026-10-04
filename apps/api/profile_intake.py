"""Extract explicit storyteller profile context from a Codex reply marker."""

from __future__ import annotations

import json
import re
from copy import deepcopy
from datetime import datetime
from typing import Any


PROFILE_MARKER_START = "[[MEMORY_SPARK_PROFILE]]"
PROFILE_MARKER_END = "[[/MEMORY_SPARK_PROFILE]]"
LEGACY_PROFILE_MARKER_PATTERN = re.compile(r"<!--\s*profile\s*:", re.IGNORECASE)
LEGACY_PROFILE_MARKER_END = "-->"
PROFILE_FIELDS = {
    "name": 120,
    "birth_date_expression": 120,
    "birth_place": 160,
    "childhood_place": 160,
}
LIFE_STAGES = {"baby", "toddler", "childhood", "adolescence", "young_adulthood", "midlife", "later_life"}
STORY_FOCUS_FIELDS = {"who": 500, "where": 300, "when": 160, "what": 1000}
EXPLICIT_MIDLIFE_CUE = re.compile(r"三十岁(?:以后|之后)")


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
    """Keep only bounded, explicit profile values emitted by the runtime."""
    if not isinstance(raw, dict):
        return None

    updates: dict[str, Any] = {}
    if raw.get("preferred_language") in ("en-AU", "zh-CN"):
        updates["preferred_language"] = raw["preferred_language"]
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


def apply_explicit_story_stage(text: str, updates: Any) -> dict[str, Any] | None:
    """Apply an unambiguous stage cue without inventing other profile facts.

    The model may use the allowed stage vocabulary but still misclassify the
    explicit Chinese ``三十岁以后/三十岁之后`` cue as young adulthood. This
    narrow guard protects persisted application state while leaving all other
    profile fields and uncertain wording model-owned.
    """
    validated = validate_profile_updates(updates) or {}
    if not isinstance(text, str) or not EXPLICIT_MIDLIFE_CUE.search(text):
        return validated or None
    focus = dict(validated.get("story_focus") or {})
    focus["life_stage"] = "midlife"
    validated["story_focus"] = focus
    return validated


def profile_marker_present(text: str) -> bool:
    """Return whether a reply contains a supported profile marker."""
    return PROFILE_MARKER_START in text or LEGACY_PROFILE_MARKER_PATTERN.search(text) is not None


def _normalize_legacy_profile(raw: Any) -> Any:
    """Translate the pre-Memory-Spark profile shape into the current schema."""
    if not isinstance(raw, dict):
        return raw

    normalized = dict(raw)
    aliases = {
        "who": "name",
        "when": "birth_date_expression",
        "where": "birth_place",
    }
    for legacy_key, current_key in aliases.items():
        if current_key not in normalized and legacy_key in raw:
            normalized[current_key] = raw[legacy_key]
    if "what" in raw and "story_focus" not in normalized:
        normalized["story_focus"] = {"what": raw["what"]}
    return normalized


def extract_profile_updates(text: str) -> tuple[str, dict[str, Any] | None]:
    """Strip the first profile marker and return its validated payload.

    The HTML-comment form is retained as a compatibility bridge for replies
    produced by older profile-intake prompts.
    """
    canonical_start = text.find(PROFILE_MARKER_START)
    legacy_match = LEGACY_PROFILE_MARKER_PATTERN.search(text)
    legacy_start = legacy_match.start() if legacy_match else -1
    if canonical_start < 0 and legacy_start < 0:
        return text.strip(), None

    if canonical_start >= 0 and (legacy_start < 0 or canonical_start <= legacy_start):
        start = canonical_start
        payload_start = start + len(PROFILE_MARKER_START)
        end_marker = PROFILE_MARKER_END
        legacy = False
    else:
        start = legacy_start
        payload_start = legacy_match.end()
        end_marker = LEGACY_PROFILE_MARKER_END
        legacy = True

    end = text.find(end_marker, payload_start)
    if end < 0:
        return text[:start].rstrip(), None

    visible = f"{text[:start]}{text[end + len(end_marker):]}".strip()
    try:
        raw = json.loads(text[payload_start:end].strip())
    except json.JSONDecodeError:
        return visible, None
    if legacy:
        raw = _normalize_legacy_profile(raw)
    return visible, validate_profile_updates(raw)
