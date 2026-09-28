"""Checked-in synthetic cases for the Memoir trajectory evaluator.

The cases exercise ``CodexRuntime.turn`` and its private-worker seam with an
isolated in-process worker/storage fixture. They are deterministic and safe to
run in ordinary CI; setting a real worker URL is a separate live-provider run.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import os
from typing import Any, Mapping
from uuid import uuid4

from .codex_runtime import CodexRuntime
from .trajectory_evaluation import TrajectoryRecorder, build_skill_manifest, normalise_correlation


DATASET_NAME = "memoir-synthetic"
DATASET_VERSION = "memoir-synthetic/1"
RUBRIC_VERSION = "memoir-trajectory-rubric/2"


class SyntheticStorage:
    """A per-case private storage boundary with no shared user/project data."""

    def __init__(self, case: Mapping[str, Any], correlation: Mapping[str, str]) -> None:
        self.user_id = f"synthetic-user-{correlation.get('case_id', uuid4().hex)}-{uuid4().hex[:8]}"
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
        recorder.finish(reply, status="completed", stop_reason="turn.completed")
        return {
            "thread_id": "synthetic-thread",
            "reply": reply,
            "artifacts": [],
            "trajectory": recorder.payload(),
            "_workspace_capable": True,
        }


class SyntheticRuntime(CodexRuntime):
    def __init__(self, case: Mapping[str, Any]) -> None:
        super().__init__(worker_url="http://synthetic-private-worker", worker_secret="synthetic-secret", model="synthetic-model")
        self.worker = SyntheticWorker(case)

    async def _worker_turn(self, **kwargs: Any) -> dict[str, Any]:
        return await self.worker.turn(**kwargs)


async def run_case(case: Mapping[str, Any], correlation: Mapping[str, str]) -> dict[str, Any]:
    """Execute one case through the normal runtime/private-worker seam."""
    storage = SyntheticStorage(case, correlation)
    runtime = SyntheticRuntime(case)

    async def discard_delta(_chunk: str) -> None:
        return None

    result = await runtime.turn(
        storage,
        str(case.get("input", {}).get("text") if isinstance(case.get("input"), Mapping) else case.get("text") or ""),
        project_id=storage.project_id,
        language=(case.get("input") or {}).get("language") if isinstance(case.get("input"), Mapping) else None,
        on_delta=discard_delta,
        evaluation=correlation,
        include_trajectory=True,
    )
    return result
