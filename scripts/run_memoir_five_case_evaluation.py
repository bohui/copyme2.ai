#!/usr/bin/env python3
"""Run the reusable five-case Memoir evaluation.

The default live path uses the configured private-worker/provider boundary.
``--mode fixture`` uses the same ``CodexRuntime`` orchestration and isolated
storage boundary with a deterministic worker response.  Fixture output is
explicitly marked ``mock_only`` and is never a live-model quality result.

The runner intentionally keeps executable code here, while inputs, hidden
truth, expected outcomes, judge prompt, and calibration remain separate
checked-in files under ``tests/evaluation``.
"""

from __future__ import annotations

import argparse
import asyncio
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
from pathlib import PurePosixPath
import re
import shutil
import subprocess
import sys
import time
from typing import Any, Mapping
from uuid import uuid4

import httpx


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from apps.api.codex_runtime import CodexRuntime
from apps.api.family_context import family_features_enabled
from apps.api.memoir_preview import (
    compose_candidate,
    incremental_index_request,
    snapshot_key,
    source_snapshot,
)
from apps.api.place_groups import resolve_place_groups
from apps.api.trajectory_evaluation import (
    EVALUATION_RUBRIC_VERSION,
    JUDGE_RUBRIC_VERSION,
    LangfusePublisher,
    TrajectoryRecorder,
    build_application_revision,
    build_skill_manifest,
    load_judge_calibration,
    normalise_correlation,
    redact_payload,
)
from apps.api.codex_runtime import normalize_conversation_language
from scripts.memoir_five_case_evaluator import (
    LIFE_STAGES,
    SKILLS,
    aggregate_case,
    case_expectations,
    evaluate_round,
    build_langfuse_round_scores,
    load_json,
    mark_round_unavailable,
    merge_ui_skill_observations,
    validate_expected,
    validate_inputs,
    expected_round,
)


INPUTS_PATH = ROOT / "tests/evaluation/memoir_five_case_inputs.json"
EXPECTED_PATH = ROOT / "tests/evaluation/memoir_five_case_expected.json"
TRUTH_PATH = ROOT / "tests/evaluation/memoir_five_case_truth.json"
CALIBRATION_PATH = ROOT / "tests/evaluation/memoir_five_case_judge_calibration.json"
JUDGE_PROMPT_PATH = ROOT / "tests/evaluation/memoir_five_case_judge_prompt.md"
RUNNER_VERSION = "memoir-five-case-runner/4"
EXECUTION_MODES = {"fixture", "live", "pilot"}
DEFAULT_PROVIDER = "http://127.0.0.1:4000/v1"
DEFAULT_MODEL = "gpt-5.6-luna-pooled"
COMPOSE_WORKER_URL = "http://codex-worker:8766"
COMPOSE_PHOTO_WORKER_URL = "http://photo-worker:8767"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def json_safe(value: Any) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False, default=str))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def langfuse_deterministic_status(grade: Mapping[str, Any]) -> str:
    """Keep root telemetry status aligned with the local deterministic grade."""
    status = str(grade.get("overall") or "unavailable")
    return status if status in {"pass", "fail", "unavailable", "mock_only"} else "unavailable"


def parse_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw_line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("\"'")
        if key:
            values[key] = value
    return values


def configured_env(name: str, env_file: Mapping[str, str]) -> str:
    return os.getenv(name, env_file.get(name, "")).strip()


def provider_config(env_file: Mapping[str, str], override_url: str | None = None, override_model: str | None = None) -> dict[str, Any]:
    base_url = (override_url or configured_env("MEMORY_SPARK_LLM_BASE_URL", env_file) or DEFAULT_PROVIDER).rstrip("/")
    model = override_model or configured_env("MEMORY_SPARK_LLM_MODEL", env_file) or DEFAULT_MODEL
    return {
        "base_url": base_url,
        "model": model,
        "api_key_configured": bool(configured_env("MEMORY_SPARK_LLM_API_KEY", env_file)),
        "provider_name": configured_env("MEMORY_SPARK_LLM_PROVIDER", env_file) or "configured",
        "reasoning_effort": configured_env("MEMORY_SPARK_LLM_REASONING_EFFORT", env_file) or configured_env("MEMORY_SPARK_REASONING_EFFORT", env_file) or "unknown",
    }


def command_version(command: str) -> str | None:
    try:
        result = subprocess.run([command, "--version"], cwd=ROOT, check=False, capture_output=True, text=True, timeout=3)
    except (OSError, subprocess.TimeoutExpired):
        return None
    text = (result.stdout or result.stderr or "").strip().splitlines()
    return text[0][:256] if text else None


def validate_dataset(inputs: Mapping[str, Any], expected: Mapping[str, Any]) -> list[str]:
    errors = validate_inputs(inputs)
    input_ids = {str(item.get("id")) for item in inputs.get("cases", []) if isinstance(item, Mapping)}
    errors.extend(validate_expected(expected, input_ids))
    if len({case.get("project_id") for case in inputs.get("cases", [])}) != 5:
        errors.append("project_id values must be unique across the five isolated cases")
    return errors


class CaseStorage:
    """Small isolated storage adapter exercising the production runtime seam."""

    def __init__(self, case: Mapping[str, Any], state: Mapping[str, Any] | None = None):
        self.user_id = str(state.get("user_id")) if state and state.get("user_id") else str(uuid4())
        self.project_id = str(case["project_id"])
        self.case_id = str(case["id"])
        self._profile = deepcopy((state or {}).get("profile") or {})
        self._memories = deepcopy((state or {}).get("memories") or [])
        self._place = deepcopy((state or {}).get("place"))
        self._place_history = deepcopy((state or {}).get("place_history") or [])
        self._family = deepcopy((state or {}).get("family"))
        self._session = deepcopy((state or {}).get("session"))
        self._lease_token: str | None = None
        self._revision = int((state or {}).get("place_revision") or 0)
        self._rounds_completed = int((state or {}).get("rounds_completed") or 0)
        self._memory_counter = int((state or {}).get("memory_counter") or 0)
        self._family_enabled = bool((state or {}).get("family_enabled", True))
        self._agent_artifacts = deepcopy((state or {}).get("agent_artifacts") or [])

    def set_round_entitlement(self, enabled: bool) -> None:
        self._family_enabled = bool(enabled)

    def acquire_agent_turn_lease(self, token: str, lease_seconds: int = 300) -> bool:
        if self._lease_token is not None:
            return False
        self._lease_token = token
        return True

    def renew_agent_turn_lease(self, token: str, lease_seconds: int = 300) -> bool:
        return token == self._lease_token

    def release_agent_turn_lease(self, token: str) -> bool:
        if token != self._lease_token:
            return False
        self._lease_token = None
        return True

    @staticmethod
    def agent_path(relative: str) -> str:
        """Apply the same artifact-path boundary as UserStorage.

        The evaluator must exercise CodexRuntime's production artifact path
        without writing into a user's real storage bucket.  The isolated
        adapter therefore validates the exact production path contract and
        retains only metadata for each synthetic artifact.
        """
        path = PurePosixPath(relative)
        if (
            not isinstance(relative, str)
            or path.is_absolute()
            or relative != path.as_posix()
            or any(part.startswith(".") for part in path.parts)
            or len(path.parts) < 2
            or path.parts[0] not in {"sessions", "archived_sessions", "memories"}
        ):
            raise ValueError("Only Codex session and memory artifacts may be synchronized")
        return path.as_posix()

    def put_agent_turn_file(self, lease_token: str, relative: str, content: bytes) -> str:
        """Capture an artifact through the production lease-fenced seam.

        Bytes are intentionally reduced to size/hash metadata so per-round
        traces never become a second copy of the worker transcript.
        """
        if lease_token != self._lease_token:
            raise RuntimeError("isolated artifact write is outside the lease")
        root, tail = self.agent_path(relative).split("/", 1)
        path = f"{root}/turns/{lease_token}/{tail}"
        self._agent_artifacts.append({
            "path": path,
            "bytes": len(content),
            "sha256": hashlib.sha256(content).hexdigest(),
        })
        return path

    def agent_session(self):
        return deepcopy(self._session)

    def memories(self):
        return deepcopy(list(reversed(self._memories)))

    def all_memories(self, **_: Any):
        return deepcopy(self._memories)

    def composition_memories(self):
        return deepcopy(self._memories)

    def profile(self):
        return deepcopy(self._profile)

    def save_profile(self, profile, **kwargs):
        self._profile = deepcopy(profile or {})
        return [deepcopy(self._profile)]

    def place_journey(self):
        return deepcopy(self._place)

    def place_history(self):
        return deepcopy(self._place_history)

    def story_entitlement(self):
        return {
            "status": "paid",
            "plan_key": "family_memoir_v1",
            "family_tree": self._family_enabled,
            "timeline": self._family_enabled,
            "expanded_details": self._family_enabled,
            "stripe_price_id": os.getenv("STRIPE_PRICE_FAMILY", "") or "synthetic-family-price",
        }

    def recall_rounds_completed(self):
        return self._rounds_completed

    def family_context(self, project_id):
        if project_id != self.project_id:
            raise ValueError("cross-project family context read")
        return deepcopy(self._family)

    def upsert_family_context(self, project_id, document, expected_revision=0):
        if project_id != self.project_id:
            raise ValueError("cross-project family context write")
        current_revision = int((self._family or {}).get("revision") or 0)
        if current_revision != int(expected_revision):
            raise RuntimeError("isolated family revision conflict")
        saved = deepcopy(document)
        saved["revision"] = current_revision + 1
        saved["updated_at"] = utc_now()
        self._family = saved
        return {"document": deepcopy(saved), "revision": saved["revision"], "changed": True}

    def save_place_journey(self, lease_token, candidate, *, source_sequence=None):
        if lease_token != self._lease_token:
            raise RuntimeError("isolated place write is outside the lease")
        self._revision += 1
        saved = {
            **deepcopy(candidate),
            "status": "active",
            "revision": self._revision,
            "updated_at": utc_now(),
        }
        if source_sequence is not None:
            saved["source_sequence"] = source_sequence
        self._place = saved
        self._place_history.append(deepcopy(saved))
        return deepcopy(saved)

    def commit_agent_turn(self, lease_token, thread_id, text, source_paths, *, source_sequence=None, **kwargs):
        if lease_token != self._lease_token:
            raise RuntimeError("isolated conversation write is outside the lease")
        self._session = {"codex_thread_id": thread_id, "status": "active"}
        self._memory_counter += 1
        record = {
            "id": f"memory-{self.case_id[:18]}-{self._memory_counter:03d}",
            "kind": "agent",
            "project_id": self.project_id,
            "content": text,
            "source_paths": list(source_paths or []),
            "source_sequence": int(source_sequence or self._memory_counter),
            "life_stage": "unplaced",
            "created_at": utc_now(),
        }
        self._memories.append(record)
        self._rounds_completed += 1
        return [deepcopy(record)]

    def assign_memory_stage(self, memory_id, life_stage):
        for record in self._memories:
            if record.get("id") == memory_id:
                record["life_stage"] = life_stage
                return [deepcopy(record)]
        raise ValueError("isolated memory not found")

    def save_memory(self, text, *, kind="memoir", source_paths=None):
        self._memory_counter += 1
        record = {
            "id": f"memory-{self.case_id[:18]}-{self._memory_counter:03d}",
            "kind": kind,
            "project_id": self.project_id,
            "content": text,
            "source_paths": list(source_paths or []),
            "source_sequence": self._memory_counter,
            "life_stage": "unplaced",
            "created_at": utc_now(),
        }
        self._memories.append(record)
        return [deepcopy(record)]

    def state_snapshot(self) -> dict[str, Any]:
        return {
            "user_id": self.user_id,
            "project_id": self.project_id,
            "profile": deepcopy(self._profile),
            "memories": deepcopy(self._memories),
            "place": deepcopy(self._place),
            "place_history": deepcopy(self._place_history),
            "family": deepcopy(self._family),
            "session": deepcopy(self._session),
            "place_revision": self._revision,
            "rounds_completed": self._rounds_completed,
            "memory_counter": self._memory_counter,
            "family_enabled": self._family_enabled,
            "agent_artifacts": deepcopy(self._agent_artifacts),
        }


