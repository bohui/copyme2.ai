"""Explicit task-owned session for separately bounded subscription evaluation.

No CLI, credential discovery, shared-service setup, or live default exists here.
An authorized native bootstrap supplies its existing gateway credential, audited
Codex executable and disposable application storage/Temporal resources. Merely
constructing a source object is not numerical approval or a cost attestation.
"""
import asyncio
from copy import deepcopy
from contextvars import ContextVar
import hashlib
import json
import math
import os
from pathlib import Path
import re
import socket
import time
import weakref

import httpx
from fastapi import FastAPI, Request, Response
import uvicorn

from apps.api.agent_storage import UserStorage
from apps.api.diagnostics import failure_class
from apps.api.codex_runtime import CodexRuntime
from apps.api.codex_timeout_policy import WORKER_TIMEOUT, validate_native_collector_timeout
from apps.api.memory_event_worker import MemoryEventWorker, MemoirLaneBroker
from scripts.issue14_progressive_readback import CASE_IDS, ProgressiveReadback, case_plans_for_run
from scripts.issue14_subscription_transport import SubscriptionRun, SubscriptionTransport, MAX_REQUEST_BYTES
from scripts.memoir_subscription_profiles import profile_for


_ISSUED = weakref.WeakSet()
_WORKER_URL = 'http://issue14-task-worker.invalid'
_PROFILES = {
    'collector': ('gpt-5.6-luna-pooled', 'max'),
    'workspace': ('gpt-5.6-luna-pooled', 'max'),
    'memory_context': ('gpt-5.6-luna-pooled', 'max'),
    'author_timeline': ('memoir-luna-low', 'low'),
    'composer': ('memoir-luna-low', 'low'),
}
_OPTIONS = ('model_providers.llm_provider.request_max_retries=0',
    'model_providers.llm_provider.stream_max_retries=0',
    'model_providers.llm_provider.supports_websockets=false',
    'features.memories=false', 'memories.generate_memories=false',
    'memories.use_memories=false', 'web_search="disabled"')


def assert_owned_subscription_session(value):
    if (type(value) is not OwnedSubscriptionSession or value not in _ISSUED or value._closed
            or not value._workflow_ready
            or value._profile != profile_for(value._profile.name, selected_case_ids=value._profile.selected_case_ids)
            or value._plans != value._profile.plans(value.run.run_id)
            or value.run.selected_case_ids != value._profile.selected_case_ids
            or (value._profile.name == 'subscription_fifty' and value.run.case_ids != value._profile.case_ids)
            or value.runtime.worker_transport is not value.worker_transport
            or value.runtime.worker_url != value.worker_url
            or value.provider_transport.run is not value.run
            or value.lane_worker.worker_transport is not value.worker_transport
            or value.lane_worker.worker_url != value.worker_url
            or value.lane_worker.broker is not value.broker
            or type(value.broker) is not _ScopedSubscriptionBroker or value.broker.raw is not value._broker
            or any(w.base_url != value._base_url or tuple(w.command) != value._command
                   or w.model != _PROFILES[role][0] or w.reasoning_effort != _PROFILES[role][1]
                   or w.legacy_root is not None for role, w in value._workers.items())):
        raise ValueError('A live owned subscription session binding is required')


def is_owned_session(value):
    try:
        assert_owned_subscription_session(value)
        return True
    except (ValueError, AttributeError):
        return False


