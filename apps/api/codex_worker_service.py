"""Private Codex worker for isolated, per-user app-server execution."""
from __future__ import annotations

import base64
import asyncio
import fcntl
import hashlib
import hmac
import json
import logging
import os
import threading
import time
import httpx
from pathlib import Path
from typing import Any, Literal
from uuid import UUID
from urllib.parse import urlsplit

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from .turn_stream import STREAM_HEADERS, turn_events
from pydantic import BaseModel, Field, model_validator

from .codex_agent import CodexConnection, provider_config
from .issue14_execution_admission import (
    AdmissionDenied, check_issue14_dispatch, issue14_connection_options,
    validate_optional_issue14_admission,
)
from .codex_artifacts import iter_artifacts
from .codex_runtime import (
    LANGUAGE_INTAKE_SCHEMA,
    WORKSPACE_TIMEOUT,
    build_conversation_system_prompt,
    build_language_intake_prompt,
    build_system_prompt,
    build_workspace_extraction_prompt,
    normalize_conversation_language,
)
from .codex_worker_files import migrate_home, write_config
from .diagnostics import configure_diagnostic_logger, elapsed_ms, failure_class, log_diagnostic, new_request_id
from .trajectory_evaluation import TrajectoryRecorder, build_skill_manifest, normalise_correlation
from .agent_lock import AgentTurnBusyError
from .agent_tasks import organiser_prompt
from .memoir_tasks import MemorySource, PublishTaskInput
from .memoir_preview import composer_timeout, composer_instructions, composer_output_schema
from .memory_events import extraction_instructions, extraction_schema
from .interview_plan import collector_schema


diagnostic_logger = logging.getLogger("memoir.worker.diagnostics")
configure_diagnostic_logger(diagnostic_logger)


class ComposerProviderUnavailable(RuntimeError):
    """The configured provider is offline; no model work has been attempted."""


class WorkerTurnError(RuntimeError):
    """A failed worker turn carrying recorder-redacted evidence."""

    def __init__(self, message: str, trajectory: dict[str, Any]):
        super().__init__(message)
        self.trajectory = trajectory


class WorkerTurnInput(BaseModel):
    user_id: UUID
    thread_id: str | None = Field(default=None, min_length=1, max_length=256)
    memories: list[str] = Field(default_factory=list, max_length=20)
    profile: dict[str, Any] = Field(default_factory=dict)
    place_journey: dict[str, Any] = Field(default_factory=dict)
    family_enabled: bool = False
    canonical_events: bool = False
    family_context: dict[str, Any] = Field(default_factory=dict)
    project_id: str | None = Field(default=None, min_length=1, max_length=128)
    text: str = Field(default="", max_length=500000)
    interview_context: dict[str, Any] | None = None
    model: str | None = Field(default=None, min_length=1, max_length=256)
    language: str | None = Field(default=None, pattern="^(en-AU|zh-CN)$")
    conversation_rounds_completed: int | None = Field(default=None, ge=0)
    agent_role: Literal['collector', 'organiser', 'memory_context', 'workspace', 'composer', 'author_timeline'] = 'collector'
    extraction_focus: Literal['family_tree', 'author_timeline', 'place_journey'] | None = None
    composer_phase: Literal['index', 'prepare', 'draft', 'review'] = 'draft'
    preparation_id: str | None = Field(default=None, pattern='^[a-f0-9]{64}$')
    task_sources: list[MemorySource] = Field(default_factory=list, max_length=1000)
    # Present only for local/CI evaluation. Normal product turns do not carry
    # evaluation IDs and therefore do not return trajectory evidence.
    evaluation: dict[str, str] = Field(default_factory=dict, max_length=12)
    # Internal-only correlation for bounded service diagnostics. It is never
    # included in the storyteller prompt or reply.
    diagnostic_request_id: str | None = Field(default=None, min_length=1, max_length=96)


    @model_validator(mode='after')
    def bound_conversation_input(self):
        if not self.text and not (self.agent_role == 'collector' and self.interview_context and self.interview_context.get('photo_context')):
            raise ValueError('A collector turn needs narration or an accepted photo cue')
        if self.agent_role not in {'composer', 'author_timeline'} and len(self.text) > 100000:
            raise ValueError('Conversation input exceeds the supported limit')
        return self