FIXTURE_STAGE_BANDS = (
    (1, 2, "baby"),
    (3, 7, "toddler"),
    (8, 15, "childhood"),
    (16, 22, "adolescence"),
    (23, 30, "young_adulthood"),
    (31, 38, "midlife"),
    (39, 46, "later_life"),
)
FIXTURE_EN_PLACE_LABELS = (
    "Hobart", "Launceston", "Kingston", "Perth", "Fremantle", "Adelaide",
    "Sydney", "Wollongong", "Canberra",
)
FIXTURE_ZH_PLACE_LABELS = ("成都", "大理", "重庆", "昆明", "贵阳")
FIXTURE_RELATIONSHIP_TERMS = {
    "sister": "sister", "brother": "brother", "mother": "mother", "father": "father",
    "mum": "mother", "dad": "father", "grandmother": "grandmother", "grandfather": "grandfather",
    "aunt": "aunt", "uncle": "uncle", "cousin": "cousin", "partner": "partner",
    "friend": "friend", "neighbour": "friend", "neighbor": "friend", "children": "child",
    "child": "child",
    "哥哥": "brother", "姐姐": "sister", "母亲": "mother", "父亲": "father",
    "外婆": "grandmother", "祖母": "grandmother", "伴侣": "partner", "朋友": "friend",
    "孩子": "child", "家人": "family",
}


def _fixture_round_from_memories(memories: Any) -> int:
    rows = memories if isinstance(memories, list) else []
    return len(rows) + 1


def _fixture_stage(memories: Any) -> str | None:
    round_number = _fixture_round_from_memories(memories)
    for start, end, stage in FIXTURE_STAGE_BANDS:
        if start <= round_number <= end:
            return stage
    # The final four turns are review turns. They deliberately retain the
    # current persisted stage rather than inventing a new stage.
    return None


def _fixture_places(text: str) -> list[str]:
    """Lex only the current storyteller message; never consult hidden truth."""
    labels = FIXTURE_EN_PLACE_LABELS + FIXTURE_ZH_PLACE_LABELS
    found = [(match.start(), label) for label in labels for match in re.finditer(re.escape(label), text, re.IGNORECASE)]
    ordered: list[str] = []
    for _, label in sorted(found):
        if label not in ordered:
            ordered.append(label)
    lowered = text.casefold()
    # A historical-only/public-history reference and an unresolved label are
    # explicitly negative cases in the place skill contract. A present-day
    # public reference remains actionable and is intentionally not filtered.
    historical_only = (
        ("historical" in lowered and "photo" in lowered)
        or "public history" in lowered
        or "历史参考" in text
        or "公共老照片" in text
    )
    ambiguous = (
        "not sure which" in lowered
        or "unsure which" in lowered
        or "clarify rather than" in lowered
        or "ask instead of mapping" in lowered
        or "ask rather than map" in lowered
        or "不确定是哪" in text
        or "请先问" in text
        or "请先问我" in text
    )
    if historical_only or ambiguous:
        return []
    return ordered


def _fixture_coordinate(label: str) -> tuple[float, float]:
    # Synthetic coarse coordinates are only to keep the fixture's grouping
    # service offline. They are deliberately not copied from hidden truth or
    # presented as real geocoding evidence.
    digest = hashlib.sha256(label.casefold().encode("utf-8")).digest()
    latitude = -60.0 + (int.from_bytes(digest[:4], "big") / 2**32) * 120.0
    longitude = -170.0 + (int.from_bytes(digest[4:8], "big") / 2**32) * 340.0
    return round(latitude, 5), round(longitude, 5)


def _marker_profile(memories: Any, text: str) -> str:
    stage = _fixture_stage(memories)
    if not stage:
        return ""
    places = _fixture_places(text)
    focus: dict[str, Any] = {"life_stage": stage, "what": text[:240]}
    if places:
        focus["where"] = places[0]
    return "[[MEMORY_SPARK_PROFILE]]" + json.dumps({"story_focus": focus, "name": ""}, ensure_ascii=False) + "[[/MEMORY_SPARK_PROFILE]]"


def _marker_places(text: str) -> str:
    parts: list[str] = []
    for place in _fixture_places(text):
        latitude, longitude = _fixture_coordinate(place)
        payload = {
            "schema_version": 1,
            "place": place,
            "hierarchy": ["Earth", place],
            "granularity": "city",
            "latitude": latitude,
            "longitude": longitude,
            "duration_ms": 5200,
        }
        parts.append("[[MEMORY_SPARK_PLACE_JOURNEY]]" + json.dumps(payload, ensure_ascii=False) + "[[/MEMORY_SPARK_PLACE_JOURNEY]]")
    return "".join(parts)


def _fixture_people(text: str, prior_context: Mapping[str, Any] | None = None) -> list[dict[str, Any]]:
    people: list[dict[str, Any]] = []
    prior_people = [item for item in (prior_context or {}).get("people", []) if isinstance(item, Mapping)]
    lower = text.casefold()
    for term, family_title in FIXTURE_RELATIONSHIP_TERMS.items():
        term_present = bool(re.search(rf"\b{re.escape(term.casefold())}\b", lower)) if term.isascii() else term in text
        if not term_present:
            continue
        name = term
        # English turns usually provide a proper name immediately after the
        # relationship; using it makes corrections stable without knowing the
        # hidden family fixture.
        if term.isascii():
            match = re.search(
                rf"\b(?i:{re.escape(term)})\b(?:\s+(?i:called|named|is))?\s+([A-Z][a-z]+)",
                text,
            )
            if match:
                name = match.group(1)
        elif term in {"朋友", "伴侣"}:
            match = re.search(rf"{re.escape(term)}(?:叫|是|为)?\s*([\u4e00-\u9fff]{{2,4}})", text)
            if match:
                name = match.group(1)
        slug = "fixture-person-" + hashlib.sha256(name.casefold().encode("utf-8")).hexdigest()[:12]
        prior = next((item for item in prior_people if str(item.get("name")) == name), None)
        record: dict[str, Any] = {
            "id": slug,
            "name": name,
            "family_title": family_title,
            "visibility": "private",
            "living_status": "unknown",
        }
        if prior and ("correction" in lower or "更正" in text or "revise" in lower or "update" in lower):
            record["existing_id"] = str(prior.get("id"))
        if not any(item["id"] == record["id"] for item in people):
            people.append(record)
    # A previously identified person mentioned again is still an explicit
    # relationship signal in the visible conversation.  Reusing the prior
    # record keeps corrections and repeated references tied to application
    # state without consulting the hidden dataset truth.
    for prior in prior_people:
        name = str(prior.get("name") or "").strip()
        if not name:
            continue
        name_present = bool(re.search(rf"\b{re.escape(name.casefold())}\b", lower)) if name.isascii() else name in text
        if not name_present:
            continue
        record = deepcopy(dict(prior))
        if "correction" in lower or "更正" in text or "revise" in lower or "update" in lower:
            record["existing_id"] = str(prior.get("id"))
        if not any(item["id"] == record.get("id") for item in people):
            people.append(record)
    return people