def _json(raw):
    def pairs(values):
        result = {}
        for key, value in values:
            if key in result:
                raise ValueError('Duplicate JSON key')
            result[key] = value
        return result
    value = json.loads(raw, object_pairs_hook=pairs, parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
    if type(value) is not dict:
        raise ValueError('Object required')
    return value


def _response_correlation_matches(data, expected):
    """Codex 0.155.1 encodes application IDs inside its JSON turn metadata.

    Pinned upstream be2951ea, core/src/responses_metadata.rs and its
    app-server client_metadata tests define this envelope. Top-level caller IDs
    are not an alternative contract. Parse duplicate keys strictly and retain
    the exact payload bytes for forwarding; never repair or inject missing IDs.
    """
    metadata = data.get('client_metadata')
    if type(metadata) is not dict or any(key in metadata for key in expected):
        return False
    encoded = metadata.get('x-codex-turn-metadata')
    if type(encoded) is not str:
        return False
    try:
        actual = _json(encoded)
    except (ValueError, TypeError, RecursionError):
        return False
    return all(type(actual.get(key)) is str and actual[key] == value
               for key, value in expected.items())


class _ScopedSubscriptionBroker:
    """Own only the active case's lanes; extraction always precedes composer."""
    def __init__(self, raw, owner):
        self.raw, self.owner, self._round_lanes = raw, owner, []

    @property
    def client(self):
        return self.raw.client

    def _plan(self):
        if self.owner._active is None:
            raise ValueError('Background work requires an active subscription round')
        return self.owner._plans[self.owner._active[0]]

    async def rpc(self, name, **payload):
        result = await self.raw.rpc(name, **payload)
        if name == 'pending_memoir_lanes':
            if type(result) is not list or set(result) - set(self._round_lanes):
                raise ValueError('Unrelated or replayed subscription lane')
            return [lane for lane in self._round_lanes if lane in result]
        if name == 'claim_memoir_lane' and result:
            plan = self._plan()
            if result.get('user_id') != plan['owner_id'] or result.get('project_id') != plan['project_id']:
                raise ValueError('Claimed lane is outside the active case')
        return result

    async def drain_once(self):
        plan = self._plan()
        receipts = await self.raw.rpc('pending_memoir_receipts', p_limit=50)
        if type(receipts) is not list:
            raise ValueError('Malformed subscription outbox')
        timeline, composer = [], []
        for receipt in receipts:
            scope = await self.raw.rpc('read_memoir_receipt_scope', p_receipt_id=receipt)
            if (type(scope) is not dict or scope.get('user_id') != plan['owner_id']
                    or scope.get('project_id') != plan['project_id']
                    or scope.get('change_kind') not in {'round','accepted','events'}):
                raise ValueError('Receipt is outside the active subscription case')
            queued = await self.raw.rpc('queue_memoir_receipt', p_receipt_id=receipt, p_cadence=5)
            if queued:
                if queued.get('timeline_lane_id'): timeline.append(queued['timeline_lane_id'])
                if queued.get('composer_lane_id'): composer.append(queued['composer_lane_id'])
        self._round_lanes = list(dict.fromkeys(timeline + composer))
        return list(self._round_lanes)


class _WorkerTransport(httpx.AsyncBaseTransport):
    def __init__(self, owner):
        self.owner = owner

    async def handle_async_request(self, request):
        owner = self.owner
        assert_owned_subscription_session(owner)
        if request.method != 'POST' or str(request.url) != owner.worker_url + '/internal/codex/turn':
            owner.run.stop('target_forbidden')
            raise httpx.RequestError('Subscription worker target forbidden')
        owner._pending.add(asyncio.current_task())
        scope = owner._active
        try:
            async with asyncio.timeout(owner.run.remaining_seconds()), owner._worker_lock:
                assert_owned_subscription_session(owner)
                if scope is None or scope != owner._active or owner.run.remaining_seconds() <= 0:
                    raise ValueError('Worker scope unavailable')
                body = await request.aread()
                assert_owned_subscription_session(owner)
                if len(body) > MAX_REQUEST_BYTES:
                    raise ValueError('Worker payload too large')
                data = _json(body)
                case_id, ordinal = scope
                plan = owner._plans[case_id]
                role = data.get('agent_role', 'collector')
                observation = getattr(owner, '_collector_observation', None)
                if observation is not None:
                    observation.admit(role, scope)
                expected = owner.bridge_for_case(case_id).before_round(case_id, ordinal)
                job = owner._job_context.get()
                if role in {'author_timeline', 'composer'}:
                    if job is None:
                        raise ValueError('Background worker requires owned activity context')
                    expected['job_id'] = job['job_id']
                    if role == 'composer':
                        if ordinal not in owner._profile.checkpoints:
                            raise ValueError('Composer outside checkpoint')
                        expected['checkpoint_id'] = f'{case_id}:{ordinal}'
                supplied = data.get('evaluation')
                if (role not in _PROFILES or data.get('user_id') != plan['owner_id']
                        or data.get('project_id') != plan['project_id'] or data.get('language') != plan['language']
                        or type(data.get('family_enabled', False)) is not bool
                        or data.get('family_enabled', False) and not owner._profile.family_enabled_for_round(plan, ordinal)
                        or data.get('model') not in (None, _PROFILES[role][0])
                        or supplied is not None and (type(supplied) is not dict
                            or any(supplied.get(k) != v for k, v in expected.items()))):
                    raise ValueError('Worker scope mismatch')
                payload = owner._payload_type.model_validate({**data, 'evaluation': expected,
                                                         'model': _PROFILES[role][0]})
                worker = owner._workers[role]
                owner._dispatch_role = role
                owner._dispatch_correlation = deepcopy(expected)
                before = owner.run.snapshot()
                record = {'case_id': case_id, 'round': ordinal, 'role': role,
                          'phase': payload.composer_phase if role == 'composer' else None,
                          'correlation': deepcopy(expected), 'status': 'started',
                          'execution_timeout_seconds': worker._execution_timeout(role, payload.composer_phase),
                          'started_at_monotonic': time.monotonic(),
                          'client_requests_before': before['client_requests_started'],
                          'completed_responses_before': before['completed_http_responses'],
                          'local_client_requests_seen': 0}
                owner._worker_records.append(record)
                diagnostic_context = [record, deepcopy(expected), role, None]
                owner._worker_diagnostic_contexts.append(diagnostic_context)
                del owner._worker_diagnostic_contexts[:-16]
                owner._dispatch_record = record
                try:
                    result = await worker.turn(payload)
                    record['status'] = 'completed'
                except BaseException as error:
                    expired = worker.execution_deadline_expired(payload)
                    record.update(status='failed', failure_stage='worker_turn',
                        failure_class=failure_class(error), worker_deadline_expired=expired,
                        timeout_origin=('worker_execution_deadline' if expired else
                            'transport_timeout' if isinstance(error, httpx.TimeoutException) else 'unknown_timeout'))
                    raise
                finally:
                    progress = worker.execution_progress(payload)
                    if progress is not None:
                        record['worker_progress'] = progress
                        diagnostic_context[3] = deepcopy(progress)
                    finished = time.monotonic()
                    after = owner.run.snapshot()
                    record.update(finished_at_monotonic=finished,
                        elapsed_ms=max(0, round((finished - record['started_at_monotonic']) * 1000)),
                        client_requests_after=after['client_requests_started'],
                        completed_responses_after=after['completed_http_responses'])
                    owner._dispatch_role = None
                    owner._dispatch_correlation = None
                    owner._dispatch_record = None
                if observation is not None:
                    observation.complete()
                if 'application/x-ndjson' in request.headers.get('accept', ''):
                    # The evaluation is buffered, but the normal runtime still
                    # consumes its existing typed NDJSON worker protocol.
                    # HTTPX aiter_lines also splits Unicode NEL/LS/PS. Escape
                    # them (including nested strings) without changing decoded
                    # text, so one terminal JSON object remains one wire line.
                    terminal = json.dumps({'type': 'result', 'data': result}, ensure_ascii=True) + '\n'
                    return httpx.Response(200, content=terminal.encode(),
                        headers={'Content-Type':'application/x-ndjson'}, request=request)
                return httpx.Response(200, json=result, request=request)
        except BaseException:
            owner.run.stop('send_interrupted_or_failed')
            raise
        finally:
            owner._pending.discard(asyncio.current_task())

    async def aclose(self):
        # One short-lived HTTPX client cannot close the shared owned session.
        pass


class OwnedSubscriptionSession:
    """Own the worker graph and loopback forwarding listener until close()."""
    def __init__(self):
        raise TypeError('Use the explicit native create integration point')

    @classmethod
    async def create(cls, *, run, provider_transport, storages, broker, temporal_client,
                     home_root, codex_binary, codex_sha256, api_key,
                     evaluation_profile='subscription_progressive', entitlement_facades=None,
                     collector_timeout_seconds=WORKER_TIMEOUT, single_collector_observation=False,
                     selected_case_ids=None):
        collector_timeout_seconds = validate_native_collector_timeout(collector_timeout_seconds)
        if type(single_collector_observation) is not bool:
            raise ValueError('Explicit single collector mode required')
        if selected_case_ids is not None and (single_collector_observation or collector_timeout_seconds != 180):
            raise ValueError('Selected fifty-case session requires the bounded full campaign')
        if single_collector_observation:
            from scripts.single_collector_observation import validate_observation_limits
            validate_observation_limits(evaluation_profile,run.limits.max_requests,
                run.limits.max_elapsed_seconds,run.case_limits.max_requests,
                run.case_limits.max_elapsed_seconds,collector_timeout_seconds)
        if (type(run) is not SubscriptionRun or type(provider_transport) is not SubscriptionTransport
                or provider_transport.run is not run or type(api_key) is not str or not api_key):
            raise ValueError('Explicit owned run, transport and existing credential required')
        profile = profile_for(evaluation_profile, selected_case_ids=selected_case_ids)
        case_limits = run.case_limits
        profile.validate_limits(run.limits.max_requests, run.limits.max_elapsed_seconds,
            case_limits.max_requests if case_limits else None,
            case_limits.max_elapsed_seconds if case_limits else None)
        if tuple(run.case_ids or ()) != (profile.case_ids if profile.name == 'subscription_fifty' else ()):
            raise ValueError('Request gate does not match the explicit evaluation profile')
        if run.selected_case_ids != profile.selected_case_ids:
            raise ValueError('Request gate selection differs from the session')
        plans = profile.plans(run.run_id)
        # Validate the original dataset before starting listeners or workers.
        for case, plan in plans.items():
            profile.bridge(case_id=case, run_id=run.run_id, project_id=plan['project_id'],
                           source_revision=run.source_revision)
        if (type(storages) is not dict or set(storages) != set(profile.case_ids)
                or any(type(storages[k]) is not UserStorage or storages[k].user_id != p['owner_id']
                       or storages[k].url != 'http://synthetic.invalid'
                       or type(storages[k].client._transport) is not httpx.MockTransport
                       for k, p in plans.items())):
            raise ValueError('Distinct disposable storage identities required')
        if (type(broker) is not MemoirLaneBroker or broker.url != 'http://synthetic.invalid'
                or type(broker.client._transport) is not httpx.MockTransport):
            raise ValueError('Disposable Postgres RPC facade broker required')
        if profile.name == 'subscription_fifty':
            from memoir_postgres_workflow import PostgresRest
            if (type(entitlement_facades) is not dict or set(entitlement_facades) != set(plans)
                    or any(type(entitlement_facades[case]) is not PostgresRest
                        or entitlement_facades[case].owner != plan['owner_id']
                        or entitlement_facades[case].service is not False
                        or getattr(storages[case].client._transport.handler, '__self__', None) is not entitlement_facades[case]
                        or storages[case].story_entitlement() != profile.entitlement(plan, 1)
                        for case, plan in plans.items())):
                raise ValueError('Owner-scoped synthetic campaign entitlement required')
        elif entitlement_facades is not None:
            raise ValueError('Historical profile has no mutable campaign entitlement facade')
        home, binary = Path(home_root), Path(codex_binary)
        if (home.exists() or home.is_symlink() or not binary.is_absolute() or not binary.is_file()
                or hashlib.sha256(binary.read_bytes()).hexdigest() != codex_sha256):
            raise ValueError('Fresh task home and exact reviewed Codex executable required')
        if run.remaining_seconds() <= 0:
            raise ValueError('Run deadline expired before allocation')
        self = object.__new__(cls)
        self.run, self.provider_transport = run, provider_transport
        self._collector_observation = None
        if single_collector_observation:
            from scripts.single_collector_observation import CollectorObservationGate
            self._collector_observation = CollectorObservationGate(run)
        self.photo_research = None
        self.browser_readback = None
        self._profile = profile
        self._entitlement_facades = dict(entitlement_facades or {})
        self.temporal_client = temporal_client
        self._broker = broker
        self.broker = _ScopedSubscriptionBroker(broker, self)
        self.task_queue = 'canary-subscription-' + run.run_id
        self._plans, self._storages = plans, dict(storages)
        self._active, self._finished, self._pending = None, {case: 0 for case in profile.case_ids}, set()
        self._closed, self._worker_lock = False, asyncio.Lock()
        self._dispatch_role = None
        self._dispatch_correlation = None
        self._dispatch_record = None
        self._job_context = ContextVar('subscription_activity', default=None)
        self._worker_records = []
        self._worker_diagnostic_contexts = []
        self._server = self._server_task = self._socket = None
        self._workflow = None
        self._workflow_ready = False
        self._workers = {}
        home.mkdir(mode=0o700, parents=True)
        # The legacy worker service constructs an unused global worker on import.
        # Defer that import until explicit native creation, and confine even its
        # unused home to this task. Native bootstrap has already removed secrets
        # from the environment; active workers receive the existing key explicitly.
        previous_home = os.environ.get('MEMORY_SPARK_CODEX_HOME')
        os.environ['MEMORY_SPARK_CODEX_HOME'] = str(home / 'unused-module-worker')
        try:
            from apps.api.codex_worker_service import CodexWorker, WorkerTurnInput
            self._payload_type = WorkerTurnInput
        finally:
            if previous_home is None:
                os.environ.pop('MEMORY_SPARK_CODEX_HOME', None)
            else:
                os.environ['MEMORY_SPARK_CODEX_HOME'] = previous_home
        self.worker_url = _WORKER_URL
        self.worker_transport = _WorkerTransport(self)
        self._http = httpx.AsyncClient(transport=provider_transport, follow_redirects=False, trust_env=False)
        app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

        @app.post('/v1/responses')
        async def responses(request: Request):
            record, stage = None, 'owned_dispatch'
            try:
                assert_owned_subscription_session(self)
                if self._active is None or not self._pending or self._dispatch_role not in _PROFILES:
                    raise ValueError('No owned worker dispatch')
                record = self._dispatch_record
                if record is None:
                    raise ValueError('No owned worker record')
                record['local_client_requests_seen'] += 1
                stage = 'client_body'
                chunks, size = [], 0
                async for chunk in request.stream():
                    size += len(chunk)
                    if size > MAX_REQUEST_BYTES:
                        raise ValueError('Client payload too large')
                    chunks.append(chunk)
                raw = b''.join(chunks)
                stage = 'client_json'
                data = _json(raw)
                expected = self._dispatch_correlation
                stage = 'client_correlation'
                if not _response_correlation_matches(data, expected):
                    raise ValueError('Client correlation mismatch')
                stage = 'client_profile'
                if (data.get('stream') is not True
                        or (data.get('model'), (data.get('reasoning') or {}).get('effort')) != _PROFILES[self._dispatch_role]):
                    raise ValueError('Client scope mismatch')
                # No hosted tools, photos/audio/files, paid tier or alternate endpoint.
                from scripts.canary_gateway_binding import _text_only
                stage = 'client_modality'
                if not _text_only(data):
                    raise ValueError('Client modality unsupported')
                authorization = request.headers.get('authorization', '')
                stage = 'gateway_send'
                result = await self._http.post(self.provider_transport.endpoint, content=raw,
                    headers={'Authorization': authorization, 'Content-Type': 'application/json'})
                record.update(local_client_last_stage='gateway_response', local_client_last_status='forwarded')
                return Response(content=result.content, status_code=result.status_code,
                                media_type=result.headers.get('content-type', 'application/json'))
            except asyncio.CancelledError:
                if record is not None:
                    record.update(local_client_last_stage=stage, local_client_last_status='cancelled',
                                  local_client_last_failure_class='cancelled')
                self.run.stop('send_interrupted_or_failed')
                raise
            except Exception as error:
                if record is not None:
                    record.update(local_client_last_stage=stage, local_client_last_status='rejected',
                                  local_client_last_failure_class=failure_class(error))
                self.run.stop('send_interrupted_or_failed')
                return Response(status_code=502, content='Subscription client request stopped')

        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self._socket = sock
            sock.bind(('127.0.0.1', 0)); sock.listen(128); sock.setblocking(False)
            self._base_url = f'http://127.0.0.1:{sock.getsockname()[1]}/v1'
            config = uvicorn.Config(app, host='127.0.0.1', lifespan='off', access_log=False, log_config=None)
            self._server = uvicorn.Server(config)
            self._server_task = asyncio.create_task(self._server.serve(sockets=[sock]))
            async with asyncio.timeout(min(5, run.remaining_seconds())):
                while not self._server.started:
                    if self._server_task.done():
                        await self._server_task
                        raise RuntimeError('Owned listener did not start')
                    await asyncio.sleep(.005)
            command = [str(binary)]
            for option in _OPTIONS:
                command += ['-c', option]
            command.append('app-server')
            self._command = tuple(command)
            for role, (model, effort) in _PROFILES.items():
                worker = CodexWorker(home_root=home / 'workers' / role, command=list(command),
                    base_url=self._base_url, api_key=api_key, model=model, reasoning_effort=effort,
                    timeout=collector_timeout_seconds if role == 'collector' else WORKER_TIMEOUT)
                worker.legacy_root = None
                self._workers[role] = worker
            self.runtime = CodexRuntime(home_root=home / 'api', base_url=self._base_url,
                worker_url=self.worker_url, worker_secret='task-owned-in-process',
                worker_transport=self.worker_transport, task_publisher_enabled=False, model=_PROFILES['collector'][0])
            self.runtime.composer_model = _PROFILES['composer'][0]
            self.lane_worker = MemoryEventWorker(self.broker, worker_url=self.worker_url,
                worker_secret='task-owned-in-process', worker_transport=self.worker_transport)
            await self._start_workflows()
            _ISSUED.add(self)
            return self
        except BaseException:
            await self.close()
            raise

    async def _start_workflows(self):
        from temporalio import activity
        from temporalio.client import Client
        from temporalio.worker import Worker
        from apps.api.temporal_workflows import MemoirSkillLane
        from urllib.parse import urlsplit
        if type(self.temporal_client) is not Client:
            raise ValueError('Owned loopback Temporal client required')
        target = self.temporal_client.service_client.config.target_host
        url = urlsplit('http://' + target)
        if url.hostname != '127.0.0.1' or not url.port or url.username or url.password:
            raise ValueError('Owned loopback Temporal client required')
        @activity.defn(name='memoir.execute_lane')
        async def execute(lane_id: str):
            assert_owned_subscription_session(self)
            if self._active is None:
                raise ValueError('Background activity outside active round')
            info = activity.info()
            token = self._job_context.set({'job_id': info.workflow_run_id + ':' + info.activity_id})
            try:
                result = await self.lane_worker.execute_lane(lane_id)
                state = await self.broker.rpc('read_memoir_lane_state', p_lane_id=lane_id)
                return {'status': result['status'], 'pending': bool(state and state['pending'])}
            finally:
                self._job_context.reset(token)
        self._workflow = Worker(self.temporal_client, task_queue=self.task_queue,
            workflows=[MemoirSkillLane], activities=[execute], max_concurrent_activities=1,
            max_concurrent_activity_task_polls=1)
        await self._workflow.__aenter__()
        self._workflow_ready = True

    @property
    def case_ids(self):
        return self._profile.case_ids

    @property
    def evaluation_profile(self):
        return self._profile.name

    @property
    def selected_case_ids(self):
        return self._profile.selected_case_ids

    @property
    def case_plans(self):
        return deepcopy(self._plans)

    def worker_receipts(self):
        return deepcopy(self._worker_records)

    def worker_failure_for(self, correlation):
        """Project a bounded timeout cause from owned records, never an error.

        This is diagnostic readback only. The dispatch gate remains stopped,
        and no receipt or HTTP/browser input can authorize another worker call.
        """
        assert_owned_subscription_session(self)
        if type(correlation) is not dict:
            return None
        case, round_id = correlation.get('case_id'), correlation.get('round_id')
        if (type(case) is not str or case not in self._plans or type(round_id) is not str
                or not round_id.isascii() or not round_id.isdigit() or len(round_id) > 2):
            return None
        ordinal = int(round_id)
        if not 1 <= ordinal <= self._profile.rounds:
            return None
        expected = self.bridge_for_case(case).before_round(case, ordinal)
        if {k: v for k, v in correlation.items() if k not in ('job_id', 'checkpoint_id')} != expected:
            return None
        for record in reversed(self._worker_records[-16:]):
            if (type(record) is not dict
                    or record.get('case_id') != case or type(record.get('round')) is not int
                    or record['round'] != ordinal or type(record.get('role')) is not str
                    or record['role'] not in _PROFILES
                    or record.get('status') != 'failed' or record.get('failure_stage') != 'worker_turn'
                    or record.get('failure_class') != 'timeout'):
                continue
            context = next((ctx for ctx in self._worker_diagnostic_contexts
                if ctx[0] is record), None)
            if context is None or context[2] != record['role']:
                continue
            authorized = context[1]
            extras = ({'job_id', 'checkpoint_id'} if record['role'] == 'composer' else
                {'job_id'} if record['role'] == 'author_timeline' else set())
            if (set(authorized) != set(expected) | extras
                    or any(authorized.get(k) != v for k, v in expected.items())
                    or record.get('correlation') != authorized
                    or correlation != expected and correlation != authorized):
                continue
            if extras and (type(authorized.get('job_id')) is not str
                    or not re.fullmatch(r'[A-Za-z0-9_.:-]{1,256}', authorized['job_id'])):
                continue
            if record['role'] == 'composer' and (ordinal not in self._profile.checkpoints
                    or authorized.get('checkpoint_id') != f'{case}:{ordinal}'):
                continue
            origin = record.get('timeout_origin', 'unknown_timeout')
            expired = record.get('worker_deadline_expired', False)
            if (type(origin) is not str or origin not in
                    {'worker_execution_deadline', 'transport_timeout', 'unknown_timeout'}
                    or type(expired) is not bool or expired != (origin == 'worker_execution_deadline')):
                continue
            seconds, elapsed = record.get('execution_timeout_seconds'), record.get('elapsed_ms')
            counts = [record.get(key) for key in ('client_requests_before', 'client_requests_after',
                'completed_responses_before', 'completed_responses_after')]
            if (type(seconds) not in (int, float) or not .001 <= seconds <= 600 or not math.isfinite(seconds)
                    or type(elapsed) is not int or not 0 <= elapsed < 2**53
                    or any(type(n) is not int or not 0 <= n < 2**53 for n in counts)):
                continue
            started, completed = counts[1] - counts[0], counts[3] - counts[2]
            if not 0 <= completed <= started:
                continue
            progress = record.get('worker_progress')
            if (len(context) == 4 and context[3] is not None and progress != context[3]
                    or progress is not None and (len(context) != 4 or progress != context[3])):
                continue
            return {'schema_version': 'memoir-worker-failure/1', 'correlation': deepcopy(authorized),
                'role': record['role'], 'failure_class': 'timeout',
                'timeout_origin': origin, 'worker_deadline_expired': expired,
                'execution_timeout_seconds': seconds, 'elapsed_ms': elapsed,
                'request_accounting': {'started': started, 'completed': completed,
                    'unresolved': started - completed},
                **({'worker_progress':deepcopy(progress)} if progress is not None else {})}
        return None

    def bridge_for_case(self, case_id):
        return self._profile.bridge(case_id=case_id, run_id=self.run.run_id,
            project_id=self._plans[case_id]['project_id'], source_revision=self.run.source_revision)

    def storage_for_case(self, case_id):
        assert_owned_subscription_session(self)
        return self._storages[case_id]

    def activate_round(self, case_id, ordinal):
        assert_owned_subscription_session(self)
        if (self._active is not None or self._pending or type(ordinal) is not int
                or case_id not in self.case_ids or ordinal != self._finished[case_id] + 1
                or ordinal > self._profile.rounds):
            self.run.stop('protocol_invalid')
            raise ValueError('Subscription round sequence mismatch')
        index = self.case_ids.index(case_id)
        if any(self._finished[prior] != self._profile.rounds for prior in self.case_ids[:index]):
            self.run.stop('protocol_invalid')
            raise ValueError('Earlier cases must finish before the next case')
        if self._profile.name == 'subscription_fifty' and ordinal == 1:
            self.run.start_case(case_id)
        if self._profile.name == 'subscription_fifty':
            # Mutate only the already verified disposable HTTP facade. No
            # payment service or database entitlement row is involved.
            self._entitlement_facades[case_id].entitlement = self._profile.entitlement(self._plans[case_id], ordinal)
        self._active = (case_id, ordinal)
        return self.bridge_for_case(case_id).before_round(case_id, ordinal)

    def finish_round(self):
        assert_owned_subscription_session(self)
        if self._active is None or self._pending:
            raise ValueError('Owned worker calls have not settled')
        self._finished[self._active[0]] = self._active[1]
        self._active = None

    def finish_case(self, case_id):
        assert_owned_subscription_session(self)
        if self._active is not None or self._pending or self._finished.get(case_id) != self._profile.rounds:
            self.run.stop('protocol_invalid')
            raise ValueError('Case must finish all rounds and readbacks')
        if self._profile.name == 'subscription_fifty':
            self.run.finish_case(case_id)

    async def close(self):
        if getattr(self, '_closed', True):
            return
        self._closed = True
        try:
            self.run.stop('closed')
        except Exception:
            # A failed journal must not strand task-owned processes/listeners.
            pass
        pending = [task for task in self._pending if task is not asyncio.current_task()]
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        cleanup_failed = False
        if self.browser_readback is not None:
            try:
                await self.browser_readback.close()
            except BaseException:
                cleanup_failed = True
        if self.photo_research is not None:
            try:
                await self.photo_research.close()
            except BaseException:
                cleanup_failed = True
        if self._workflow is not None:
            try:
                await self._workflow.__aexit__(None, None, None)
            except BaseException:
                cleanup_failed = True
        self._workflow_ready = False
        if self._server is not None:
            self._server.should_exit = True
        if self._server_task is not None:
            try:
                async with asyncio.timeout(5):
                    await asyncio.shield(self._server_task)
            except BaseException:
                self._server_task.cancel()
                await asyncio.gather(self._server_task, return_exceptions=True)
                cleanup_failed = True
        if self._socket is not None:
            self._socket.close()
        for client in (self._http, self.broker.client):
            try:
                await client.aclose()
            except BaseException:
                cleanup_failed = True
        for storage in self._storages.values():
            try:
                storage.client.close()
            except BaseException:
                cleanup_failed = True
        try:
            self.run.close()
        finally:
            _ISSUED.discard(self)
        if cleanup_failed:
            raise RuntimeError('Owned session cleanup incomplete') from None
