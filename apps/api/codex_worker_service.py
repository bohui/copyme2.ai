"""Private Codex worker for isolated, per-user app-server execution."""
from __future__ import annotations

import asyncio
from contextvars import ContextVar
import fcntl
import hashlib
import hmac
import json
import logging
import os
import threading
import time
from pathlib import Path
from typing import Any, Literal
from uuid import UUID

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from .turn_stream import STREAM_HEADERS, turn_events
from .lifetime_memory_activation import ActivationPublication, CanonicalActivationUnavailable
from .lifetime_memory_policy import PolicyUnavailable
from pydantic import BaseModel, Field, model_validator

from .codex_agent import CodexConnection
from .collector_configuration import CollectorConfigurationError, collector_configuration
from .conversation_phase import PhaseState
from .codex_timeout_policy import WORKER_TIMEOUT, WORKER_MAX_TIMEOUT
from .codex_progress import WorkerProgress
from .issue14_execution_admission import (
    AdmissionDenied, check_issue14_dispatch, validate_optional_issue14_admission,
)
from .codex_runtime import (
    WORKSPACE_TIMEOUT,
)
from .diagnostics import configure_diagnostic_logger, elapsed_ms, failure_class, log_diagnostic, new_request_id
from .trajectory_evaluation import execution_correlation
from .agent_lock import AgentTurnBusyError
from .memoir_tasks import MemorySource
from .memoir_preview import composer_timeout
from .lifetime_memory_lane_engine import BoundedLaneInput, LaneGenerationPaused, run_bounded_lane
from .lifetime_memory_job_engine import BoundedJobInput, JobOutputInvalid, run_bounded_job

from .lifetime_memory_engine import (
    GovernedCollectorInput, run_governed_collector, validate_governed_context,
)


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
    governed: GovernedCollectorInput | None = None
    bounded_lane: BoundedLaneInput | None = None
    bounded_job: BoundedJobInput | None = None
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
    conversation_phase: PhaseState | None = None
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
    evaluation: dict[str, str] = Field(default_factory=dict, max_length=13)
    # Internal-only correlation for bounded service diagnostics. It is never
    # included in the storyteller prompt or reply.
    diagnostic_request_id: str | None = Field(default=None, min_length=1, max_length=96)


    @model_validator(mode='before')
    @classmethod
    def reject_unknown_governed_fields(cls, value):
        if isinstance(value, dict) and any(value.get(key) is not None for key in ('governed','bounded_lane','bounded_job')):
            if set(value) - set(cls.model_fields):
                raise ValueError('Governed turns reject unknown legacy context fields')
        return value

    @model_validator(mode='after')
    def bound_conversation_input(self):
        if sum(value is not None for value in (self.governed,self.bounded_lane,self.bounded_job))>1:
            raise ValueError('Governed execution contracts cannot be combined')
        if self.bounded_job is not None:
            if (self.text or self.thread_id or self.memories or self.profile or self.place_journey
                    or self.family_context or self.family_enabled or self.canonical_events
                    or self.task_sources or self.extraction_focus or self.interview_context is not None
                    or self.conversation_rounds_completed is not None or self.preparation_id is not None):
                raise ValueError('Bounded collection jobs cannot mix legacy execution context')
            job=self.bounded_job
            if (self.agent_role!='organiser' or self.user_id!=job.fence.user_id
                    or self.project_id!=job.fence.project_id
                    or (self.model is not None and self.model!=job.budget.model)
                    or (self.language is not None and self.language!=job.fence.locale)):
                raise ValueError('Bounded collection job role, owner, project, language or model mismatch')
            return self
        if self.bounded_lane is not None:
            if (self.governed is not None or self.text or self.thread_id or self.memories or self.profile
                    or self.place_journey or self.family_context or self.family_enabled
                    or self.canonical_events or self.task_sources or self.extraction_focus
                    or self.interview_context is not None or self.conversation_rounds_completed is not None
                    or self.preparation_id is not None):
                raise ValueError('Bounded lanes cannot mix legacy execution context')
            lane = self.bounded_lane
            role = ('memory_context' if lane.phase == 'profile' else
                'author_timeline' if lane.phase in {'extract','summarize'} else 'composer')
            if (self.agent_role != role or self.user_id != lane.fence.user_id
                    or self.project_id != lane.fence.project_id
                    or (self.model is not None and self.model != lane.budget.model)
                    or (self.language is not None and self.language != lane.fence.locale)
                    or (role == 'composer' and self.composer_phase != lane.phase)):
                raise ValueError('Bounded lane role, identity, language or model mismatch')
            return self
        if self.governed is not None:
            if (self.agent_role != 'collector' or self.text or self.memories or self.profile
                    or self.place_journey or self.family_context or self.family_enabled
                    or self.canonical_events or self.task_sources or self.extraction_focus
                    or self.conversation_rounds_completed is not None):
                raise ValueError('Governed turns cannot mix legacy collector context')
            identity = self.governed.fence.identity
            if self.user_id != identity.owner_id or (self.project_id is not None and self.project_id != identity.project_id):
                raise ValueError('Governed collector identity mismatch')
            packet = validate_governed_context(self.governed, self.interview_context, model=self.model)
            if self.language is not None and self.language != packet.pinned.language:
                raise ValueError('Governed collector language mismatch')
            return self

        raise ValueError('A canonical execution contract is required')