def _has_timeline_cue(text: str) -> bool:
    """Recognise explicit author-event timing, not generic temporal prose.

    This is intentionally a visible-input heuristic for the offline fixture,
    not a replacement for the production timeline skill.  In particular,
    photo capture dates and historical/public-photo context are negative
    cases: they should not create an author timeline event merely because a
    year or an approximate date appears in the request.
    """
    lowered = text.casefold()
    photo_context = bool(re.search(r"\b(?:photo|photograph|snapshot|image|picture)\b|照片|老照片|图像|相片", lowered))
    first_person_event = bool(
        re.search(
            r"\b(?:i|we)\b(?:\s+\w+){0,4}\s+\b(?:arrived|born|lived|moved|returned|left|spent|started|began|opened|attended|learned|worked|cared|travelled|traveled|met|married|raised|joined|graduated|studied|wrote|remember|remembered|recall|recalled|took|rented|chose|chosen|kept|followed|argued|visited|taught|ran)\b",
            lowered,
        )
        or re.search(r"(?:我|我们)[^。！？\n]{0,80}(?:出生|住在|住过|住几天|居住|租房|搬|回到|离开|度过|开始|开办|参加|学习|工作|照顾|旅行|结婚|抚养|加入|毕业|写|经营|记得|争论|租|带回|教|改成|跟着|搬家|发生)", text)
    )
    direct_action_event = bool(
        re.search(r"\b(?:i|we)\b(?:\s+\w+){0,4}\s+\b(?:arrived|born|lived|moved|returned|left|spent|started|began|opened|attended|learned|worked|cared|travelled|traveled|met|married|raised|joined|graduated|studied|wrote|took|rented|chose|chosen|kept|followed|argued|visited|taught|ran)\b", lowered)
        or re.search(r"(?:我|我们)[^。！？\n]{0,50}(?:出生|住在|住过|住几天|居住|租房|搬|回到|离开|度过|开始|开办|参加|学习|工作|照顾|旅行|结婚|抚养|加入|毕业|写|经营|争论|租|带回|教|改成|跟着|搬家|发生)", text)
    )
    source_boundary = bool(
        re.search(r"\b(?:family account|family history|family source|source material|not direct|not evidence|do not remember|don't remember|cannot remember|can't remember|personally remember)\b", lowered)
        or re.search(r"(?:difference between what .* remembers and what I .* remember|directly remember|preserve the difference)", lowered)
        or re.search(r"(?:家庭叙述|家庭材料|家人的回忆来源|没有直接记忆|不能确认|不是我的亲历|不替代我的亲历|不是.*证据)", text)
    )
    if source_boundary and not direct_action_event:
        return False
    non_event_reflection = bool(
        re.search(r"\b(?:not|no)\s+(?:a\s+)?(?:dated\s+|timeline\s+|chronological\s+)?event\b|\b(?:review-only|review only|chronological memoir|chronological review)\b|\breflections?\b[^.?!\n]{0,80}\b(?:no date|not|rather than)\b", lowered)
        or re.search(r"(?:不一定|不要强行|不要把.*写成|不想把.*补写|不编造因果|保留在故事之外|保留.*空白|没有.*日期|没有.*年份).*(?:事件|时间线|初稿|反思|回望|空白|事实|经历|因果)?", text)
    )
    if photo_context and not first_person_event:
        return False

    third_party_timing = bool(
        re.search(r"\b(?:whether|unsure|uncertain|cannot tell|not certain)\b[^.?!\n]{0,80}\b[A-Z][a-z]+\b\s+(?:moved|left|went|returned|graduated|married)\b", text)
        or re.search(r"(?:不确定|不清楚|无法确定)[^。！？\n]{0,60}(?:去了|离开|毕业前|毕业后|之前|之后)", text)
    )
    if third_party_timing:
        return False

    explicit_date = bool(
        re.search(r"(?:18|19|20)\d{2}", text)
        or re.search(r"\b(?:year|date|month|season|age|aged|born|calendar|chronolog)\b", lowered)
        or re.search(r"\b(?:around|approximately|approximate|roughly|uncertain|unclear)\s+(?:the\s+)?(?:age|year|date|month|time|period)\b", lowered)
        or re.search(r"\b(?:at|around)\s+(?:age\s+)?(?:about\s+)?(?:three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|twenty|twenties|thirty|thirties|forty|forties|\d{1,2})\b", lowered)
        or re.search(r"\b(?:early|mid|late)[ -](?:teen|teens|twenties|thirties|forties|fifties|sixties|seventies|eighties|nineties|\d{1,2}s?)\b", lowered)
        or re.search(r"\b(?:last|final|first|next|several|many)\s+(?:year|years|month|months|winter|summer|spring|autumn|season|decade)s?\b", lowered)
        or re.search(r"\bpart\s+of\s+the\s+year\b", lowered)
        or re.search(r"\b(?:before|after)\s+(?:or|and)\s+(?:after|before)\b", lowered)
        or re.search(r"\b(?:time order|chronology|chronological|sequence|which came first)\b", lowered)
        or re.search(r"(?:大约|约|前后|年份|日期|月份|年龄|岁|期间|时间顺序|先后|具体年份|不记准|无法确认|出生|二十多|三十岁|十六岁|十四岁|十五岁|二十四|二十五|一九|二〇|一九九|二〇〇)", text)
    )
    period_statement = bool(re.search(r"\b(?:that|this|the)\s+(?:late|early|mid|uncertain|adolescent|teenage)[^.!?\n]{0,80}\b(?:belongs|period|winter|season)\b", lowered))
    contextual_event = bool(
        re.search(r"(?:童年|幼儿|青春期|成年|晚年)[^。！？\n]{0,40}(?:搬家|搬动|发生|住过|工作|课程|考试)", text)
    )
    correction_event = bool(
        re.search(r"\bcorrection\b", lowered)
        and re.search(r"\b(?:18|19|20)\d{2}\b|\b(?:around|approximately|approximate)\b", lowered)
        and re.search(r"\b(?:move|moved|studio|office|apprenticeship|date|year)\w*\b", lowered)
        or re.search(r"更正", text)
        and re.search(r"(?:一九|二〇|大约|前后|年份|日期)", text)
    )
    return (explicit_date or first_person_event or period_statement or correction_event or contextual_event) and not non_event_reflection and (first_person_event or period_statement or correction_event or contextual_event)


def _marker_family(memories: Any, text: str, family_enabled: bool, family_context: Mapping[str, Any] | None = None) -> str:
    if not family_enabled:
        return ""
    prior = family_context if isinstance(family_context, Mapping) else {}
    people = _fixture_people(text, prior)
    result: list[str] = []
    if people:
        result.append("[[MEMORY_SPARK_FAMILY_TREE]]" + json.dumps({"people": people, "relationships": []}, ensure_ascii=False) + "[[/MEMORY_SPARK_FAMILY_TREE]]")
    if _has_timeline_cue(text):
        expression = "unknown"
        year = re.search(r"(?:18|19|20)\d{2}", text)
        if year:
            expression = f"around {year.group(0)}"
        elif re.search(r"(?:大约|around|about|approximate|估计|前后|二十多|三十岁|十六岁|十四岁|十五岁|二十四|二十五)", text, re.IGNORECASE):
            expression = text[:120]
        timeline = {
            "timeline": [{
                "id": "fixture-event-" + hashlib.sha256(text.encode("utf-8")).hexdigest()[:12],
                "title": text[:80] or "Remembered event",
                "kind": "event",
                "date_expression": expression,
                "precision": "unknown" if expression == "unknown" else "approximate",
            }],
        }
        result.append("[[MEMORY_SPARK_AUTHOR_TIMELINE]]" + json.dumps(timeline, ensure_ascii=False) + "[[/MEMORY_SPARK_AUTHOR_TIMELINE]]")
    return "".join(result)


