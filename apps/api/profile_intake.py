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
EXPLICIT_MIDLIFE_NEGATION = re.compile(
    r"(?:不是|并非|不在|并不是)[^。！？.!?；;\n]{0,12}三十岁(?:以后|之后)"
)
EXPLICIT_CORRECTION = re.compile(
    r"(?:更正|纠正|修正|改正|更改|记错了|说错了|弄错了|搞错了|不对|"
    r"(?:correction|correct(?:ed|ion)?|revise|revised|update)\b)",
    re.IGNORECASE,
)
CHINESE_STAGE_BOUNDARY = re.compile(
    r"(?:三十岁(?:以后|之后)|四十岁(?:以后|之后)|五十岁(?:以后|之后)|"
    r"中年|童年|小时候|幼儿时期|童年时|少年时期|青春期|"
    r"(?:\d{1,2}|[一二三四五六七八九十百两〇零○]+)岁)"
)
CHINESE_NON_AUTHOR_SUBJECT = re.compile(
    r"^(?:的)?(?:姐姐|妹妹|哥哥|弟弟|父亲|爸爸|爸|母亲|妈妈|妈|父母|"
    r"外婆|外公|奶奶|爷爷|祖父|祖母|伴侣|妻子|丈夫|孩子|儿子|女儿|"
    r"阿姨|叔叔|舅舅|姑姑|表亲|朋友|同事|同学|老师|邻居|导师|老板)"
)
CHINESE_MIDLIFE_AGE = r"(?:3\d|4\d|5\d|三十[一二三四五六七八九]?|四十[一二三四五六七八九]?|五十[一二三四五六七八九]?)岁"


def _author_stage_evidence(text: str) -> str | None:
    """Classify only explicit author-age evidence used for midlife gating.

    This is deliberately structural rather than a list of event verbs.  A
    first-person age/period assertion establishes the author's stage; a
    relative's age or a childhood-age assertion does not.  Date corrections
    without an age cue remain model-owned facts, but they cannot promote an
    existing stage to ``midlife`` merely because the model chose that label.
    """
    if not isinstance(text, str):
        return None
    source = text.casefold()
    if _midlife_cue_is_author_scoped(text):
        return "midlife"
    author_midlife = bool(
        re.search(
            r"\b(?:i|we)\b[^.!?;\n]{0,80}\b(?:in|during)\s+my\s+"
            r"(?:thirties|30s|forties|40s|fifties|50s)\b",
            source,
        )
        or re.search(
            r"\b(?:i|we)\b[^.!?;\n]{0,60}\b(?:aged?|turned|was|am)\s+"
            r"(?:3\d|4\d|5\d)\b|"
            r"\b(?:i|we)\b[^.!?;\n]{0,50}\bat\s+(?:age\s+)?(?:3\d|4\d|5\d)\b",
            source,
        )
        or _chinese_author_midlife_evidence(text)
        or re.search(r"\b(?:in|during)\s+(?:later\s+)?midlife\b", source)
    )
    if author_midlife:
        return "midlife"
    author_earlier = bool(
        re.search(
            r"\b(?:i|we)\b[^.!?;\n]{0,60}\b(?:when\s+i\s+was|at\s+age|aged|age)\s+"
            r"(?:0?\d|1\d|2\d)\b",
            source,
        )
        or re.search(
            r"\b(?:when\s+i\s+was|as\s+a)\s+(?:baby|toddler|child|teenager|teen)\b",
            source,
        )
        or _chinese_author_earlier_evidence(text)
    )
    return "non_midlife" if author_earlier else None


def _chinese_clauses(text: str) -> list[str]:
    return [part.strip() for part in re.split(r"[，,。！？.!?；;\n]+", text) if part.strip()]


def _chinese_direct_author_subject(clause: str, *, require_first_subject: bool = False) -> bool:
    """Recognize ``我`` as the storyteller, not ``我姐姐`` or ``我的母亲``."""
    if not isinstance(clause, str):
        return False
    if require_first_subject:
        leading = clause.lstrip(" \t，,：:")
        match = re.match(r"我们|我", leading)
        if not match:
            return False
        suffix = leading[match.end():]
        return not (
            suffix.startswith("的")
            or CHINESE_NON_AUTHOR_SUBJECT.match(suffix)
        )
    for match in re.finditer(r"我们|我", clause):
        suffix = clause[match.end():]
        if suffix.startswith("的") or CHINESE_NON_AUTHOR_SUBJECT.match(suffix):
            continue
        return True
    return False


def _chinese_author_midlife_evidence(text: str) -> bool:
    return any(
        CHINESE_STAGE_BOUNDARY.search(clause)
        and re.search(
            rf"(?:中年|{CHINESE_MIDLIFE_AGE}(?!以后|之后))", clause
        )
        and _chinese_direct_author_subject(clause)
        for clause in _chinese_clauses(text)
    )


def _later_stage_correction_rejects_prior_midlife(text: str) -> bool:
    """Detect a later correction that replaces a prior midlife assertion."""
    cues = list(EXPLICIT_MIDLIFE_CUE.finditer(text))
    if not cues:
        return False
    last_cue_end = max(match.end() for match in cues)
    for correction in EXPLICIT_CORRECTION.finditer(text):
        if correction.start() <= last_cue_end:
            continue
        tail = text[correction.start():]
        if re.search(
            r"(?:小时候|幼儿时期|童年|少年时期|青春期|"
            rf"(?:[一二三四五六七八九十两〇零○]+|\d{{1,2}})岁)",
            tail,
        ):
            return True
    return False