class CodexWorker:
    """Run Codex outside the API container and under a user-specific UID."""

    def __init__(self, *, home_root=None, command=None, base_url=None, model=None,
                 timeout=None, api_key=None, reasoning_effort=None, issue14_admission=None):
        self._issue14_admission = validate_optional_issue14_admission(issue14_admission)
        self.home_root = Path(home_root or os.getenv(
            "MEMORY_SPARK_CODEX_HOME", "var/codex-worker-users"
        ))
        # The image initializer requests 0711. Some volume providers
        # normalize a mounted root to 0755; either way, sibling contents stay
        # protected because each user home below is 0700 and UID-owned.
        self.home_root.mkdir(parents=True, exist_ok=True, mode=0o711)
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
                configured_timeout = float(os.getenv("MEMORY_SPARK_CODEX_WORKER_TIMEOUT", str(WORKER_TIMEOUT)))
            except ValueError:
                configured_timeout = WORKER_TIMEOUT
        # Keep explicit sub-second values available to unit tests; deployed
        # values are bounded above and the normal default remains 120s.
        self.timeout = min(max(float(configured_timeout), 0.001), WORKER_MAX_TIMEOUT)
        self._deadline_context = ContextVar('worker_execution_deadline', default=None)
        self._progress_context = ContextVar('worker_execution_progress', default=None)
        self._locks: dict[str, object] = {}
        from .two_lane_memory import RuntimeCapacity
        self._capacity=RuntimeCapacity()
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

    def execution_deadline_expired(self, payload):
        """Read this task's actual timeout context for this exact dispatch."""
        evidence = self._deadline_context.get()
        return bool(evidence is not None and evidence[0] is payload
                    and evidence[2] is asyncio.current_task()
                    and evidence[1] is not None and evidence[1].expired())


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
        # Diagnostics remain bound to the caller's exact dispatch object; the
        # separately detached execution payload cannot be mutated across awaits.
        deadline_payload = payload
        self._progress_context.set(None)
        self._deadline_context.set((deadline_payload, None, asyncio.current_task()))
        payload = WorkerTurnInput.model_validate(payload.model_dump(mode='json'))
        from .lifetime_memory_lane_engine import check_lane_generation
        check_lane_generation()
        check_issue14_dispatch(self._issue14_admission, role=payload.agent_role,
            correlation=payload.evaluation)
        progress = WorkerProgress()
        self._progress_context.set((deadline_payload, progress, asyncio.current_task()))
        user_id = str(payload.user_id)
        request_id = new_request_id(payload.diagnostic_request_id)
        if payload.diagnostic_request_id != request_id:
            payload = payload.model_copy(update={'diagnostic_request_id': request_id})
        started = time.perf_counter()
        model = payload.model or (os.getenv('MEMORY_SPARK_MEMOIR_COMPOSER_MODEL', self.model)
                                  if payload.agent_role in {'composer', 'author_timeline'} else self.model)
        collector = collector_configuration(model) if payload.agent_role == 'collector' else None
        if collector:
            model = collector.model
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
            from .two_lane_memory import two_lanes_enabled
            from contextlib import AsyncExitStack
            async with AsyncExitStack() as admission:
                if two_lanes_enabled():
                    await admission.enter_async_context(self._capacity.slot(interactive=payload.agent_role=='collector',
                        serial_lock=self._lock(user_id, execution_role)))
                else:
                    await admission.enter_async_context(self._lock(user_id, execution_role))
                if payload.agent_role == 'composer' and payload.bounded_lane is None:
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
                    async with asyncio.timeout(self._execution_timeout(payload.agent_role, payload.composer_phase)) as execution_deadline:
                        self._deadline_context.set((deadline_payload, execution_deadline, asyncio.current_task()))
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

        finally:
            progress.close()

    def execution_progress(self, payload):
        evidence = self._progress_context.get()
        if (evidence is None or evidence[0] is not payload or evidence[2] is not asyncio.current_task()
                or type(evidence[1]) is not WorkerProgress):
            return None
        return evidence[1].snapshot()


    @staticmethod
    def _execution_role(payload):
        if payload.bounded_job is not None:
            return 'job-' + str(payload.bounded_job.fence.job_id)
        if payload.bounded_lane is not None:
            return 'bounded-' + str(payload.bounded_lane.fence.lane_id)
        if payload.agent_role == 'composer' and payload.composer_phase == 'prepare':
            if not payload.preparation_id:
                raise ValueError('Preparation requires an opaque task ID')
            return 'composer-' + payload.preparation_id
        return payload.agent_role

    async def _turn(self, payload: WorkerTurnInput, on_delta=None, on_event=None):
        if payload.governed is not None or payload.bounded_lane is not None or payload.bounded_job is not None:
            payload = WorkerTurnInput.model_validate(payload.model_dump(mode='json'))
        check_issue14_dispatch(self._issue14_admission, role=payload.agent_role,
            correlation=payload.evaluation)
        user_id = str(payload.user_id)
        uid = self._uid_for(user_id)
        model = payload.model or (os.getenv('MEMORY_SPARK_MEMOIR_COMPOSER_MODEL', self.model)
                                  if payload.agent_role in {'composer', 'author_timeline'} else self.model)
        collector = collector_configuration(model) if payload.agent_role == 'collector' else None
        if collector:
            model = collector.model
        if payload.bounded_job is not None:
            return await run_bounded_job(command=self._run_command(uid),home_root=self.home_root,
                base_url=self.base_url,api_key=self.api_key,model=model,
                bounded_job=payload.bounded_job,timeout=self._execution_timeout(payload.agent_role,payload.composer_phase),
                connection_factory=CodexConnection,issue14_admission=self._issue14_admission,
                progress=self._progress_context.get()[1] if self._progress_context.get() else None,
                uid=uid,apply_owner=os.getenv('MEMORY_SPARK_DISABLE_PRIVDROP') != '1',effort=self.reasoning_effort)
        if payload.bounded_lane is not None:
            return await run_bounded_lane(command=self._run_command(uid),home_root=self.home_root,
                base_url=self.base_url,api_key=self.api_key,model=model,
                bounded_lane=payload.bounded_lane,timeout=self._execution_timeout(payload.agent_role,payload.composer_phase),
                connection_factory=CodexConnection,issue14_admission=self._issue14_admission,
                progress=self._progress_context.get()[1] if self._progress_context.get() else None,
                uid=uid,apply_owner=os.getenv('MEMORY_SPARK_DISABLE_PRIVDROP') != '1',
                effort=self.reasoning_effort)
        if payload.governed is not None:
            # Do not visit or migrate any legacy home. Both transports use the
            # identical packet and fresh-home execution/budget validation seam.
            from .trajectory_evaluation import TrajectoryRecorder
            recorder = TrajectoryRecorder(payload.evaluation) if payload.evaluation else None
            if recorder is not None:
                recorder.set_context(agent_role='collector',model=model,language=payload.language,
                    execution_contract='canonical')
            try:
                return await run_governed_collector(
                    command=self._run_command(uid), home_root=self.home_root,
                    base_url=self.base_url, api_key=self.api_key, model=model,
                    governed=payload.governed, interview_context=payload.interview_context,
                    thread_id=payload.thread_id, timeout=self._execution_timeout('collector'),
                    on_delta=on_delta, on_event=on_event,
                    effort=collector.effort or self.reasoning_effort,
                    responsesapi_client_metadata={**execution_correlation(payload.evaluation, model),
                        'request_id':new_request_id(payload.diagnostic_request_id)},
                    connection_factory=CodexConnection, issue14_admission=self._issue14_admission,
                    progress=self._progress_context.get()[1] if self._progress_context.get() else None,
                    uid=uid, apply_owner=os.getenv('MEMORY_SPARK_DISABLE_PRIVDROP') != '1',
                    trajectory=recorder,
                )
            except BaseException as error:
                if recorder is not None:
                    recorder.finish(status='failed',stop_reason='canonical.worker.failed',
                        error={'error_type':type(error).__name__})
                    error.trajectory=recorder.payload()
                raise
        raise ValueError('A canonical execution contract is required')