class FixtureWorker:
    """Synthetic private worker used only by ``--mode fixture``."""

    def __init__(self, case: Mapping[str, Any]):
        self.case = case
        self.current_round = 0
        self.calls: list[dict[str, Any]] = []

    def set_round(self, round_number: int) -> None:
        self.current_round = round_number

    def _composer_index(self, packet: Mapping[str, Any]) -> dict[str, Any]:
        request = packet
        context = request.get("context") if isinstance(request.get("context"), Mapping) else {}
        sources = [source for source in request.get("sources", []) if isinstance(source, Mapping)]
        stage_index = {stage: index for index, stage in enumerate(LIFE_STAGES)}
        periods: dict[str, dict[str, Any]] = {}
        for source in sources:
            stage = str(source.get("life_stage") or "unplaced")
            period_id = "period_" + re.sub(r"[^A-Za-z0-9_-]+", "_", stage)
            periods.setdefault(period_id, {
                "id": period_id,
                "order": stage_index.get(stage, len(LIFE_STAGES)),
                "label": stage.replace("_", " ").title(),
                "source_refs": [{"source_id": source["id"], "version": source["version"]}],
            })
        events = []
        for source in sources:
            stage = str(source.get("life_stage") or "unplaced")
            period_id = "period_" + re.sub(r"[^A-Za-z0-9_-]+", "_", stage)
            events.append({
                "id": "event_" + re.sub(r"[^A-Za-z0-9_-]+", "_", str(source["id"])),
                "period_id": period_id if stage != "unplaced" else None,
                "summary": str(source.get("text") or "")[:180],
                "source_refs": [{"source_id": source["id"], "version": source["version"]}],
                "date": {"original_expression": "unknown", "start_year": None, "end_year": None, "precision": "unknown"},
                "status": "active",
                "narrative": True,
            })
        # The index worker may receive a batch. Keep existing entries so the
        # production incremental-index merge can exercise its revision path.
        previous = context.get("previous_index") if isinstance(context, Mapping) else None
        if isinstance(previous, Mapping):
            existing_periods = {str(item.get("id")): item for item in previous.get("periods", []) if isinstance(item, Mapping)}
            existing_events = {str(item.get("id")): item for item in previous.get("events", []) if isinstance(item, Mapping)}
            existing_periods.update(periods)
            existing_events.update({str(item["id"]): item for item in events})
            periods = existing_periods
            events = list(existing_events.values())
        return {"periods": sorted(periods.values(), key=lambda item: (item["order"], item["id"])), "events": events}

    @staticmethod
    def _ref(source: Mapping[str, Any]) -> dict[str, str]:
        return {"source_id": str(source["id"]), "version": str(source["version"])}

    def _draft(self, packet: Mapping[str, Any]) -> dict[str, Any]:
        request = packet["request"]
        plan = packet["plan"]
        kind = plan["kind"]
        sources = [source for source in request.get("sources", []) if isinstance(source, Mapping)]
        periods = [period for period in request.get("periods", []) if isinstance(period, Mapping)]
        events = [event for event in request.get("events", []) if isinstance(event, Mapping)]
        event_by_period: dict[str, list[Mapping[str, Any]]] = {}
        for event in events:
            if event.get("period_id") is not None:
                event_by_period.setdefault(str(event["period_id"]), []).append(event)
        source_by_id = {str(source["id"]): source for source in sources}

        def refs_for(items: list[Mapping[str, Any]]) -> list[dict[str, str]]:
            refs: list[dict[str, str]] = []
            for item in items:
                for ref in item.get("source_refs", []):
                    key = (ref.get("source_id"), ref.get("version"))
                    if key not in {(r.get("source_id"), r.get("version")) for r in refs}:
                        refs.append({"source_id": str(ref["source_id"]), "version": str(ref["version"])})
            return refs

        def block(block_id: str, text: str, refs: list[dict[str, str]]) -> dict[str, Any]:
            return {"id": block_id, "type": "paragraph", "text": text, "asset_id": None, "asset_version": None,
                    "caption": "", "alt": "", "credit": "", "source_refs": refs, "uncertainty": []}

        def chapter(period: Mapping[str, Any], chapter_id: str, selected_events: list[Mapping[str, Any]], base_revision: int = 0) -> dict[str, Any]:
            selected_sources = [source_by_id[ref["source_id"]] for event in selected_events for ref in event.get("source_refs", []) if ref.get("source_id") in source_by_id]
            refs = refs_for(selected_events)
            blocks = [block("block_" + chapter_id + "_" + str(index), str(source.get("text") or "")[:1200], [self._ref(source)]) for index, source in enumerate(selected_sources)]
            if not blocks:
                blocks = [block("block_" + chapter_id, "The available testimony for this period is kept as a bounded note.", refs)]
            return {"id": chapter_id, "base_revision": base_revision, "title": str(period.get("label") or "Remembered period"),
                    "subtitle": "", "period_ids": [str(period["id"])], "event_ids": [str(event["id"]) for event in selected_events],
                    "source_refs": refs, "blocks": blocks, "change_type": "create", "update_reason": "Fixture draft uses only the supplied fictional storyteller sources."}

        source_summary = []
        for event in events:
            source_summary.append({"id": "summary_" + str(event["id"]), "text": str(event.get("summary") or "")[:180],
                                   "source_refs": deepcopy(event.get("source_refs") or []), "event_ids": [str(event["id"])], "uncertainty": ["date not resolved"]})
        if not source_summary and sources:
            source_summary = [{"id": "summary_" + str(source["id"]), "text": str(source.get("text") or "")[:180], "source_refs": [self._ref(source)], "event_ids": [], "uncertainty": ["date not resolved"]} for source in sources]

        chapters: list[dict[str, Any]] = []
        outline: list[dict[str, Any]] = []
        dispositions: list[dict[str, Any]] = []
        storyline = {"title": "", "source_refs": [], "event_ids": [], "blocks": []}
        if kind == "formal_memoir":
            selected_periods = periods
            for index, period in enumerate(selected_periods):
                selected = event_by_period.get(str(period["id"]), [])
                if not selected:
                    continue
                current = chapter(period, "chapter_" + str(period["id"]), selected)
                chapters.append(current)
                outline.append({"chapter_id": current["id"], "order": index, "title": current["title"], "period_ids": current["period_ids"], "event_ids": current["event_ids"], "status": "draft", "rationale": "Chronological grouping of supplied testimony.", "source_refs": current["source_refs"]})
                for event in selected:
                    dispositions.append({"event_id": str(event["id"]), "disposition": "included", "chapter_ids": [current["id"]], "reason": "Included in its grounded chronological chapter."})
            disposition_ids = {item["event_id"] for item in dispositions}
            for event in events:
                if str(event["id"]) not in disposition_ids:
                    dispositions.append({"event_id": str(event["id"]), "disposition": "unplaced", "chapter_ids": [], "reason": "The timing is unresolved, so this testimony is retained without inventing a period."})
        elif kind == "sample_chapter":
            selected_period = next((period for period in periods if event_by_period.get(str(period["id"]))), None)
            selected = event_by_period.get(str(selected_period["id"]), []) if selected_period else []
            if selected_period:
                current = chapter(selected_period, "chapter_" + str(selected_period["id"]), selected)
                chapters = [current]
                outline = [{"chapter_id": current["id"], "order": 0, "title": current["title"], "period_ids": current["period_ids"], "event_ids": current["event_ids"], "status": "draft", "rationale": "A focused sample bounded to one grounded period.", "source_refs": current["source_refs"]}]
                selected_ids = {str(event["id"]) for event in selected}
                dispositions = [{"event_id": str(event["id"]), "disposition": "included" if str(event["id"]) in selected_ids else "deferred", "chapter_ids": [current["id"]] if str(event["id"]) in selected_ids else [], "reason": "Included in the focused sample." if str(event["id"]) in selected_ids else "Deferred outside the focused sample."} for event in events]
        else:
            all_refs = refs_for(events) or [self._ref(source) for source in sources]
            storyline = {"title": "A grounded line through the memories", "source_refs": all_refs,
                         "event_ids": [str(event["id"]) for event in events],
                         "blocks": [block("storyline_" + str(index), str(source.get("text") or "")[:1200], [self._ref(source)]) for index, source in enumerate(sources)] or [block("storyline_note", "The available testimony is kept as an evidence-linked outline.", all_refs)]}
            outline = [{"chapter_id": "planned_" + str(period["id"]), "order": int(period.get("order", index)), "title": str(period.get("label") or "Remembered period"), "period_ids": [str(period["id"])], "event_ids": [str(event["id"]) for event in event_by_period.get(str(period["id"]), [])], "status": "planned", "rationale": "Held as a future evidence-linked chapter, not presented as a completed chapter.", "source_refs": deepcopy(period.get("source_refs") or [])} for index, period in enumerate(periods)]
            dispositions = [{"event_id": str(event["id"]), "disposition": "included", "chapter_ids": [], "reason": "Included in the bounded chronological storyline."} for event in events]

        return {
            "schema_version": "1.0",
            "project_id": request["project_id"],
            "input_snapshot_id": request["snapshot"]["id"],
            "input_fingerprint": plan["input_fingerprint"],
            "expected_manuscript_revision": request["prior_state"]["revision"],
            "kind": kind,
            "status": "draft",
            "title": "A fictional life kept in the storyteller's words" if request["target"]["locale"] != "zh-CN" else "用讲述者的话保存的一生",
            "title_source_refs": ([self._ref(sources[0])] if sources else []),
            "counter": deepcopy(plan["counter"]),
            "source_summary": source_summary,
            "outline": outline,
            "chapters": chapters,
            "storyline": storyline,
            "carry_forward_chapter_ids": [],
            "retired_chapter_ids": [],
            "proposed_replacements": [],
            "event_dispositions": dispositions,
            "questions_for_mira": [],
            "review_flags": [],
            "next_action": "review_manuscript" if kind == "formal_memoir" else "review_preview",
        }

    @staticmethod
    def _review(packet: Mapping[str, Any]) -> dict[str, Any]:
        return {"ready_for_user_review": True, "publication_approved": False, "findings": []}

    async def turn(self, **kwargs: Any) -> dict[str, Any]:
        role = str(kwargs.get("agent_role") or "collector")
        text = str(kwargs.get("text") or "")
        self.calls.append({"agent_role": role, "round": self.current_round, "text_chars": len(text)})
        if role == "composer":
            try:
                packet = json.loads(text)
            except (TypeError, ValueError):
                packet = {}
            phase = str(kwargs.get("composer_phase") or "draft")
            payload = self._composer_index(packet) if phase == "index" else self._draft(packet) if phase == "draft" else self._review(packet)
            return {"thread_id": f"fixture-composer-{self.current_round:03d}", "reply": json.dumps(payload, ensure_ascii=False), "artifacts": [], "usage": {"fixture": True}}
        if role == "workspace":
            memories = kwargs.get("memories") or []
            family_enabled = bool(kwargs.get("family_enabled"))
            family_context = kwargs.get("family_context") if isinstance(kwargs.get("family_context"), Mapping) else {}
            reply = _marker_profile(memories, text) + _marker_places(text) + _marker_family(memories, text, family_enabled, family_context)
            return {"thread_id": f"fixture-workspace-{self.current_round:03d}", "reply": reply, "artifacts": [], "trajectory": {"steps": []}, "_workspace_capable": True}
        locale = normalize_conversation_language(kwargs.get("language"))
        reply = "I hear the detail. I’ll keep its source and uncertainty clear." if locale != "zh-CN" else "我听见了这个细节，会保留它的来源和不确定性。"
        return {"thread_id": f"fixture-collector-{self.current_round:03d}", "reply": reply, "artifacts": [], "trajectory": {"steps": []}, "_workspace_capable": True}


class FixtureRuntime(CodexRuntime):
    def __init__(self, case: Mapping[str, Any]):
        super().__init__(worker_url="http://fixture-private-worker", worker_secret="fixture-secret", model="fixture-model", task_publisher_enabled=False)
        self.fixture_worker = FixtureWorker(case)

        async def handle(request: httpx.Request) -> httpx.Response:
            if request.url.path != "/internal/codex/turn":
                return httpx.Response(404, request=request)
            payload = json.loads(request.content.decode("utf-8"))
            self.fixture_worker.set_round(self.fixture_worker.current_round or 1)
            result = await self.fixture_worker.turn(**payload)
            if "application/x-ndjson" in request.headers.get("accept", ""):
                events = "\n".join(json.dumps(event, ensure_ascii=False) for event in (
                    {"type": "text_delta", "text": result["reply"]},
                    {"type": "provider_complete", "data": result},
                    {"type": "result", "data": result},
                )) + "\n"
                return httpx.Response(200, headers={"content-type": "application/x-ndjson"}, content=events.encode("utf-8"), request=request)
            return httpx.Response(200, headers={"content-type": "application/json"}, content=json.dumps(result, ensure_ascii=False).encode("utf-8"), request=request)

        self.worker_transport = httpx.MockTransport(handle)


def build_composer_request(storage: CaseStorage, case: Mapping[str, Any], round_number: int, action: str) -> tuple[dict[str, Any], dict[str, Any]]:
    rows = storage.composition_memories()
    locale = normalize_conversation_language(case.get("locale"))
    sources = source_snapshot(rows, storage.project_id)
    key = snapshot_key(sources, storage.project_id, locale)
    trigger: dict[str, Any] = {
        "type": action,
        "confirmed": True,
        "free_rounds_completed": round_number,
        "free_round_limit": 20,
        "storytelling_confirmation_ref": "synthetic-review-confirmation" if action == "storytelling_complete" else None,
        "composition_authorized": action == "storytelling_complete",
    }
    if action == "private_draft_checkpoint":
        trigger.update({"private_draft_authorized": True, "private_rounds_completed": round_number, "private_draft_cadence": 5})
    request = {
        "schema_version": "1.0", "request_id": key, "event_id": f"{key[:50]}-{round_number}", "project_id": storage.project_id,
        "trigger": trigger,
        "target": {"locale": locale, "audience": "storyteller", "medium": "web"},
        "snapshot": {"id": key, "policy_epoch": 1, "expected_manuscript_revision": 0, "retrieval_complete": True, "glossary_version": "1", "preferences_version": locale},
        "policy": {"max_chapter_words": 7000, "soft_chapter_words": 6000, "focus_threshold": 0.65, "max_followup_questions": 0, "preview_preference": "auto"},
        "sources": sources, "assets": [], "periods": [], "events": [],
        "prior_state": {"kind": "none", "revision": 0, "chapters": [], "last_snapshot_fingerprint": ""},
        "authorised_retirements": [],
        "context": {"style": "plain, warm, faithful"},
    }
    index_request = incremental_index_request(request, None)
    return request, index_request


