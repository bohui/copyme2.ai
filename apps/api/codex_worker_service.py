"""Private Codex worker for isolated, per-user app-server execution."""
from __future__ import annotations

import base64
import asyncio
import fcntl
import hashlib
import hmac
import json
import os
import threading
import httpx
from pathlib import Path
from typing import Any, Literal
from uuid import UUID

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import StreamingResponse
from .turn_stream import STREAM_HEADERS, turn_events
from pydantic import BaseModel, Field

from .codex_agent import CodexConnection, provider_config
from .codex_artifacts import iter_artifacts
from .codex_runtime import (
    LANGUAGE_INTAKE_SCHEMA,
    build_conversation_system_prompt,
    build_language_intake_prompt,
    build_system_prompt,
    build_workspace_extraction_prompt,
    normalize_conversation_language,
)
from .codex_worker_files import migrate_home, write_config
from .trajectory_evaluation import TrajectoryRecorder, build_skill_manifest, normalise_correlation
from .agent_lock import AgentTurnBusyError
from .agent_tasks import organiser_prompt
from .memoir_tasks import MemorySource, PublishTaskInput


class WorkerTurnInput(BaseModel):
    user_id: UUID
    thread_id: str | None = Field(default=None, min_length=1, max_length=256)
    memories: list[str] = Field(default_factory=list, max_length=20)
    profile: dict[str, Any] = Field(default_factory=dict)
    place_journey: dict[str, Any] = Field(default_factory=dict)
    family_enabled: bool = False
    family_context: dict[str, Any] = Field(default_factory=dict)
    project_id: str | None = Field(default=None, min_length=1, max_length=128)
    text: str = Field(min_length=1, max_length=100000)
    model: str | None = Field(default=None, min_length=1, max_length=256)
    language: str | None = Field(default=None, pattern="^(en-AU|zh-CN)$")
    agent_role: Literal['collector', 'organiser', 'memory_context', 'workspace'] = 'collector'
    task_sources: list[MemorySource] = Field(default_factory=list, max_length=1000)
    # Present only for local/CI evaluation. Normal product turns do not carry
    # evaluation IDs and therefore do not return trajectory evidence.
    evaluation: dict[str, str] = Field(default_factory=dict, max_length=12)