app = FastAPI(title="Memory Spark Codex Worker")
worker = CodexWorker()


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
    try:
        from .lifetime_memory_lane_engine import check_lane_generation
        check_lane_generation()
        async with ActivationPublication(os.getenv('MEMOIR_PUBLICATION_DATABASE_URL'),
                authenticated_owner=payload.user_id).guard():
            pass
    except LaneGenerationPaused:
        raise HTTPException(503, 'Conversation generation is paused; retry later',
            headers={'X-Error-Code': LaneGenerationPaused.code, 'Retry-After': '60'}) from None
    except CanonicalActivationUnavailable:
        raise HTTPException(503, 'Conversation provider authority is unavailable',
            headers={'X-Error-Code': CanonicalActivationUnavailable.code, 'Retry-After': '60'}) from None
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
        result = await task
        return result
    except AgentTurnBusyError as error:
        raise HTTPException(status_code=409, detail=str(error)) from None
    except PolicyUnavailable:
        raise HTTPException(503, 'Accepted conversation policy requires maintenance before private content can be used',
            headers={'X-Error-Code': PolicyUnavailable.code, 'Retry-After': '60'}) from None
    except CanonicalActivationUnavailable:
        raise HTTPException(503, 'Conversation provider authority is unavailable',
            headers={'X-Error-Code': CanonicalActivationUnavailable.code, 'Retry-After': '60'}) from None
    except JobOutputInvalid:
        raise HTTPException(status_code=502, detail='Collection output requires bounded repair',
                            headers={'X-Error-Code': JobOutputInvalid.code, 'Retry-After': '60'}) from None
    except LaneGenerationPaused:
        raise HTTPException(status_code=503, detail='Bounded lifetime generation is paused; retry later',
                            headers={'X-Error-Code': LaneGenerationPaused.code, 'Retry-After': '60'}) from None
    except ComposerProviderUnavailable:
        raise HTTPException(status_code=503, detail='The model provider is unavailable',
                            headers={'X-Error-Code': 'COMPOSER_PROVIDER_UNAVAILABLE'}) from None
    except CollectorConfigurationError:
        raise HTTPException(status_code=503, detail='Conversational generation is temporarily unavailable',
                            headers={'X-Error-Code': 'COLLECTOR_CONFIGURATION_INVALID'}) from None
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