async def run_composer_checkpoint(runtime: CodexRuntime, storage: CaseStorage, case: Mapping[str, Any], round_number: int, action: str, *, execution_mode: str, timeout: float = 300) -> dict[str, Any]:
    started = time.monotonic()
    provider_calls_before = len(getattr(getattr(runtime, "fixture_worker", None), "calls", []))
    worker_requests_before = int(getattr(runtime, "observed_worker_requests", 0))
    request, index_request = build_composer_request(storage, case, round_number, action)
    checkpoint: dict[str, Any] = {}

    async def progress(_phase: str) -> None:
        return None

    try:
        result = await asyncio.wait_for(
            compose_candidate(request, runtime, storage, storage.project_id, normalize_conversation_language(case.get("locale")), checkpoint=checkpoint, progress=progress, index_request=index_request),
            timeout=max(1.0, float(timeout)),
        )
        ready = result.get("status") == "ready"
        saved = False
        if ready:
            bundle = {"type": "memoir_evaluation_composition", "snapshot_key": request["snapshot"]["id"], **result}
            saved = bool(storage.save_memory(json.dumps(bundle, ensure_ascii=False), kind="memoir", source_paths=[f"memoir-evaluation:{storage.project_id}", request["snapshot"]["id"]]))
        provider_calls_after = len(getattr(getattr(runtime, "fixture_worker", None), "calls", []))
        return {"status": "mock_only" if execution_mode == "fixture" else "pass", "invoked": True, "output_ok": bool(ready and saved), "ready": ready, "persisted": saved, "action": action, "elapsed_ms": round((time.monotonic() - started) * 1000, 1), "provider_calls": provider_calls_after - provider_calls_before if execution_mode == "fixture" else None, "worker_requests": int(getattr(runtime, "observed_worker_requests", 0)) - worker_requests_before, "usage_reported": False, "cost_reported": False}
    except (Exception,) as error:
        status_code = getattr(getattr(error, "response", None), "status_code", None)
        comment = "Composer checkpoint failed; the trace retains a bounded error class/status and replay command."
        if status_code is not None:
            comment = f"Composer checkpoint failed with HTTP {status_code}; no composition result was treated as a pass."
        return {"status": "unavailable" if execution_mode == "live" else "mock_only", "invoked": True, "output_ok": False, "action": action, "error_type": type(error).__name__, "http_status": status_code, "comment": comment, "elapsed_ms": round((time.monotonic() - started) * 1000, 1), "provider_calls": len(getattr(getattr(runtime, "fixture_worker", None), "calls", [])) - provider_calls_before if execution_mode == "fixture" else None, "worker_requests": int(getattr(runtime, "observed_worker_requests", 0)) - worker_requests_before, "usage_reported": False, "cost_reported": False}


def ui_place_group_observation(storage: CaseStorage, *, prior_place_count: int, execution_mode: str) -> dict[str, Any]:
    # The UI-owned service is driven by the application state produced by the
    # turn, not by the hidden expected-outcome file. This makes a hallucinated
    # or stale marker observable instead of allowing the evaluator to create
    # the exact records it expects.
    accepted_places = storage.place_history()
    if len(accepted_places) <= prior_place_count:
        return {"executed": True, "called": False, "output_ok": True, "status": "mock_only" if execution_mode == "fixture" else "pass", "comment": "No accepted place arrived in this round."}
    try:
        result = resolve_place_groups(accepted_places)
        pins = [record.get("pin") for record in result.get("places", [])]
        independent = all(pin is None or pin.get("place") for pin in pins)
        return {"executed": True, "called": True, "output_ok": bool(len(result.get("places", [])) == len(accepted_places) and independent), "status": "mock_only" if execution_mode == "fixture" else "pass", "group_status": result.get("status"), "place_count": len(result.get("places", [])), "pin_independence": independent, "source_place_count": len(accepted_places), "comment": "Production grouping function exercised from accepted application state; no model call."}
    except Exception as error:
        return {"executed": True, "called": True, "output_ok": False, "status": "fail", "error_type": type(error).__name__}


def photo_request_place(text: str) -> str | None:
    """Extract a public photo place from the current visible request only."""
    labels = FIXTURE_EN_PLACE_LABELS + FIXTURE_ZH_PLACE_LABELS
    found = [(match.start(), label) for label in labels for match in re.finditer(re.escape(label), text, re.IGNORECASE)]
    return next((label for _, label in sorted(found)), None)


def photo_request_period(text: str, action: str) -> str:
    if action == "current_day":
        return ""
    year = re.search(r"(?:18|19|20)\d{2}|[一二〇零一九八七六五四三两]{4,8}", text)
    return year.group(0) if year else "historical"


async def ui_photo_observation(
    expected: Mapping[str, Any],
    text: str,
    case: Mapping[str, Any],
    args: argparse.Namespace,
    *,
    execution_mode: str,
) -> dict[str, Any]:
    action = expected.get("photo_action")
    if action in {"current_day", "historical"}:
        if execution_mode != "live":
            return {"executed": False, "called": False, "output_ok": False, "status": "not_run", "budget": "planned_one_search_per_case", "comment": "No external photo search was sent in fixture mode."}
        place = photo_request_place(text)
        period = photo_request_period(text, str(action))
        if not place:
            return {"executed": True, "called": False, "output_ok": False, "status": "unavailable", "comment": "The visible photo request did not contain a resolvable public place."}
        if not args.photo_worker_url or not args.photo_worker_secret:
            return {"executed": True, "called": False, "output_ok": False, "status": "unavailable", "comment": "The configured private photo worker boundary is unavailable."}
        payload = {"owner": str(case["project_id"]), "place": place, "period": period, "cursor": None}
        headers = {"X-Photo-Worker-Secret": args.photo_worker_secret}
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(args.photo_timeout, connect=min(args.photo_timeout, 5))) as client:
                response = await client.post(args.photo_worker_url.rstrip("/") + "/internal/photos", headers=headers, json=payload)
            response.raise_for_status()
            body = response.json()
            status = str(body.get("status") or "").upper()
            items = body.get("items")
            metadata = []
            if isinstance(items, list):
                for item in items[:50]:
                    if not isinstance(item, Mapping):
                        continue
                    metadata.append({
                        "source_url": item.get("source_url"),
                        "license": item.get("license"),
                        "license_url": item.get("license_url"),
                        "date_expression": item.get("date_expression"),
                        "attribution": item.get("attribution"),
                    })
            source_labeled = sum(bool(item.get("source_url")) for item in metadata)
            rights_labeled = sum("license" in item and item.get("license") is not None for item in metadata)
            date_labeled = sum(bool(item.get("date_expression")) for item in metadata)
            metadata_shape_ok = not metadata or (source_labeled == len(metadata) and rights_labeled == len(metadata))
            shape_ok = isinstance(items, list) and status in {"READY", "PARTIAL", "NO_MATCH", "SEARCHING", "UNAVAILABLE"} and metadata_shape_ok
            if status == "UNAVAILABLE":
                return {"executed": True, "called": True, "output_ok": False, "status": "unavailable", "place": place, "period": period, "result_status": status, "item_count": len(items) if isinstance(items, list) else None, "failures": body.get("failures") or [], "comment": "Photo worker returned an unavailable result; no photo is treated as evidence."}
            return {"executed": True, "called": True, "output_ok": shape_ok, "status": "pass" if shape_ok else "fail", "place": place, "period": period, "result_status": status, "item_count": len(items) if isinstance(items, list) else None, "target_count": body.get("target_count"), "shortfall": body.get("shortfall"), "metadata_items_observed": len(metadata), "source_labeled": source_labeled, "rights_labeled": rights_labeled, "date_labeled": date_labeled, "unknown_rights": sum(1 for item in metadata if not item.get("license") or str(item.get("license")).casefold() in {"unknown", "unresolved"}), "item_metadata": metadata, "comment": "Production photo-worker response was recorded as public reference metadata only; unknown rights remain unknown and are not treated as permission."}
        except Exception as error:
            return {"executed": True, "called": True, "output_ok": False, "status": "unavailable", "place": place, "period": period, "error_type": type(error).__name__, "comment": "Photo worker call failed; no source or rights claim was fabricated."}
    return {"executed": True, "called": False, "output_ok": True, "status": "mock_only" if execution_mode == "fixture" else "pass", "comment": "No public-photo search was made for this round."}


def state_for_grade(storage: CaseStorage) -> dict[str, Any]:
    state = storage.state_snapshot()
    state.pop("memories", None)
    return state