class CodexWorker:
    """Run Codex outside the API container and under a user-specific UID."""

    def __init__(self, *, home_root=None, legacy_root=None, command=None, base_url=None, model=None, timeout=120):
        self.home_root = Path(home_root or os.getenv(
            "MEMORY_SPARK_CODEX_HOME", "var/codex-worker-users"
        ))
        # The image initializer requests 0711. Some volume providers
        # normalize a mounted root to 0755; either way, sibling contents stay
        # protected because each user home below is 0700 and UID-owned.
        self.home_root.mkdir(parents=True, exist_ok=True, mode=0o711)
        legacy_root = legacy_root or os.getenv('MEMORY_SPARK_LEGACY_CODEX_HOME')
        self.legacy_root = Path(legacy_root) if legacy_root else None
        self.command = command or [os.getenv("MEMORY_SPARK_CODEX_BIN", "codex"), "app-server"]
        self.privdrop = os.getenv("MEMORY_SPARK_CODEX_PRIVDROP_BIN", "/usr/bin/setpriv")
        self.base_url = base_url or os.getenv(
            "MEMORY_SPARK_LLM_BASE_URL", "http://127.0.0.1:4000/v1"
        )
        self.model = model or os.getenv("MEMORY_SPARK_LLM_MODEL", "deepseek-v4-flash")
        self.api_key = os.getenv("MEMORY_SPARK_LLM_API_KEY", "")
        # Bound the whole execution, not each protocol request separately.
        # This remains below the API's 300-second lease even if the API dies.
        self.timeout = min(timeout, 240)
        self._locks: dict[str, object] = {}
        self._identity_lock = threading.Lock()
        self._identity_file = self.home_root / ".user-ids.json"

    def _lock(self, user_id: str, agent_role: str = 'collector'):
        # This lock is only an in-worker optimization. The API's Supabase
        # lease remains authoritative across replicas and worker instances.
        import asyncio

        key = user_id if agent_role == 'collector' else f'{user_id}:{agent_role}'
        return self._locks.setdefault(key, asyncio.Lock())

    def _uid_for(self, user_id: str) -> int:
        """Allocate a stable, non-system UID for the user's Codex process."""
        with self._identity_lock, (self.home_root / '.identity.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            try:
                mapping = json.loads(self._identity_file.read_text(encoding="utf-8"))
            except FileNotFoundError:
                mapping = {}
            if user_id in mapping:
                return int(mapping[user_id])

            used = {int(value) for value in mapping.values()}
            first = 20000 + (int(hashlib.sha256(user_id.encode()).hexdigest()[:8], 16) % 40000)
            candidate = first
            while candidate in used:
                candidate = 20000 + ((candidate - 20000 + 1) % 40000)
                if candidate == first:
                    raise RuntimeError("No Codex worker UID is available")
            mapping[user_id] = candidate
            temporary = self._identity_file.with_suffix(".tmp")
            temporary.write_text(json.dumps(mapping, sort_keys=True), encoding="utf-8")
            os.chmod(temporary, 0o600)
            os.replace(temporary, self._identity_file)
            return candidate

    def _home(self, user_id: str, uid: int, agent_role: str = 'collector') -> Path:
        # Workspace extraction must not contend with the persisted collector
        # thread. It gets a separate home while remaining under the same
        # per-user root and UID boundary.
        home_key = user_id if agent_role == 'collector' else f'{user_id}-{agent_role}'
        home = self.home_root / home_key
        if agent_role == 'collector' and not home.exists() and not home.is_symlink() and self.legacy_root is not None:
            migrate_home(self.legacy_root / user_id, home, uid)
        home.mkdir(parents=True, exist_ok=True, mode=0o700)
        write_config(home, self.home_root, uid, provider_config(self.base_url, self.model))
        return home

    def _run_command(self, uid: int):
        return [
            self.privdrop,
            f"--reuid={uid}",
            f"--regid={uid}",
            "--clear-groups",
            "--no-new-privs",
            *self.command,
        ]

    async def turn(self, payload: WorkerTurnInput, on_delta=None, on_event=None):
        user_id = str(payload.user_id)
        async with self._lock(user_id, payload.agent_role):
            # Shared-volume lock also covers API disconnect/lease expiry and
            # multiple worker processes. Collector and workspace passes have
            # separate homes and therefore separate locks.
            lock_key = user_id if payload.agent_role == 'collector' else f'{user_id}-{payload.agent_role}'
            lock_name = hashlib.sha256(lock_key.encode()).hexdigest()[:32]
            with (self.home_root / f'.turn-{lock_name}.lock').open('a') as lock:
                try:
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    raise AgentTurnBusyError('Codex worker is busy for this user') from None
                async with asyncio.timeout(self.timeout):
                    options = {}
                    if on_delta:
                        options['on_delta'] = on_delta
                    if on_event:
                        options['on_event'] = on_event
                    return await self._turn(payload, **options)

    async def _turn(self, payload: WorkerTurnInput, on_delta=None, on_event=None):
        user_id = str(payload.user_id)
        uid = self._uid_for(user_id)
        home = self._home(user_id, uid, payload.agent_role)
        correlation = normalise_correlation(payload.evaluation)
        trajectory = None
        if correlation:
            trajectory = TrajectoryRecorder(
                correlation,
                skill_manifest=build_skill_manifest(Path(__file__).resolve().parents[2] / 'skills'),
            )
            trajectory.set_context(agent_role=payload.agent_role, language=payload.language, model=payload.model or self.model)
            trajectory.record('application', 'worker.turn.received', input={
                'thread_id': payload.thread_id,
                'project_id': payload.project_id,
                'text': payload.text,
            })
        model = payload.model or self.model
        language = normalize_conversation_language(payload.language)
        context = "\n".join(str(memory)[:2000] for memory in payload.memories) or "(none)"
        if payload.agent_role == 'collector':
            instructions = build_conversation_system_prompt(
                context,
                payload.profile,
                place_journey=payload.place_journey,
                family_context=payload.family_context,
                language=language,
            )
        elif payload.agent_role == 'workspace':
            instructions = build_workspace_extraction_prompt(
                context,
                payload.profile,
                place_journey=payload.place_journey,
                family_enabled=payload.family_enabled,
                family_context=payload.family_context,
                task_sources=payload.task_sources,
                language=language,
            )
        else:
            instructions = build_system_prompt(
                context,
                payload.profile,
                place_journey=payload.place_journey,
                family_enabled=payload.family_enabled,
                family_context=payload.family_context,
                language=language,
            )
        if payload.agent_role == 'organiser':
            instructions = organiser_prompt(payload.task_sources, language)
        elif payload.agent_role == 'memory_context':
            instructions = build_language_intake_prompt()
        prompt = f"{instructions}\n\nStoryteller message:\n{payload.text}"
        environment = {"MEMORY_SPARK_LLM_API_KEY": self.api_key}
        try:
            async with CodexConnection(
                self._run_command(uid),
                home,
                provider_env=environment,
                timeout=self.timeout,
                trajectory=trajectory,
            ) as connection:
                if payload.thread_id and payload.agent_role == 'collector':
                    result = await connection.request("thread/resume", {
                        "threadId": payload.thread_id,
                        "cwd": str(home),
                        "modelProvider": "llm_provider",
                        "model": model,
                        "approvalPolicy": "never",
                        "sandbox": "read-only",
                        "baseInstructions": instructions,
                    })
                else:
                    result = await connection.request("thread/start", {
                        "cwd": str(home),
                        "ephemeral": payload.agent_role in {'memory_context', 'workspace'},
                        "modelProvider": "llm_provider",
                        "model": model,
                        "approvalPolicy": "never",
                        "sandbox": "read-only",
                        "baseInstructions": instructions,
                    })
                thread_id = result["thread"]["id"]
                reply = await connection.turn(
                    thread_id,
                    prompt,
                    **({'output_schema': LANGUAGE_INTAKE_SCHEMA} if payload.agent_role == 'memory_context' else {}),
                    **({'on_delta': on_delta} if on_delta and payload.agent_role == 'collector' else {}),
                    **({'responsesapi_client_metadata': correlation} if correlation else {}),
                )
            if trajectory:
                trajectory.record('application', 'worker.turn.completed', output={'thread_id': thread_id, 'reply': reply})
                trajectory.finish(reply, status='completed', stop_reason='turn.completed')

            if on_event:
                await on_event({
                    'type': 'provider_complete',
                    'data': {'thread_id': thread_id, 'reply': reply},
                })
        except BaseException as error:
            if trajectory:
                trajectory.finish(None, status='failed', stop_reason='turn.failed', error=str(error))
            raise

        artifacts = [
            {"path": path, "content": base64.b64encode(content).decode("ascii")}
            for path, content in (iter_artifacts(home) if payload.agent_role == 'collector' else [])
        ]
        result = {"thread_id": thread_id, "reply": reply, "artifacts": artifacts}
        if trajectory:
            result["trajectory"] = trajectory.payload()
        return result


app = FastAPI(title="Memory Spark Codex Worker")
worker = CodexWorker()


@app.post('/internal/tasks', status_code=202)
async def publish_task(payload: PublishTaskInput, x_codex_worker_secret: str | None = Header(default=None)):
    # Called only after the API authorises the sources and commits the turn.
    # No task volume is mounted here: tenant runtimes cannot reach its contents.
    _require_worker_secret(x_codex_worker_secret)
    target = os.getenv('MEMORY_SPARK_TASK_STORE_URL', '').rstrip('/')
    if not target:
        raise HTTPException(503, 'Task persistence is not configured')
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(target + '/internal/tasks',
                headers={'X-Codex-Worker-Secret': x_codex_worker_secret},
                json=payload.model_dump(mode='json'))
            response.raise_for_status()
            return response.json()
    except httpx.HTTPError:
        raise HTTPException(503, 'Task persistence unavailable; retry the same task') from None


def _require_worker_secret(provided: str | None):
    expected = os.getenv("MEMORY_SPARK_CODEX_WORKER_SECRET", "")
    if not expected or not provided or not hmac.compare_digest(provided, expected):
        raise HTTPException(status_code=401, detail="Invalid Codex worker credentials")


@app.get("/health")
def health():
    return {"status": "ok", "service": "memory-spark-codex-worker"}


@app.post("/internal/codex/turn")
async def turn(payload: WorkerTurnInput, request: Request,
               x_codex_worker_secret: str | None = Header(default=None)):
    _require_worker_secret(x_codex_worker_secret)
    if 'application/x-ndjson' in request.headers.get('accept', ''):
        return StreamingResponse(turn_events(lambda emit: worker.turn(payload, on_delta=emit,
                                                                        on_event=emit.event)),
                                 media_type='application/x-ndjson', headers=STREAM_HEADERS)
    task = asyncio.create_task(worker.turn(payload))
    try:
        while not task.done():
            if await request.is_disconnected():
                task.cancel()
                break
            await asyncio.wait({task}, timeout=0.1)
        return await task
    except AgentTurnBusyError as error:
        raise HTTPException(status_code=409, detail=str(error)) from None
    except TimeoutError:
        raise HTTPException(status_code=504, detail='Codex worker turn timed out') from None
    except RuntimeError as error:
        raise HTTPException(status_code=502, detail=f"Codex worker failed: {error}") from None
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