class CodexWorker:
    """Run Codex outside the API container and under a user-specific UID."""

    def __init__(self, *, home_root=None, legacy_root=None, command=None, base_url=None, model=None,
                 timeout=None, api_key=None, reasoning_effort=None, issue14_admission=None):
        self._issue14_admission = validate_optional_issue14_admission(issue14_admission)
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
        self.model = model or os.getenv("MEMORY_SPARK_LLM_MODEL", "gpt-5.6-luna-pooled")
        self.api_key = api_key if api_key is not None else os.getenv("MEMORY_SPARK_LLM_API_KEY", "")
        self.reasoning_effort = reasoning_effort
        # Bound the whole execution, not each protocol request separately.
        # Collector/workspace budgets stay below their conversation leases;
        # composer phases use the separate private-draft budget below.
        configured_timeout = timeout
        if configured_timeout is None:
            try:
                configured_timeout = float(os.getenv("MEMORY_SPARK_CODEX_WORKER_TIMEOUT", "120"))
            except ValueError:
                configured_timeout = 120
        # Keep explicit sub-second values available to unit tests; deployed
        # values are bounded above and the normal default remains 120s.
        self.timeout = min(max(float(configured_timeout), 0.001), 240)
        self._locks: dict[str, object] = {}
        self._identity_lock = threading.Lock()
        self._identity_file = self.home_root / ".user-ids.json"

    def _lock(self, user_id: str, agent_role: str = 'collector'):
        # This lock is only an in-worker optimization. The API's Supabase
        # lease remains authoritative across replicas and worker instances.
        import asyncio

        key = user_id if agent_role == 'collector' else f'{user_id}:{agent_role}'
        return self._locks.setdefault(key, asyncio.Lock())

    def _execution_timeout(self, agent_role: str, composer_phase: str = 'index'):
        if agent_role == 'composer':
            return composer_timeout(composer_phase)
        if agent_role == 'workspace':
            return WORKSPACE_TIMEOUT
        return self.timeout

    @staticmethod
    def _refresh_collector_thread(payload: WorkerTurnInput) -> bool:
        """Start a fresh persisted thread before a long history dominates latency.

        The application still supplies the bounded saved-memory context, so this
        is a context compaction boundary rather than a loss of the memoir. A
        worker process must not spend the whole collector budget replaying every
        prior protocol turn at the final review checkpoint.
        """
        return (
            payload.agent_role == 'collector'
            and payload.thread_id is not None
            and payload.conversation_rounds_completed is not None
            and payload.conversation_rounds_completed >= 40
        )

    def _uid_for(self, user_id: str) -> int:
        """Allocate a stable, non-system UID for the user's Codex process."""
        # The explicit local/macOS evaluation mode does not have Linux's
        # privileged chown/setpriv boundary. Use the current account so the
        # isolated worker can exercise the real app-server path without
        # pretending to provide production tenant isolation. Production keeps
        # the default path below and never sets this flag.
        if os.getenv("MEMORY_SPARK_DISABLE_PRIVDROP") == "1":
            return os.getuid()
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
        write_config(
            home,
            self.home_root,
            uid,
            provider_config(self.base_url, self.model),
            apply_owner=os.getenv("MEMORY_SPARK_DISABLE_PRIVDROP") != "1",
        )
        return home

    def _run_command(self, uid: int):
        # macOS development/CI hosts do not provide Linux's setpriv. The
        # isolated evaluation worker runs under its own process and workspace
        # boundary, so it can opt out explicitly without weakening the
        # production default or changing normal worker deployments.
        if os.getenv("MEMORY_SPARK_DISABLE_PRIVDROP") == "1":
            return list(self.command)
        return [
            self.privdrop,
            f"--reuid={uid}",
            f"--regid={uid}",
            "--clear-groups",
            "--no-new-privs",
            *self.command,
        ]

    async def turn(self, payload: WorkerTurnInput, on_delta=None, on_event=None):
        check_issue14_dispatch(self._issue14_admission, role=payload.agent_role,
            correlation=payload.evaluation)
        user_id = str(payload.user_id)
        request_id = new_request_id(payload.diagnostic_request_id)
        if payload.diagnostic_request_id != request_id:
            payload = payload.model_copy(update={'diagnostic_request_id': request_id})
        started = time.perf_counter()
        model = payload.model or (os.getenv('MEMORY_SPARK_MEMOIR_COMPOSER_MODEL', self.model)
                                  if payload.agent_role in {'composer', 'author_timeline'} else self.model)
        log_diagnostic(
            diagnostic_logger,
            'worker_turn_start',
            request_id,
            component='memoir.codex_worker',
            agent_role=payload.agent_role,
            model=model,
            streaming=bool(on_delta or on_event),
        )
        try:
            execution_role = self._execution_role(payload)
            async with self._lock(user_id, execution_role):
                if payload.agent_role == 'composer':
                    await self._ensure_composer_provider()
                # Shared-volume lock also covers API disconnect/lease expiry and
                # multiple worker processes. Collector and workspace passes have
                # separate homes and therefore separate locks.
                lock_key = user_id if payload.agent_role == 'collector' else f'{user_id}-{execution_role}'
                lock_name = hashlib.sha256(lock_key.encode()).hexdigest()[:32]
                with (self.home_root / f'.turn-{lock_name}.lock').open('a') as lock:
                    try:
                        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    except BlockingIOError:
                        raise AgentTurnBusyError('Codex worker is busy for this user') from None
                    async with asyncio.timeout(self._execution_timeout(payload.agent_role, payload.composer_phase)):
                        options = {}
                        if on_delta:
                            options['on_delta'] = on_delta
                        if on_event:
                            options['on_event'] = on_event
                        result = await self._turn(payload, **options)
            log_diagnostic(
                diagnostic_logger,
                'worker_turn_terminal',
                request_id,
                component='memoir.codex_worker',
                agent_role=payload.agent_role,
                model=model,
                status='completed',
                terminal_event='worker.turn',
                elapsed_ms=elapsed_ms(started),
            )
            return result
        except BaseException as error:
            log_diagnostic(
                diagnostic_logger,
                'worker_turn_failed',
                request_id,
                component='memoir.codex_worker',
                agent_role=payload.agent_role,
                model=model,
                status='failed',
                failure_class=failure_class(error),
                elapsed_ms=elapsed_ms(started),
            )
            raise

    async def _ensure_composer_provider(self):
        check_issue14_dispatch(self._issue14_admission, role='composer')
        # Codex internally retries connection failures. Reject an unreachable
        # endpoint before starting that loop, without sending source data.
        endpoint = urlsplit(self.base_url)
        try:
            _, writer = await asyncio.wait_for(asyncio.open_connection(
                endpoint.hostname, endpoint.port or (443 if endpoint.scheme == 'https' else 80)), 5)
            writer.close()
            await writer.wait_closed()
        except (OSError, TimeoutError):
            raise ComposerProviderUnavailable('The model provider is unavailable') from None

    @staticmethod
    def _execution_role(payload):
        if payload.agent_role == 'composer' and payload.composer_phase == 'prepare':
            if not payload.preparation_id:
                raise ValueError('Preparation requires an opaque task ID')
            return 'composer-' + payload.preparation_id
        return payload.agent_role

    async def _turn(self, payload: WorkerTurnInput, on_delta=None, on_event=None):
        check_issue14_dispatch(self._issue14_admission, role=payload.agent_role,
            correlation=payload.evaluation)
        user_id = str(payload.user_id)
        uid = self._uid_for(user_id)
        home = self._home(user_id, uid, self._execution_role(payload))
        model = payload.model or (os.getenv('MEMORY_SPARK_MEMOIR_COMPOSER_MODEL', self.model)
                                  if payload.agent_role in {'composer', 'author_timeline'} else self.model)
        correlation = normalise_correlation(payload.evaluation)
        request_id = new_request_id(payload.diagnostic_request_id)
        started = time.perf_counter()
        log_diagnostic(
            diagnostic_logger,
            'appserver_turn_start',
            request_id,
            component='memoir.codex_worker.appserver_client',
            agent_role=payload.agent_role,
            model=model,
        )
        trajectory = None
        if correlation:
            trajectory = TrajectoryRecorder(
                correlation,
                skill_manifest=build_skill_manifest(Path(__file__).resolve().parents[2] / 'skills'),
            )
            trajectory.set_context(agent_role=payload.agent_role, language=payload.language, model=model)
            trajectory.record('application', 'worker.turn.received', input={
                'thread_id': payload.thread_id,
                'project_id': payload.project_id,
                'text': payload.text,
            })
        language = normalize_conversation_language(payload.language)
        context = "\n".join(str(memory)[:2000] for memory in payload.memories) or "(none)"
        if payload.agent_role == 'collector':
            instructions = build_conversation_system_prompt(
                context,
                payload.profile,
                project_id=payload.project_id,
                place_journey=payload.place_journey,
                family_context=payload.family_context,
                language=language,
                conversation_rounds_completed=payload.conversation_rounds_completed,
                interview_context=payload.interview_context,
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
                focus=payload.extraction_focus,
                canonical_events=payload.canonical_events,
                source_text=payload.text,
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
        elif payload.agent_role == 'composer':
            instructions = composer_instructions(payload.composer_phase)
        elif payload.agent_role == 'author_timeline':
            instructions = extraction_instructions()
        # thread/start and thread/resume already install baseInstructions.
        # Repeating them as user input doubles prompt processing each turn.
        prompt = f"Storyteller message:\n{payload.text}"
        environment = {"MEMORY_SPARK_LLM_API_KEY": self.api_key}
        try:
            async with CodexConnection(
                self._run_command(uid),
                home,
                provider_env=environment,
                timeout=self._execution_timeout(payload.agent_role, payload.composer_phase),
                trajectory=trajectory,
                **issue14_connection_options(self._issue14_admission),
            ) as connection:
                if payload.thread_id and payload.agent_role == 'collector' and not self._refresh_collector_thread(payload):
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
                        "ephemeral": payload.agent_role in {'memory_context', 'workspace', 'composer', 'author_timeline'},
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
                    **({'output_schema': LANGUAGE_INTAKE_SCHEMA} if payload.agent_role == 'memory_context' else
                       {'output_schema': composer_output_schema(payload.composer_phase)} if payload.agent_role == 'composer' else
                       {'output_schema': extraction_schema()} if payload.agent_role == 'author_timeline' else
                       {'output_schema': collector_schema()}
                       if payload.agent_role == 'collector' and payload.interview_context is not None else {}),
                    **({'on_delta': on_delta} if on_delta and payload.agent_role in {'collector', 'workspace'} else {}),
                    **({'on_event': on_event} if on_event else {}),
                    **({'effort': self.reasoning_effort} if self.reasoning_effort is not None else
                       {'effort': os.getenv('MEMORY_SPARK_MEMOIR_COMPOSER_REASONING_EFFORT', 'low')}
                       if payload.agent_role == 'composer' else
                       {'effort': os.getenv('MEMORY_SPARK_AUTHOR_TIMELINE_REASONING_EFFORT', 'low')}
                       if payload.agent_role == 'author_timeline' else {}),
                    responsesapi_client_metadata={**correlation, 'request_id': request_id},
                )
            if trajectory:
                trajectory.record('application', 'worker.turn.completed', output={'thread_id': thread_id, 'reply': reply})
                trajectory.finish(reply, status='completed', stop_reason='turn.completed')

            if on_event:
                await on_event({
                    'type': 'provider_complete',
                    'data': {
                        'thread_id': thread_id,
                        'reply': reply,
                        'trajectory': trajectory.payload() if trajectory else None,
                    },
                })
            log_diagnostic(
                diagnostic_logger,
                'appserver_turn_terminal',
                request_id,
                component='memoir.codex_worker.appserver_client',
                agent_role=payload.agent_role,
                model=model,
                status='completed',
                terminal_event='turn.completed',
                elapsed_ms=elapsed_ms(started),
            )
        except BaseException as error:
            log_diagnostic(
                diagnostic_logger,
                'appserver_turn_failed',
                request_id,
                component='memoir.codex_worker.appserver_client',
                agent_role=payload.agent_role,
                model=model,
                status='failed',
                failure_class=failure_class(error),
                elapsed_ms=elapsed_ms(started),
            )
            if trajectory:
                # Keep the failure receipt useful without copying provider
                # exception text into the trajectory or stream.
                trajectory.finish(
                    None,
                    status='failed',
                    stop_reason='turn.failed',
                    error={'error_type': type(error).__name__},
                )
                if isinstance(error, Exception):
                    raise WorkerTurnError('Codex worker turn failed', trajectory.payload()) from error
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
    try:
        check_issue14_dispatch(getattr(worker, '_issue14_admission', None), role='organiser')
    except AdmissionDenied:
        raise HTTPException(status_code=403, detail='Issue 14 evaluation admission denied',
            headers={'X-Error-Code': 'ISSUE14_ADMISSION_DENIED'}) from None
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
               x_codex_worker_secret: str | None = Header(default=None),
               x_memoir_request_id: str | None = Header(default=None)):
    _require_worker_secret(x_codex_worker_secret)
    try:
        check_issue14_dispatch(getattr(worker, '_issue14_admission', None),
            role=payload.agent_role, correlation=payload.evaluation)
    except AdmissionDenied:
        raise HTTPException(status_code=403, detail='Issue 14 evaluation admission denied',
            headers={'X-Error-Code': 'ISSUE14_ADMISSION_DENIED'}) from None
    request_id = new_request_id(x_memoir_request_id or payload.diagnostic_request_id)
    if payload.diagnostic_request_id != request_id:
        payload = payload.model_copy(update={'diagnostic_request_id': request_id})
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
    except ComposerProviderUnavailable:
        raise HTTPException(status_code=503, detail='The model provider is unavailable',
                            headers={'X-Error-Code': 'COMPOSER_PROVIDER_UNAVAILABLE'}) from None
    except TimeoutError:
        raise HTTPException(status_code=504, detail='Codex worker turn timed out') from None
    except WorkerTurnError as error:
        return JSONResponse(
            status_code=502,
            content={'detail': 'Codex worker failed', 'trajectory': error.trajectory},
        )
    except RuntimeError as error:
        raise HTTPException(status_code=502, detail='Codex worker failed') from None
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