async def run_case(
    case: Mapping[str, Any],
    expected_payload: Mapping[str, Any],
    case_expected: Mapping[str, Any],
    *,
    args: argparse.Namespace,
    run_dir: Path,
    execution_mode: str,
    runtime: CodexRuntime | None = None,
    max_rounds: int = 50,
    langfuse_publisher: LangfusePublisher | None = None,
) -> dict[str, Any]:
    case_dir = run_dir / "cases" / str(case["id"])
    rounds_dir = case_dir / "rounds"
    rounds_dir.mkdir(parents=True, exist_ok=True)
    state_path = case_dir / "storage_state.json"
    state = load_json(state_path) if args.resume and state_path.exists() else None
    # The hidden truth is loaded only by the outer evaluator for post-run
    # assertions; it is never attached to this application storage adapter or
    # to any worker packet.
    storage = CaseStorage(case, state)
    if runtime is None:
        runtime = FixtureRuntime(case) if execution_mode == "fixture" else CodexRuntime(
            worker_url=args.worker_url,
            worker_secret=args.worker_secret,
            model=args.provider_model,
            base_url=args.provider_url,
            timeout=args.timeout,
            provider_env={
                "MEMORY_SPARK_LLM_API_KEY": configured_env("MEMORY_SPARK_LLM_API_KEY", parse_env_file(Path(args.env_file))),
                "MEMORY_SPARK_LLM_BASE_URL": args.provider_url,
                "MEMORY_SPARK_LLM_MODEL": args.provider_model,
            },
            task_publisher_enabled=False,
        )
    round_grades: list[dict[str, Any]] = []
    ui_by_round: dict[int, dict[str, Any]] = {}
    failures: list[dict[str, Any]] = []
    langfuse_submitted = 0
    langfuse_unavailable = 0
    langfuse_disabled = False
    provider_usage = {"reported": False, "input_tokens": None, "output_tokens": None, "total_tokens": None, "cost": None, "provider_calls": None, "private_worker_requests": 0, "note": "The configured provider did not expose token or cost usage; private_worker_requests counts requests sent to the configured private worker boundary only."}
    for round_number in range(1, max_rounds + 1):
        trace_path = rounds_dir / f"round-{round_number:03d}.json"
        retry_prior: Mapping[str, Any] | None = None
        if args.resume and trace_path.exists() and state_path.exists():
            prior = load_json(trace_path)
            if isinstance(prior, Mapping) and prior.get("round") == round_number and prior.get("grade"):
                prior_grade = prior.get("grade") if isinstance(prior.get("grade"), Mapping) else {}
                should_retry = bool(args.retry_unavailable and prior_grade.get("overall") == "unavailable" and prior.get("error"))
                if should_retry:
                    attempts = sorted(rounds_dir.glob(f"round-{round_number:03d}.attempt-*.json"))
                    attempt_number = len(attempts) + 1
                    write_json(rounds_dir / f"round-{round_number:03d}.attempt-{attempt_number:03d}.json", prior)
                    retry_prior = prior
                elif args.regrade:
                    expected = expected_round(expected_payload, case_expected, round_number)
                    regraded = evaluate_round(
                        expected_payload,
                        case_expected,
                        round_number,
                        prior.get("response") if isinstance(prior.get("response"), Mapping) else {},
                        execution_mode=execution_mode,
                        ui_observations=prior.get("ui") if isinstance(prior.get("ui"), Mapping) else {},
                        composer_observation=prior.get("composer") if isinstance(prior.get("composer"), Mapping) else None,
                    )
                    if prior.get("error") is not None:
                        if execution_mode == "live":
                            regraded = mark_round_unavailable(
                                regraded,
                                reason=str((prior.get("error") or {}).get("type") or "prior_error"),
                            )
                        else:
                            regraded["overall"] = "fail"
                        regraded["error"] = prior["error"]
                    updated = dict(prior)
                    history = list(updated.get("grade_history") or [])
                    history.append({"contract": updated.get("expected_outcome"), "grade": updated.get("grade")})
                    updated["grade_history"] = history
                    updated["expected_outcome"] = expected
                    updated["grade"] = regraded
                    write_json(trace_path, updated)
                    # Regrade is intentionally provider-free, but the saved
                    # trace still carries the receipt from the original live
                    # turn.  Preserve that accounting in the case summary
                    # instead of making a regrade look like a zero-request
                    # run.
                    provider_usage["private_worker_requests"] += int(
                        (prior.get("usage") or {}).get("private_worker_requests") or 0
                    )
                    if regraded.get("overall") == "fail":
                        failures.append({
                            "round": round_number,
                            "kind": "expectation_failure",
                            "comments": [
                                item.get("comment")
                                for item in regraded.get("skill_grades", {}).values()
                                if item.get("status") == "fail"
                            ],
                        })
                    elif regraded.get("overall") == "unavailable" and prior.get("error"):
                        error = prior["error"]
                        failures.append({
                            "round": round_number,
                            "kind": error.get("type", "unavailable"),
                            "message": error.get("message", ""),
                        })
                    round_grades.append(regraded)
                elif not should_retry:
                    round_grades.append(dict(prior["grade"]))
                if not should_retry:
                    ui_by_round[round_number] = dict(prior.get("ui") or {})
                    continue
        expected = expected_round(expected_payload, case_expected, round_number)
        storage.set_round_entitlement(bool(expected.get("family_enabled")))
        if hasattr(runtime, "fixture_worker"):
            runtime.fixture_worker.set_round(round_number)
        text = str(case["rounds"][round_number - 1])
        events: list[dict[str, Any]] = []
        deltas: list[str] = []

        async def on_delta(chunk: str) -> None:
            deltas.append(str(chunk))

        async def on_event(event: Mapping[str, Any]) -> None:
            events.append(json_safe(event))

        correlation = normalise_correlation({
            "run_id": args.run_id,
            "case_id": case["id"],
            "application_revision": build_application_revision(ROOT),
            "dataset": "memoir-five-case",
            "dataset_version": "memoir-five-case/1",
            "rubric_version": EVALUATION_RUBRIC_VERSION,
            "judge_rubric_version": JUDGE_RUBRIC_VERSION,
            "evaluator_version": RUNNER_VERSION,
            "model": runtime.model,
            "provider": args.provider_url,
            "round_id": f"{round_number:03d}",
        })
        started = time.monotonic()
        worker_requests_before = int(getattr(runtime, "observed_worker_requests", 0))
        turn_trajectory = TrajectoryRecorder(
            correlation,
            skill_manifest=build_skill_manifest(ROOT / "skills"),
        )
        result: dict[str, Any]
        error: dict[str, Any] | None = None
        prior_place_count = len(storage.place_history())
        try:
            result = await asyncio.wait_for(runtime.turn(
                storage,
                text,
                project_id=str(case["project_id"]),
                language=str(case["locale"]),
                on_delta=on_delta,
                on_event=on_event,
                evaluation=correlation,
                include_trajectory=True,
                evaluation_context={"enabled_skills": list(SKILLS), "available_tools": ["memoir-place-groups", "place-photo-research"]},
                trajectory=turn_trajectory,
            ), timeout=args.timeout + 30)
        except Exception as exc:
            partial_trajectory = getattr(exc, "trajectory", None)
            if not isinstance(partial_trajectory, Mapping):
                turn_trajectory.finish(
                    None,
                    status="failed",
                    stop_reason="runner.failed",
                    error={"error_type": type(exc).__name__},
                )
                partial_trajectory = turn_trajectory.payload()
            result = {
                "reply": None,
                "trace": [],
                "trajectory": partial_trajectory,
            }
            error = {"type": type(exc).__name__, "message": str(exc)[:240]}
        if error is None and result.get("recall_status", {}).get("payment_required"):
            error = {"type": "payment_required", "message": "isolated evaluation entitlement unexpectedly blocked a round"}
        result["state"] = state_for_grade(storage)
        composer_observation = None
        action = expected.get("composer_action")
        if error is None and action:
            composer_observation = await run_composer_checkpoint(runtime, storage, case, round_number, str(action), execution_mode=execution_mode, timeout=args.composer_timeout)
        ui_by_round[round_number] = {
            "memoir-place-groups": ui_place_group_observation(storage, prior_place_count=prior_place_count, execution_mode=execution_mode),
            "place-photo-research": await ui_photo_observation(expected, text, case, args, execution_mode=execution_mode),
        }
        grade = evaluate_round(expected_payload, case_expected, round_number, result, execution_mode=execution_mode,
                               ui_observations=ui_by_round[round_number], composer_observation=composer_observation)
        if error is not None:
            if execution_mode == "live":
                grade = mark_round_unavailable(grade, reason=error["type"])
            else:
                grade["overall"] = "fail"
            grade["error"] = error
            failures.append({"round": round_number, "kind": error["type"], "message": error["message"]})
        if grade.get("overall") == "fail":
            failures.append({"round": round_number, "kind": "expectation_failure", "comments": [item.get("comment") for item in grade.get("skill_grades", {}).values() if item.get("status") == "fail"]})
        langfuse_observation: dict[str, Any] | None = None
        trajectory = result.get("trajectory") if isinstance(result, Mapping) else None
        if langfuse_publisher is not None and not langfuse_disabled and isinstance(trajectory, Mapping):
            round_correlation = {**correlation, "round_id": f"{round_number:03d}"}
            try:
                with langfuse_publisher.case(
                    name=f"memoir-five-case-{case['id']}-round-{round_number:03d}",
                    task={"case_id": case["id"], "round": round_number, "text": text},
                    correlation=round_correlation,
                ) as sink:
                    sink.publish(
                        trajectory,
                        build_langfuse_round_scores(grade),
                        extra_metadata={
                            "round_status": grade.get("overall"),
                            "deterministic_status": langfuse_deterministic_status(grade),
                            "execution_mode": execution_mode,
                        },
                    )
                    langfuse_observation = {
                        # The SDK flush is asynchronous and does not provide a
                        # durable server readback.  Record submission only;
                        # never present this as a verified Langfuse write.
                        "status": "submitted",
                        "durable_readback": "not_verified",
                        "trace_id": sink.trace_id,
                        "observation_id": sink.observation_id,
                        "step_observations": dict(sink.step_observations),
                    }
                langfuse_submitted += 1
            except Exception as publish_error:
                # A failed telemetry publish must not turn a completed Memoir
                # turn into a product failure, but it is recorded once and
                # subsequent rounds avoid an unbounded retry storm.
                langfuse_disabled = True
                langfuse_unavailable += 1
                langfuse_observation = {
                    "status": "unavailable",
                    "error_type": type(publish_error).__name__,
                }
        elif langfuse_publisher is not None:
            langfuse_unavailable += 1
            langfuse_observation = {
                "status": "unavailable" if langfuse_disabled else "not_available",
                "reason": "round did not return a normalized trajectory",
            }
        round_worker_requests = max(0, int(getattr(runtime, "observed_worker_requests", 0)) - worker_requests_before)
        provider_usage["private_worker_requests"] += round_worker_requests
        round_record = {
            "schema_version": "memoir-five-case-round-trace/1",
            "run_id": args.run_id,
            "case_id": case["id"],
            "round": round_number,
            "execution_mode": execution_mode,
            "input": {"locale": case["locale"], "project_id": case["project_id"], "text": text},
            "expected_outcome": expected,
            "events": events,
            "visible_delta_chars": sum(len(item) for item in deltas),
            "elapsed_ms": round((time.monotonic() - started) * 1000, 1),
            "usage": {"reported": False, "private_worker_requests": round_worker_requests, "input_tokens": None, "output_tokens": None, "total_tokens": None, "cost": None},
            "error": error,
            "response": redact_payload(result),
            "composer": composer_observation,
            "langfuse": langfuse_observation,
            "ui": ui_by_round[round_number],
            "grade": grade,
            "replay": f"python scripts/run_memoir_five_case_evaluation.py --mode {execution_mode} --run-id {args.run_id} --cases {case['id']} --resume",
        }
        if retry_prior is not None:
            round_record["retry_of"] = {
                "previous_status": (retry_prior.get("grade") or {}).get("overall") if isinstance(retry_prior.get("grade"), Mapping) else None,
                "previous_error": retry_prior.get("error"),
                "preserved_attempt": f"round-{round_number:03d}.attempt-*.json",
            }
        write_json(trace_path, round_record)
        write_json(state_path, storage.state_snapshot())
        round_grades.append(grade)
    summary = aggregate_case(str(case["id"]), round_grades, execution_mode=execution_mode, expected_round_count=50)
    photo_records = [
        observation for observation in ui_by_round.values()
        for observation in [observation.get("place-photo-research") or {}]
        if observation.get("called")
    ]
    summary["photo_searches"] = {
        "planned": 2,
        "executed": len(photo_records),
        "budget_note": "One bounded production photo-worker call per positive photo scenario; no call on negative rounds.",
        "outcomes": [{key: value for key, value in record.items() if key in {"place", "period", "result_status", "item_count", "target_count", "shortfall", "status", "error_type", "metadata_items_observed", "source_labeled", "rights_labeled", "date_labeled", "unknown_rights"}} for record in photo_records],
    }
    summary["provider_usage"] = provider_usage
    summary["failures"] = failures
    summary["ui_rounds"] = sorted(ui_by_round)
    summary["langfuse"] = {
        "requested": bool(getattr(args, "publish_langfuse", False)),
        "configured": langfuse_publisher is not None,
        "submitted_rounds": langfuse_submitted,
        "durable_readback": "not_verified" if langfuse_submitted else "not_available",
        "unavailable_rounds": langfuse_unavailable,
        "disabled_after_error": langfuse_disabled,
    }
    write_json(case_dir / "summary.json", summary)
    return summary


