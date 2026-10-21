"""Fixed trajectory fixtures for the deterministic scorer.

No application or model is executed. Canonical database workflow tests cover
application boundaries; explicit live commands measure language behavior.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import json
import os
from typing import Any, Mapping
from uuid import uuid4


from .trajectory_evaluation import TrajectoryRecorder, build_skill_manifest, normalise_correlation


DATASET_NAME = "memoir-synthetic"
DATASET_VERSION = "memoir-synthetic/3"
RUBRIC_VERSION = "memoir-trajectory-rubric/2"


def normalise_case(case: Mapping[str, Any]) -> dict[str, Any]:
    """Fill the reproducibility fields that every checked-in case must carry."""
    normalized = deepcopy(dict(case))
    input_value = normalized.get("input")
    input_data = deepcopy(dict(input_value)) if isinstance(input_value, Mapping) else {
        "text": str(normalized.get("text") or ""),
    }
    input_data.setdefault("language", normalized.get("language") or "en-AU")
    normalized["input"] = input_data
    normalized.setdefault("profile", {})
    normalized.setdefault("memories", [])
    normalized.setdefault("entitlement", None)
    normalized.setdefault("enabled_skills", [])
    expected = normalized.get("expected") if isinstance(normalized.get("expected"), Mapping) else {}
    normalized.setdefault(
        "available_tools",
        [{"name": str(tool)} for tool in expected.get("allowed_tools", []) if tool],
    )
    return normalized


class SyntheticStorage:
    """A per-case private storage boundary with no shared user/project data."""

    def __init__(self, case: Mapping[str, Any], correlation: Mapping[str, str]) -> None:
        self.user_id = str(uuid4())
        self.project_id = str(case.get("project_id") or f"synthetic-project-{correlation.get('case_id', uuid4().hex)}")
        self._profile = deepcopy(case.get("profile") or {})
        self._memories = deepcopy(case.get("memories") or [])
        self._place = deepcopy(case.get("place_journey"))
        self._entitlement = deepcopy(case.get("entitlement"))
        if isinstance(self._entitlement, dict) and self._entitlement.get("plan_key") == "family_memoir_v1":
            configured_price = os.getenv("STRIPE_PRICE_FAMILY", "").strip()
            self._entitlement["stripe_price_id"] = configured_price or self._entitlement.get("stripe_price_id") or "synthetic-family-price"
        self._family = deepcopy(case.get("family_context"))
        self._session: dict[str, Any] | None = None
        self._lease_token: str | None = None
        self._revision = 0

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

    def agent_session(self):
        return deepcopy(self._session)

    def memories(self):
        return deepcopy(self._memories)

    def profile(self):
        return deepcopy(self._profile)

    def save_profile(self, profile, **kwargs):
        self._profile = deepcopy(profile)
        return [deepcopy(self._profile)]

    def place_journey(self):
        return deepcopy(self._place)

    def story_entitlement(self):
        return deepcopy(self._entitlement)

    def family_context(self, project_id):
        return deepcopy(self._family)

    def save_place_journey(self, lease_token, candidate, *, source_sequence=None):
        if lease_token != self._lease_token:
            raise RuntimeError("synthetic place write is outside the lease")
        self._revision += 1
        saved = {
            **deepcopy(candidate),
            "status": "active",
            "revision": self._revision,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        if source_sequence is not None:
            saved["source_sequence"] = source_sequence
        self._place = saved
        return deepcopy(saved)

    def upsert_family_context(self, project_id, document, expected_revision=0):
        current_revision = int((self._family or {}).get("revision") or 0)
        if current_revision != int(expected_revision):
            raise RuntimeError("synthetic family revision conflict")
        saved = deepcopy(document)
        saved["revision"] = current_revision + 1
        saved["updated_at"] = datetime.now(timezone.utc).isoformat()
        self._family = saved
        return {"document": deepcopy(saved), "revision": saved["revision"], "changed": True}

    def commit_agent_turn(self, lease_token, thread_id, text, source_paths, *, source_sequence=None):
        if lease_token != self._lease_token:
            raise RuntimeError("synthetic conversation write is outside the lease")
        self._session = {"codex_thread_id": thread_id, "status": "active"}
        record = {
            "id": f"memory-{uuid4().hex[:10]}",
            "kind": "agent",
            "content": text,
            "source_paths": list(source_paths or []),
        }
        if source_sequence is not None:
            record["source_sequence"] = source_sequence
        self._memories.insert(0, record)
        return [record]


class SyntheticWorker:
    """Deterministic private-worker response used by the checked-in dataset."""

    def __init__(self, case: Mapping[str, Any]) -> None:
        self.case = case

    async def turn(self, **kwargs: Any) -> dict[str, Any]:
        correlation = normalise_correlation(kwargs.get("evaluation"))
        recorder = TrajectoryRecorder(
            correlation,
            skill_manifest=build_skill_manifest(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "skills"))),
        )
        recorder.set_context(
            agent_role=kwargs.get("agent_role", "collector"),
            language=kwargs.get("language"),
            model=kwargs.get("model", "synthetic-model"),
            enabled_skills=self.case.get("enabled_skills", []),
            available_tools=self.case.get("available_tools", []),
        )
        recorder.record("application", "worker.turn.received", input={
            "project_id": kwargs.get("project_id"),
            "text": kwargs.get("text"),
        })
        synthetic = self.case.get("synthetic") if isinstance(self.case.get("synthetic"), Mapping) else {}
        for item in synthetic.get("steps", []):
            if not isinstance(item, Mapping):
                continue
            recorder.record(
                str(item.get("phase") or "codex"),
                str(item.get("action") or "tool.call"),
                input={
                    "name": item.get("tool"),
                    "arguments": item.get("arguments") or {},
                },
                output=item.get("output") or {"status": "ok"},
                error=item.get("error"),
            )
        reply = str(synthetic.get("reply") or "I can keep this memory grounded and uncertain where needed.")
        recorder.record("application", "worker.turn.completed", output={"thread_id": "synthetic-thread", "reply": reply})
        recorder.finish(reply, status="completed", stop_reason="turn.completed",
                        state=synthetic.get('final_state', {}))
        return {
            "thread_id": "synthetic-thread",
            "reply": reply,
            "artifacts": [],
            "trajectory": recorder.payload(),
            "_workspace_capable": True,
        }


async def run_case(case: Mapping[str, Any], correlation: Mapping[str, str]) -> dict[str, Any]:
    """Replay a fixed scorer fixture. This does not execute the application."""
    case = normalise_case(case)
    result = await SyntheticWorker(case).turn(
        text=case['input']['text'], language=case['input']['language'], evaluation=correlation)
    result['evaluation_scope'] = 'scorer_fixture'
    return result