def _chinese_author_earlier_evidence(text: str) -> bool:
    sentences = [
        part.strip() for part in re.split(r"[。！？.!?；;\n]+", text) if part.strip()
    ]
    return any(
        re.search(
            r"(?:童年|小时候|幼儿时期|童年时|少年时期|青春期|"
            r"(?:[0-2]?\d|[一二三四五六七八九十百两〇零○]+)岁)",
            sentence,
        )
        and _chinese_direct_author_subject(sentence)
        for sentence in sentences
    )


def _midlife_cue_is_author_scoped(text: str) -> bool:
    """Require an explicit storyteller subject for the age normalization.

    ``三十岁以后，我...`` and ``我三十岁以后...`` establish the
    storyteller's period.  A relative's age, a reported/quoted clause, or a
    bare age phrase does not.  The clause boundary deliberately stops only at
    sentence punctuation, so ``我姐姐三十岁以后...`` cannot become an
    implicit first-person claim merely because a comma follows the cue.
    """
    if not isinstance(text, str):
        return False
    if _later_stage_correction_rejects_prior_midlife(text):
        return False
    candidates: list[tuple[bool, bool]] = []
    for match in EXPLICIT_MIDLIFE_CUE.finditer(text):
        sentence_start = max(
            text.rfind(mark, 0, match.start())
            for mark in ("。", "！", "？", ".", "!", "?", "；", ";", "\n")
        ) + 1
        sentence_end_candidates = [
            text.find(mark, match.end())
            for mark in ("。", "！", "？", ".", "!", "?", "；", ";", "\n")
        ]
        sentence_end_candidates = [index for index in sentence_end_candidates if index >= 0]
        sentence_end = min(sentence_end_candidates) if sentence_end_candidates else len(text)
        sentence = text[sentence_start:sentence_end]
        relative_start = match.start() - sentence_start
        before = sentence[:relative_start].strip(" \t，,：:")
        after = sentence[match.end() - sentence_start:].lstrip(" \t，,：:")
        before = re.sub(
            r"^(?:更正|纠正|修正|改正)\s*[:：,，]?\s*",
            "",
            before,
        )

        # A direct first-person subject before the cue is authoritative.  Do
        # not accept ``我姐姐``/``我哥哥``: the possessive ``我`` is not the
        # subject whose age is being asserted.
        scoped = bool(re.fullmatch(
            r"(?:我|我们)(?:自己|本人)?(?:在|到|于|到了|到达)?", before
        ))
        # Chinese naturally places the period first: ``三十岁以后，我...``.
        # Require the following subject rather than treating a bare cue as
        # evidence about the author.
        if before in {"", "在", "到", "到了", "于"}:
            scoped = scoped or _chinese_direct_author_subject(
                after.lstrip(" \t，,：:"), require_first_subject=True
            )
        corrected = EXPLICIT_CORRECTION.search(sentence) is not None
        negated = EXPLICIT_MIDLIFE_NEGATION.search(sentence) is not None
        candidates.append((corrected, scoped and not negated))

    # A later correction is authoritative over a stale earlier stage cue.
    corrected_candidates = [scoped for corrected, scoped in candidates if corrected]
    if corrected_candidates:
        return corrected_candidates[-1]
    return any(scoped for _corrected, scoped in candidates)


def _drop_model_midlife_if_not_author_scoped(updates: dict[str, Any]) -> dict[str, Any]:
    """Keep non-stage profile fields while discarding a literal cue override."""
    focus = updates.get("story_focus")
    if not isinstance(focus, dict) or focus.get("life_stage") != "midlife":
        return updates
    focus = dict(focus)
    focus.pop("life_stage", None)
    if focus:
        updates["story_focus"] = focus
    else:
        updates.pop("story_focus", None)
    return updates


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
    if not isinstance(text, str):
        return validated or None
    if not EXPLICIT_MIDLIFE_CUE.search(text):
        focus = validated.get("story_focus") or {}
        # Corrections are especially prone to carrying forward a stale model
        # stage.  Preserve the previously validated stage by removing only an
        # unsupported model-supplied midlife value; other profile fields and
        # explicit non-stage updates still flow through the normal merge.
        if (
            isinstance(focus, dict)
            and focus.get("life_stage") == "midlife"
            and (
                _author_stage_evidence(text) == "non_midlife"
                or (CHINESE_STAGE_BOUNDARY.search(text) and _author_stage_evidence(text) == "non_midlife")
                or (EXPLICIT_CORRECTION.search(text) and _author_stage_evidence(text) != "midlife")
            )
        ):
            return _drop_model_midlife_if_not_author_scoped(validated) or None
        return validated or None
    scoped_midlife = _midlife_cue_is_author_scoped(text)
    stage_evidence = _author_stage_evidence(text)
    if EXPLICIT_MIDLIFE_NEGATION.search(text) or (
        not scoped_midlife and stage_evidence == "non_midlife"
    ):
        return _drop_model_midlife_if_not_author_scoped(validated) or None
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