async def provider_probe(url: str, api_key: str, timeout: float) -> dict[str, Any]:
    started = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.get(url.rstrip("/") + "/models", headers={"Authorization": f"Bearer {api_key}"} if api_key else {})
        if response.status_code < 300:
            status = "reachable"
        elif response.status_code in {401, 403}:
            status = "auth_error"
        else:
            status = "http_error"
        return {"status": status, "http_status": response.status_code, "elapsed_ms": round((time.monotonic() - started) * 1000, 1)}
    except Exception as error:
        return {"status": "unreachable", "error_type": type(error).__name__, "error": str(error)[:240], "elapsed_ms": round((time.monotonic() - started) * 1000, 1)}


async def worker_probe(url: str, timeout: float) -> dict[str, Any]:
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.get(url.rstrip("/") + "/health")
        return {"status": "reachable" if response.status_code == 200 else "error", "http_status": response.status_code}
    except Exception as error:
        return {"status": "unreachable", "error_type": type(error).__name__, "error": str(error)[:240]}


async def photo_worker_probe(url: str, secret: str, timeout: float) -> dict[str, Any]:
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.get(url.rstrip("/") + "/health")
        return {"status": "reachable" if response.status_code == 200 else "error", "http_status": response.status_code}
    except Exception as error:
        return {"status": "unreachable", "error_type": type(error).__name__, "error": str(error)[:240]}


async def preflight(
    args: argparse.Namespace,
    env_file: Mapping[str, str],
    *,
    run_dir: Path,
    inputs: Mapping[str, Any],
    expected: Mapping[str, Any],
    langfuse_receipt: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    provider = provider_config(env_file, args.provider_url, args.provider_model)
    probe = await provider_probe(provider["base_url"], configured_env("MEMORY_SPARK_LLM_API_KEY", env_file), min(args.timeout, 10))
    worker = await worker_probe(args.worker_url, min(args.timeout, 10)) if args.worker_url else {"status": "not_configured"}
    photo_worker = await photo_worker_probe(args.photo_worker_url, args.photo_worker_secret, min(args.photo_timeout, 10)) if args.photo_worker_url else {"status": "not_configured"}
    codex = shutil.which(configured_env("MEMORY_SPARK_CODEX_BIN", env_file) or "codex")
    photo = {
        "planned_external_searches": 10,
        "per_case": 2,
        "configured_serpapi": bool(configured_env("SERPAPI_KEY", env_file) or configured_env("SERPAPI_API_KEY", env_file)),
        "configured_google_cse": bool(configured_env("GOOGLE_CSE_ID", env_file) or configured_env("GOOGLE_CSE_URL", env_file)),
        "executed": 0,
        "budget_status": "not_spent",
    }
    calibration = {"status": "unavailable", "reason": "not_checked"}
    try:
        load_judge_calibration(load_json(CALIBRATION_PATH))
        calibration = {"status": "approved"}
    except Exception as error:
        calibration = {"status": "unavailable", "reason": type(error).__name__}
    blockers: list[dict[str, str]] = []
    if not provider["api_key_configured"]:
        blockers.append({"target": "MEMORY_SPARK_LLM_API_KEY", "reason": "provider consumer credential is not configured"})
    if probe.get("status") != "reachable":
        blockers.append({"target": provider["base_url"], "reason": probe.get("error") or f"provider probe status {probe.get('status')} (HTTP {probe.get('http_status')})"})
    if not args.worker_url:
        blockers.append({"target": "MEMORY_SPARK_CODEX_WORKER_URL", "reason": f"private worker URL is not configured; Compose injects {COMPOSE_WORKER_URL} inside the app network"})
    elif worker.get("status") != "reachable":
        blockers.append({"target": args.worker_url, "reason": worker.get("error") or f"worker probe status {worker.get('status')} (HTTP {worker.get('http_status')})"})
    if not args.worker_secret:
        blockers.append({"target": "MEMORY_SPARK_CODEX_WORKER_SECRET", "reason": "private worker authentication secret is not configured"})
    if not args.photo_worker_url:
        blockers.append({"target": "MEMORY_SPARK_PHOTO_WORKER_URL", "reason": f"private photo worker URL is not configured; Compose injects {COMPOSE_PHOTO_WORKER_URL} inside the app network"})
    elif photo_worker.get("status") != "reachable":
        blockers.append({"target": args.photo_worker_url, "reason": photo_worker.get("error") or f"photo worker probe status {photo_worker.get('status')} (HTTP {photo_worker.get('http_status')})"})
    if not args.photo_worker_secret:
        blockers.append({"target": "MEMORY_SPARK_PHOTO_WORKER_SECRET", "reason": "private photo worker authentication secret is not configured"})
    langfuse = dict(langfuse_receipt or {"status": "not_requested"})
    if args.publish_langfuse and langfuse.get("status") != "configured":
        blockers.append({
            "target": "MEMORY_SPARK_LANGFUSE_*",
            "reason": str(langfuse.get("error") or "Langfuse publisher could not be configured")[:240],
        })
    receipt = {
        "schema_version": "memoir-five-case-preflight/1",
        "run_id": args.run_id,
        "timestamp": utc_now(),
        "application_revision": build_application_revision(ROOT),
        "provider": provider,
        "provider_probe": probe,
        "worker_probe": worker,
        "photo_worker_probe": photo_worker,
        "live_path": {
            "runner_calls": "CodexRuntime.turn",
            "production_boundary": "CodexRuntime -> private codex-worker /internal/codex/turn -> Codex CLI -> llm_provider gateway",
            "compose_worker_url": COMPOSE_WORKER_URL,
            "worker_url_used_by_runner": args.worker_url,
            "requires_worker": True,
            "photo_worker_url_used_by_runner": args.photo_worker_url,
            "requires_photo_worker_for_positive_photo_rounds": True,
        },
        "codex_binary": codex,
        "photo": photo,
        "judge": {"status": "unavailable", "reason": "No separate judge endpoint configured"},
        "langfuse": langfuse,
        "calibration": calibration,
        "dataset": {"inputs_sha256": sha256_file(INPUTS_PATH), "expected_sha256": sha256_file(EXPECTED_PATH), "truth_sha256": sha256_file(TRUTH_PATH)},
        "safety": {"isolated_project_ids": [case["project_id"] for case in inputs["cases"]], "real_customer_data": False, "production_migration": False, "shared_service_restart": False},
        "blockers": blockers,
    }
    write_json(run_dir / "preflight.json", receipt)
    return receipt


def make_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=sorted(EXECUTION_MODES), default="fixture")
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--output-root", default=str(ROOT / "var/memoir-five-case-evaluation"))
    parser.add_argument("--cases", nargs="*", default=None, help="Case IDs; default is all five")
    parser.add_argument("--inputs", default=str(INPUTS_PATH))
    parser.add_argument("--expected", default=str(EXPECTED_PATH))
    parser.add_argument("--truth", default=str(TRUTH_PATH))
    parser.add_argument("--env-file", default=str(ROOT / ".env"))
    parser.add_argument("--provider-url", default=None)
    parser.add_argument("--provider-model", default=None)
    parser.add_argument("--worker-url", default=None)
    parser.add_argument("--worker-secret", default=None)
    parser.add_argument("--photo-worker-url", default=None)
    parser.add_argument("--photo-worker-secret", default=None)
    parser.add_argument("--photo-timeout", type=float, default=45)
    parser.add_argument("--case-concurrency", type=int, default=1, help="Bounded number of synthetic cases to run concurrently; default 1.")
    parser.add_argument("--max-rounds", type=int, default=None, help="Bounded pilot limit; omit for the required 50 rounds per case.")
    parser.add_argument("--timeout", type=float, default=120)
    parser.add_argument("--composer-timeout", type=float, default=300, help="Bound each synthetic composition checkpoint; no provider substitution is attempted after the deadline.")
    parser.add_argument("--evaluation-reasoning-effort", choices=("minimal", "low", "medium", "high", "max"), default=None, help="Record the reasoning effort configured in the isolated worker; this runner does not mutate the worker environment.")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--retry-unavailable", action="store_true", help="On resume, rerun saved live rounds whose prior attempt was unavailable; preserve the prior trace as an attempt file.")
    parser.add_argument("--regrade", action="store_true", help="Re-evaluate saved round traces with the current deterministic contract; never calls the provider.")
    parser.add_argument("--preflight-only", action="store_true")
    parser.add_argument("--skip-preflight", action="store_true")
    parser.add_argument(
        "--publish-langfuse", "--publish",
        dest="publish_langfuse",
        action="store_true",
        help="Publish minimized per-round trajectories and deterministic grades to configured Langfuse.",
    )
    return parser


