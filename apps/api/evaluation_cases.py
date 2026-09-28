"""Checked-in synthetic cases for the Memoir trajectory evaluator.

The cases exercise ``CodexRuntime.turn`` and its private-worker seam with an
isolated in-process worker/storage fixture. They are deterministic and safe to
run in ordinary CI; setting a real worker URL is a separate live-provider run.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import os
from typing import Any, Mapping
from uuid import uuid4

import httpx

from .codex_runtime import CodexRuntime
from .memoir_tasks import execute_task
from .trajectory_evaluation import TrajectoryRecorder, build_skill_manifest, normalise_correlation


DATASET_NAME = "memoir-synthetic"
DATASET_VERSION = "memoir-synthetic/2"
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
    normalized.setdefault("enabled_skills", ["memoir-memory-context"])
    expected = normalized.get("expected") if isinstance(normalized.get("expected"), Mapping) else {}
    normalized.setdefault(
        "available_tools",
        [{"name": str(tool)} for tool in expected.get("allowed_tools", []) if tool],
    )
    return normalized


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
        super().__init__(
            worker_url="http://synthetic-private-worker",
            worker_secret="synthetic-secret",
            model="synthetic-model",
            task_publisher_enabled=True,
        )
        self.worker = SyntheticWorker(case)

        async def handle(request: httpx.Request) -> httpx.Response:
            if request.url.path != "/internal/codex/turn":
                return httpx.Response(404, request=request)
            payload = json.loads(request.content.decode("utf-8"))
            result = await self.worker.turn(**payload)
            encoded = json.dumps(result, ensure_ascii=False)
            if "application/x-ndjson" in request.headers.get("accept", ""):
                events = "\n".join(json.dumps(event, ensure_ascii=False) for event in (
                    {"type": "text_delta", "text": result["reply"]},
                    {"type": "provider_complete", "data": result},
                    {"type": "result", "data": result},
                )) + "\n"
                return httpx.Response(
                    200,
                    headers={"content-type": "application/x-ndjson"},
                    content=events.encode("utf-8"),
                    request=request,
                )
            return httpx.Response(200, headers={"content-type": "application/json"}, content=encoded.encode("utf-8"), request=request)

        self.worker_transport = httpx.MockTransport(handle)

    async def publish_task(self, user_id: str, project_id: str, task: Any) -> dict[str, Any]:
        """Execute the deterministic task locally inside the isolated fixture."""
        encoded = json.dumps(task.model_dump(), ensure_ascii=False, sort_keys=True)
        task_id = "synthetic-task-" + hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:16]
        return {
            "id": task_id,
            "project_id": project_id,
            "kind": task.kind,
            "status": "SUCCEEDED",
            "attempts": 1,
            "result": execute_task(task),
            "error": None,
        }


async def run_case(case: Mapping[str, Any], correlation: Mapping[str, str]) -> dict[str, Any]:
    """Execute one case through the normal runtime/private-worker seam."""
    case = normalise_case(case)
    storage = SyntheticStorage(case, correlation)
    runtime = SyntheticRuntime(case)

    async def discard_delta(_chunk: str) -> None:
        return None

    input_data = case["input"]
    result = await runtime.turn(
        storage,
        str(input_data.get("text") or ""),
        project_id=storage.project_id,
        language=input_data.get("language"),
        on_delta=discard_delta,
        evaluation=correlation,
        include_trajectory=True,
        evaluation_context={
            "enabled_skills": case["enabled_skills"],
            "available_tools": case["available_tools"],
        },
    )
    return result