async def main_async(args: argparse.Namespace) -> int:
    inputs = load_json(args.inputs)
    expected_payload = load_json(args.expected)
    truth_payload = load_json(args.truth)
    errors = validate_dataset(inputs, expected_payload)
    if errors:
        print(json.dumps({"status": "invalid_dataset", "errors": errors}, ensure_ascii=False, indent=2))
        return 2
    env_file = parse_env_file(Path(args.env_file))
    if args.provider_url is None:
        args.provider_url = provider_config(env_file)["base_url"]
    if args.provider_model is None:
        args.provider_model = provider_config(env_file)["model"]
    if args.worker_url is None:
        args.worker_url = configured_env("MEMORY_SPARK_CODEX_WORKER_URL", env_file) or None
    if args.worker_secret is None:
        args.worker_secret = configured_env("MEMORY_SPARK_CODEX_WORKER_SECRET", env_file)
    if args.photo_worker_url is None:
        args.photo_worker_url = configured_env("MEMORY_SPARK_PHOTO_WORKER_URL", env_file) or None
    if args.photo_worker_secret is None:
        args.photo_worker_secret = configured_env("MEMORY_SPARK_PHOTO_WORKER_SECRET", env_file)
    if args.run_id is None:
        args.run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:8]
    langfuse_publisher = None
    langfuse_receipt: dict[str, Any] = {"status": "not_requested"}
    if args.publish_langfuse:
        try:
            langfuse_publisher = LangfusePublisher(env=env_file)
            langfuse_receipt = {
                "status": "configured",
                "sdk": "langfuse-python-v4",
                "auth_check": getattr(langfuse_publisher, "auth_check_status", "not_supported"),
                "durable_readback": "not_verified",
            }
        except Exception as error:
            langfuse_receipt = {
                "status": "unavailable",
                "error_type": type(error).__name__,
                "error": str(error)[:240],
            }
    run_dir = Path(args.output_root) / args.run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = run_dir / "manifest.json"
    prior_manifest = load_json(manifest_path) if args.resume and manifest_path.exists() else None
    manifest = {
        "schema_version": "memoir-five-case-run/1", "runner_version": RUNNER_VERSION, "run_id": args.run_id,
        "mode": args.mode, "started_at": utc_now(), "application_revision": build_application_revision(ROOT),
        "case_concurrency": args.case_concurrency,
        "execution_budget": {
            "runner_turn_timeout_seconds": args.timeout,
            "composer_timeout_seconds": args.composer_timeout,
            "photo_timeout_seconds": args.photo_timeout,
            "retry_unavailable": bool(args.retry_unavailable),
            "evaluation_reasoning_effort": args.evaluation_reasoning_effort or provider_config(env_file, args.provider_url, args.provider_model).get("reasoning_effort"),
        },
        "skill_manifest": build_skill_manifest(ROOT / "skills"),
        "dataset": {
            "inputs": str(Path(args.inputs).relative_to(ROOT) if Path(args.inputs).is_relative_to(ROOT) else args.inputs),
            "inputs_sha256": sha256_file(Path(args.inputs)),
            "expected_sha256": sha256_file(Path(args.expected)),
            "truth_sha256": sha256_file(Path(args.truth)),
        },
        "provider": provider_config(env_file, args.provider_url, args.provider_model),
        "langfuse": langfuse_receipt,
        "private_services": {
            "codex_worker_url": args.worker_url,
            "codex_worker_secret_configured": bool(args.worker_secret),
            "photo_worker_url": args.photo_worker_url,
            "photo_worker_secret_configured": bool(args.photo_worker_secret),
        },
        "runtime_versions": {"python": sys.version.split()[0], "node": command_version("node"), "codex": command_version(configured_env("MEMORY_SPARK_CODEX_BIN", env_file) or "codex")},
        "judge_prompt": {"path": str(JUDGE_PROMPT_PATH.relative_to(ROOT)), "sha256": sha256_file(JUDGE_PROMPT_PATH)},
        "judge": {"status": "unavailable", "reason": "No judge endpoint configured"},
        "oracle_boundary": {
            "model_visible_inputs": "tests/evaluation/memoir_five_case_inputs.json round text plus persisted isolated application state",
            "hidden_truth_consumers": ["post-run evaluator/judge inputs only"],
            "fixture_worker_receives_expected_or_truth": False,
            "fixture_worker_receives": ["current storyteller text", "current persisted memories", "current persisted family context", "entitlement state"],
        },
        "photo_budget": {"planned_external_searches": 10, "executed": 0},
        "provider_usage": {"reported": False, "input_tokens": None, "output_tokens": None, "total_tokens": None, "cost": None, "private_worker_requests": 0, "note": "Token and cost usage are unavailable from the configured provider; request counts are recorded separately."},
    }
    if isinstance(prior_manifest, Mapping):
        manifest["original_started_at"] = prior_manifest.get("original_started_at") or prior_manifest.get("started_at")
        history = list(prior_manifest.get("resume_history") or [])
        history.append({"resumed_at": manifest["started_at"], "runner_version": RUNNER_VERSION, "application_revision": manifest["application_revision"], "composer_timeout": args.composer_timeout, "case_concurrency": args.case_concurrency})
        manifest["resume_history"] = history
    write_json(manifest_path, manifest)
    if args.skip_preflight:
        existing_receipt = run_dir / "preflight.json"
        if existing_receipt.exists():
            receipt = load_json(existing_receipt)
            receipt = {**receipt, "skipped": True, "skip_reason": "--skip-preflight"}
        else:
            receipt = {
                "schema_version": "memoir-five-case-preflight/1",
                "run_id": args.run_id,
                "timestamp": utc_now(),
                "application_revision": build_application_revision(ROOT),
                "provider_probe": {"status": "skipped"},
                "worker_probe": {"status": "skipped"},
                "photo_worker_probe": {"status": "skipped"},
                "calibration": {"status": "skipped"},
                "langfuse": langfuse_receipt,
                "blockers": [],
                "skipped": True,
                "skip_reason": "--skip-preflight",
            }
        write_json(run_dir / "preflight.json", receipt)
    else:
        receipt = await preflight(
            args,
            env_file,
            run_dir=run_dir,
            inputs=inputs,
            expected=expected_payload,
            langfuse_receipt=langfuse_receipt,
        )
    if args.preflight_only:
        print(json.dumps(receipt, ensure_ascii=False, indent=2))
        return 0 if not receipt["blockers"] else 3
    if args.mode == "live" and receipt["blockers"]:
        blocked = {"status": "blocked", "mode": "live", "run_id": args.run_id, "blockers": receipt["blockers"], "message": "Live five-case execution was not started because the configured provider/private-worker path did not pass fail-closed preflight. No provider substitution was made."}
        write_json(run_dir / "summary.json", blocked)
        (run_dir / "report.md").write_text("# Memoir five-case evaluation\n\nStatus: **blocked**\n\n" + blocked["message"] + "\n", encoding="utf-8")
        print(json.dumps(blocked, ensure_ascii=False, indent=2))
        return 3
    truth_by_id = {str(item["id"]): item for item in truth_payload.get("cases", []) if isinstance(item, Mapping)}
    expected_by_id = case_expectations(expected_payload)
    wanted = set(args.cases or [str(case["id"]) for case in inputs["cases"]])
    selected = [case for case in inputs["cases"] if str(case["id"]) in wanted]
    if args.mode == "pilot":
        selected = selected[:1]
        max_rounds = args.max_rounds or 5
    else:
        max_rounds = args.max_rounds or 50
    if not selected:
        print(json.dumps({"status": "invalid_selection", "cases": sorted(wanted)}, ensure_ascii=False, indent=2))
        return 2
    if args.case_concurrency < 1 or args.case_concurrency > 3:
        print(json.dumps({"status": "invalid_case_concurrency", "value": args.case_concurrency, "allowed": [1, 3]}, ensure_ascii=False, indent=2))
        return 2
    execution_mode = "fixture" if args.mode in {"fixture", "pilot"} else "live"
    semaphore = asyncio.Semaphore(args.case_concurrency)

    async def execute_case(case: Mapping[str, Any]) -> dict[str, Any]:
        case_id = str(case["id"])
        if case_id not in truth_by_id or case_id not in expected_by_id:
            raise ValueError(f"missing truth/expected record for {case_id}")
        async with semaphore:
            return await run_case(
                case,
                expected_payload,
                expected_by_id[case_id],
                args=args,
                run_dir=run_dir,
                execution_mode=execution_mode,
                max_rounds=max_rounds,
                langfuse_publisher=langfuse_publisher,
            )

    try:
        summaries = list(await asyncio.gather(*(execute_case(case) for case in selected)))
    except ValueError as error:
        print(str(error), file=sys.stderr)
        return 2
    if langfuse_publisher is not None:
        langfuse_publisher.flush()
    write_json(run_dir / "summary.json", {"status": "completed", "mode": args.mode, "cases": summaries})
    aggregate = {
        "status": "mock_only" if args.mode == "fixture" else "completed",
        "mode": args.mode,
        "run_id": args.run_id,
        "cases": summaries,
        "exact_case_count": len(summaries) == 5 if args.mode != "pilot" else False,
        "exact_rounds_per_case": all(item.get("exact_50_rounds") for item in summaries) if args.mode != "pilot" else False,
        "known_blockers": [item for item in summaries if item.get("unavailable_rounds")],
        "judge": {"status": "unavailable", "reason": "No separate judge endpoint configured"},
        "langfuse": {
            "requested": bool(args.publish_langfuse),
            "status": langfuse_receipt.get("status"),
            "durable_readback": langfuse_receipt.get("durable_readback", "not_verified"),
        },
        "photo_searches": {
            "planned": 10,
            "executed": sum(int(item.get("photo_searches", {}).get("executed") or 0) for item in summaries),
            "budget_status": "spent_bounded" if any(int(item.get("photo_searches", {}).get("executed") or 0) for item in summaries) else "not_spent",
            "case_outcomes": {item["case_id"]: item.get("photo_searches", {}) for item in summaries},
        },
        "provider_usage": {
            "reported": any(item.get("provider_usage", {}).get("reported") for item in summaries),
            "provider_calls": None,
            "private_worker_requests": sum(int(item.get("provider_usage", {}).get("private_worker_requests") or 0) for item in summaries),
            "input_tokens": None,
            "output_tokens": None,
            "total_tokens": None,
            "cost": None,
            "note": "The configured provider did not expose token or cost usage; private_worker_requests counts requests sent to the configured private worker boundary only.",
        },
        "replay": f"python scripts/run_memoir_five_case_evaluation.py --mode {args.mode} --run-id {args.run_id} --resume",
    }
    write_json(run_dir / "summary.json", aggregate)
    # Keep the durable manifest aligned with the completed aggregate.  This
    # also makes provider-free regrades retain the original request receipt.
    manifest["status"] = aggregate["status"]
    manifest["completed_at"] = utc_now()
    manifest["provider_usage"] = aggregate["provider_usage"]
    manifest["photo_budget"] = {
        **dict(manifest.get("photo_budget") or {}),
        "executed": aggregate["photo_searches"]["executed"],
        "budget_status": aggregate["photo_searches"]["budget_status"],
    }
    write_json(manifest_path, manifest)
    report_lines = ["# Memoir five-case evaluation", "", f"Status: **{aggregate['status']}**", f"Mode: `{args.mode}`", f"Run: `{args.run_id}`", "", "| Case | Rounds | Stage coverage | Round statuses |", "|---|---:|---|---|"]
    for item in summaries:
        report_lines.append(f"| {item['case_id']} | {item['rounds_observed']} | {'yes' if item['all_life_stages_observed'] else 'no'} | {json.dumps(item['round_status_counts'], ensure_ascii=False, sort_keys=True)} |")
    report_lines += ["", "Live-provider status is recorded in `preflight.json`; fixture/model status is not live evidence unless `mode` is `live`.", f"External photo-search calls executed: {aggregate['photo_searches']['executed']} of 10 planned.", "Judge status: unavailable (no configured judge endpoint).", f"Langfuse submission status: {langfuse_receipt.get('status')}; durable readback: {langfuse_receipt.get('durable_readback', 'not_verified')}.", ""]
    (run_dir / "report.md").write_text("\n".join(report_lines), encoding="utf-8")
    print(json.dumps(aggregate, ensure_ascii=False, indent=2))
    return 0


def main() -> int:
    try:
        return asyncio.run(main_async(make_arg_parser().parse_args()))
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
