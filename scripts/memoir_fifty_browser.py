"""Task-owned real-handler API for the original fifty-round campaign.

Import and build are offline. Only explicit start() opens an owned ephemeral
127.0.0.1 listener. There is no production auth bypass, shared-global patch,
provider route, frontend install, browser execution, or replayed response.
Content handlers are the production functions; synthetic authentication and
entitlements remain the already-owned PostgresRest boundaries. A native browser
producer must supply its own verified screenshots/receipts. Explicit optional
one-shot turns retain the real runtime result behind the existing shared model
gate; this API alone never establishes browser execution or E2E acceptance.
"""
from __future__ import annotations

import asyncio
from copy import deepcopy
from contextvars import ContextVar
import hmac
import json
from pathlib import Path
from uuid import UUID
import weakref
import re
import socket
from types import CellType, FunctionType

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

_READ_TABLES = frozenset({'user_profile', 'user_memory', 'user_recall_usage',
    'user_completed_round', 'user_place_journey', 'user_family_context',
    'user_memoir_project', 'user_narrator_source', 'story_entitlements'})
_READ_RPCS = frozenset({'read_user_memory_events', 'read_user_memoir_draft', 'read_user_interview_turn'})
_AGENT_READS = frozenset({'/v1/agent/profile', '/v1/agent/place-journey',
    '/v1/agent/family-context', '/v1/agent/turns/{client_turn_id}'})
_USER_READS = frozenset({'/v1/user/projects', '/v1/user/projects/{project_id}/history',
    '/v1/user/projects/{project_id}/sources/{source_id}', '/v1/user/profile'})
_PROJECT_READS = frozenset({'/v1/projects/{project_id}', '/v1/projects/{project_id}/journey',
    *('/v1/projects/{project_id}/' + name for name in ('memories', 'sources', 'chapters', 'people', 'relationships', 'timeline'))})
_STORY_READS = frozenset({'/v1/story/state', '/v1/story/readiness',
    '/v1/story/private-draft', '/v1/story/events'})


def _assert_session(session):
    from scripts.issue14_subscription_session import assert_owned_subscription_session
    assert_owned_subscription_session(session)
    if session.evaluation_profile != 'subscription_fifty':
        raise ValueError('An issued fifty-round session is required')


def _function(function, globals_map, cells=None):
    closure = function.__closure__
    if cells and closure:
        closure = tuple(CellType(cells[name]) if name in cells else cell
            for name, cell in zip(function.__code__.co_freevars, closure))
    result = FunctionType(function.__code__, globals_map,
        function.__name__, function.__defaults__, closure)
    result.__kwdefaults__ = function.__kwdefaults__
    result.__annotations__ = function.__annotations__
    result.__module__ = function.__module__
    result.__doc__ = function.__doc__
    return result


def _bind(function, **changes):
    """Bind the same reviewed handler code without changing module globals."""
    return _function(function, {**function.__globals__, **changes})


def _public_turn(value):
    """Exclude diagnostic protocol/analysis fields added only for evaluation."""
    denied = {'trajectory', 'protocol', 'private_protocol', 'protocol_steps', 'reasoning',
              'hidden_reasoning', 'analysis', 'evaluation_context'}
    if isinstance(value, dict):
        return {key: _public_turn(item) for key, item in value.items()
                if key.lower() not in denied and not key.startswith('_')}
    if isinstance(value, list):
        return [_public_turn(item) for item in value]
    return value


class _ArmedRuntime:
    def __init__(self, api, case):
        self.api, self.case = api, case

    async def turn(self, storage, text, **options):
        api = self.api
        arm = api._armed
        api._check()
        if (not arm or arm['case_id'] != self.case or arm['state'] != 'accepted'
                or api._turn_storages.get(storage) is not arm
                or options.get('client_turn_id') != arm['client_turn_id']
                or options.get('project_id') != arm['project_id']
                or options.get('language') != arm['language']
                or text not in arm['allowed_texts']
                or options.get('conversation_text', text) != arm['text']
                or options.get('source_kind', 'narrator_chat') != 'narrator_chat'
                or api._session._active != (self.case, arm['ordinal'])):
            raise HTTPException(409, 'No matching owned browser turn')
        arm['state'] = 'running'
        task = asyncio.current_task()
        api._running_turns.add(task)
        try:
            # Evaluation correlation is taken only from the owned original-data
            # bridge, never an HTTP field or the browser's claimed ordinal.
            api._runtime_invocations += 1
            value = await api._runtime.turn(storage, text, **options,
                include_trajectory=True, evaluation=deepcopy(arm['correlation']))
            arm['state'] = 'completed'
            arm['future'].set_result({'ok': True, 'value': value})
            return _public_turn(value)
        except BaseException as error:
            arm['state'] = 'failed'
            if not arm['future'].done():
                cause = None
                try:
                    readback = getattr(api._session, 'worker_failure_for', None)
                    if callable(readback):
                        cause = readback(arm['correlation'])
                except Exception:
                    pass
                arm['future'].set_result({'ok': False, 'worker_failure': cause})
            if isinstance(error, asyncio.CancelledError):
                raise
            # The production JSON handler formats RuntimeError text; never let
            # a provider exception or its trajectory reach that boundary.
            raise RuntimeError('Owned browser turn failed') from None
        finally:
            api._running_turns.discard(task)


class _Entitlements:
    def __init__(self, api, case):
        self.api, self.case = api, case

    def get(self, owner):
        self.api._check()
        if owner != self.api._plans[self.case]['owner_id']:
            raise ValueError('Synthetic owner mismatch')
        return deepcopy(self.api._facades[self.case].entitlement)


class OwnedBrowserTurnFailed(ValueError):
    """Generic browser failure with a private, owned diagnostic sidecar."""
    def __init__(self, worker_failure=None):
        super().__init__('Owned browser turn failed')
        self.worker_failure = deepcopy(worker_failure)


class OwnedFiftyBrowserAPI:
    """Own one default-read-only listener and five disjoint synthetic case routes."""
    def __init__(self):
        raise TypeError('Use build() or await create() with an issued session')

    @classmethod
    def build(cls, session):
        _assert_session(session)
        from memoir_postgres_workflow import PostgresRest
        from scripts.memoir_fifty_readback import case_plans_for_run
        from apps.api.agent_storage import UserStorage
        plans = session.case_plans
        if (plans != case_plans_for_run(session.run.run_id)
                or tuple(plans) != tuple(session.case_ids)
                or set(session._entitlement_facades) != set(plans)):
            raise ValueError('Exact synthetic fifty-case binding required')
        for case, plan in plans.items():
            facade, storage = session._entitlement_facades[case], session._storages[case]
            if (type(facade) is not PostgresRest or facade.owner != plan['owner_id']
                    or facade.service is not False or type(storage) is not UserStorage
                    or storage.url != 'http://synthetic.invalid' or storage.user_id != facade.owner
                    or type(storage.client._transport) is not httpx.MockTransport
                    or getattr(storage.client._transport.handler, '__self__', None) is not facade):
                raise ValueError('Exact owner-scoped PostgresRest facade required')
        self = object.__new__(cls)
        self._session, self._plans = session, deepcopy(plans)
        self._facades = dict(session._entitlement_facades)
        self._run_id, self._revision = session.run.run_id, session.run.source_revision
        self._closed = False
        self._server = self._task = self._socket = self._origin = None
        self._requests, self._bindings = [], []
        self._adapters, self._main_globals = {}, {}
        self._turns_enabled, self._armed, self._runtime = False, None, None
        self._runtime_invocations = 0
        self._armed_keys, self._client_turn_ids, self._running_turns = set(), set(), set()
        self._turn_storages = weakref.WeakKeyDictionary()
        self.app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
        self._build_routes()
        return self

    @classmethod
    async def create(cls, session):
        self = cls.build(session)
        try:
            await self.start()
            return self
        except BaseException:
            await self.close()
            raise

    def _check(self):
        _assert_session(self._session)
        if (self._closed or self._session.run.run_id != self._run_id
                or self._session.run.source_revision != self._revision
                or self._session.case_plans != self._plans
                or self._runtime is not None and self._session.runtime is not self._runtime
                or self._session.run.remaining_seconds() <= 0
                or any(self._session._entitlement_facades.get(case) is not facade
                    or facade.owner != self._plans[case]['owner_id'] or facade.service is not False
                    or getattr(self._session._storages[case].client._transport.handler, '__self__', None) is not facade
                    for case, facade in self._facades.items())):
            raise ValueError('Owned readback binding is closed or changed')

    def _handle_read(self, case, request):
        self._check()
        plan = self._plans[case]
        url = request.url
        if (url.scheme != 'http' or url.host != 'synthetic.invalid' or url.port not in (None, 80)
                or request.headers.get('authorization') != 'Bearer ' + plan['owner_id']):
            return httpx.Response(403, json={'detail': 'Readback storage scope denied'})
        path = url.path
        allowed = request.method == 'GET' and (path == '/auth/v1/user'
            or path.removeprefix('/rest/v1/') in _READ_TABLES and path.startswith('/rest/v1/'))
        if path.startswith('/rest/v1/rpc/'):
            rpc = path.rsplit('/', 1)[-1]
            allowed = (rpc in _READ_RPCS and request.method == ('GET' if rpc == 'read_user_interview_turn' else 'POST'))
            if allowed:
                import json
                data = dict(url.params) if request.method == 'GET' else json.loads(request.content)
                allowed = data.get('p_project_id') == plan['project_id']
        for key, value in url.params.multi_items():
            if key == 'user_id' and value != 'eq.' + plan['owner_id']:
                allowed = False
            if key == 'project_id' and value.startswith('eq.') and value != 'eq.' + plan['project_id']:
                allowed = False
        if not allowed:
            return httpx.Response(403, json={'detail': 'Read-only fixture denies this storage operation'})
        response = self._facades[case].handle(request)
        # UserStorage's production read method migrates legacy caches at revision
        # zero. Stop before that branch, including any local cache inspection.
        if path == '/rest/v1/rpc/read_user_memoir_draft' and response.status_code == 200:
            if response.json().get('revision', 0) == 0:
                raise HTTPException(409, 'Saved draft not available in this read-only fixture')
        return response

    def _handle_turn_storage(self, case, arm, request):
        self._check()
        owner = self._plans[case]['owner_id']
        if (arm is not self._armed or arm['state'] not in {'accepted', 'running'}
                or self._session._active != (case, arm['ordinal'])
                or request.url.scheme != 'http' or request.url.host != 'synthetic.invalid'
                or request.url.port not in (None, 80)
                or request.headers.get('authorization') != 'Bearer ' + owner):
            raise HTTPException(403, 'Owned turn storage scope denied')
        data = json.loads(request.content) if request.content and request.headers.get('content-type', '').startswith('application/json') else {}
        if isinstance(data, dict):
            if any(data.get(key, owner) != owner for key in ('user_id', 'p_user_id', 'owner_id', 'p_owner_id')):
                raise HTTPException(403, 'Owned turn storage owner mismatch')
            if any(data.get(key, arm['project_id']) != arm['project_id'] for key in ('project_id', 'p_project_id')):
                raise HTTPException(403, 'Owned turn storage project mismatch')
        return self._facades[case].handle(request)

    def _storage_factory(self, case, *, writable=False):
        def storage(authorization):
            self._check()
            owner = self._plans[case]['owner_id']
            if not isinstance(authorization, str) or not hmac.compare_digest(authorization.encode(), ('Bearer ' + owner).encode()):
                raise HTTPException(401, 'Exact synthetic case authorization required')
            from apps.api.agent_storage import UserStorage
            arm = self._armed if writable else None
            if writable and (not arm or arm['case_id'] != case or arm['state'] != 'accepted'):
                raise HTTPException(409, 'No accepted owned browser turn')
            handler = (lambda request: self._handle_turn_storage(case, arm, request)) if writable else (lambda request: self._handle_read(case, request))
            client = httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=False, trust_env=False)
            try:
                result = UserStorage('http://synthetic.invalid', 'synthetic-public', owner, client=client)
                if writable:
                    self._turn_storages[result] = arm
                return result
            except BaseException:
                client.close()
                raise
        return storage

    def _build_routes(self):
        from apps.api import agent_routes, supabase_routes, story_routes
        from apps.api.recall import free_recall_rounds, private_draft_cadence
        from apps.api import main
        from apps.api.store import MemoryStore
        for case, plan in self._plans.items():
            prefix = '/cases/' + case
            factory = self._storage_factory(case)
            # Rebind the production main handlers and their helper call graph.
            # No module-global auth/helper/ContextVar or shared store is changed.
            memory = MemoryStore()
            principal = ContextVar('fifty_readback_principal_' + case, default=None)
            private_globals = {**vars(main), 'authenticated_storage': factory,
                               '_request_principal': principal}
            for name, function in vars(main).items():
                if isinstance(function, FunctionType) and function.__module__ == main.__name__:
                    private_globals[name] = _function(function, private_globals)
            restore = None
            for route in main.app.routes:
                if getattr(route, 'path', None) not in (_PROJECT_READS | {'/v1/projects'}):
                    continue
                if route.path == '/v1/projects' and route.methods == {'POST'}:
                    restore = _function(route.endpoint, private_globals, {'memory': memory})
                elif route.methods == {'GET'}:
                    endpoint = _function(route.endpoint, private_globals, {'memory': memory})
                    self.app.add_api_route(prefix + route.path, endpoint, methods=['GET'],
                        response_model=route.response_model, response_class=route.response_class,
                        status_code=route.status_code)
                    self._bindings.append({'case_id': case, 'path': route.path, 'method': 'GET',
                        'handler': route.endpoint.__module__ + '.' + route.endpoint.__qualname__})
            if restore is None:
                raise ValueError('Production canonical project restore handler unavailable')
            self._adapters[case] = (memory, principal, restore)
            self._main_globals[case] = private_globals
            routers = [(agent_routes.router, _AGENT_READS, {'authenticated_storage': factory}),
                (supabase_routes.router, _USER_READS, {'storage': factory}),
                (story_routes.build_router(factory, entitlement_store=_Entitlements(self, case),
                                          stripe_client=object(), speech_service=object()), _STORY_READS, {})]
            for router, paths, changes in routers:
                for route in router.routes:
                    if route.path not in paths or route.methods != {'GET'}:
                        continue
                    endpoint = _bind(route.endpoint, **changes) if changes else route.endpoint
                    self.app.add_api_route(prefix + route.path, endpoint, methods=['GET'],
                        response_model=route.response_model, response_class=route.response_class,
                        status_code=route.status_code)
                    self._bindings.append({'case_id': case, 'path': route.path, 'method': 'GET',
                        'handler': route.endpoint.__module__ + '.' + route.endpoint.__qualname__})

            def configuration():
                return {'enabled': False, 'auth_mode': 'test', 'supabase_url': None,
                    'supabase_publishable_key': None, 'google_maps_browser_api_key': None,
                    'show_thinking_steps': False, 'free_recall_rounds': free_recall_rounds(),
                    'private_draft_cadence': private_draft_cadence(),
                    'evaluation_fixture': 'owned_fifty_armed_api' if self._turns_enabled else 'owned_fifty_readback_only'}
            self.app.add_api_route(prefix + '/v1/agent/config', configuration, methods=['GET'])

        @self.app.middleware('http')
        async def guard(request: Request, call_next):
            path = request.scope['path']
            match = re.fullmatch(r'/cases/([a-z0-9-]+)(/.*)', path)
            if not match or match[1] not in self._plans:
                return JSONResponse({'detail': 'Unknown synthetic case route'}, status_code=404)
            case, route = match.groups()
            if route.startswith('/api/v1/memoir/'):
                route = '/v1/' + route[len('/api/v1/memoir/'):]
                request.scope['path'] = '/cases/' + case + route
                request.scope['raw_path'] = request.scope['path'].encode()
            if not re.fullmatch(r'127\.0\.0\.1(?::[0-9]{1,5})?', request.headers.get('host', '')):
                return JSONResponse({'detail': 'Loopback host required'}, status_code=403)
            origin = request.headers.get('origin')
            if origin and not re.fullmatch(r'http://127\.0\.0\.1(?::[0-9]{1,5})?', origin):
                return JSONResponse({'detail': 'Loopback browser origin required'}, status_code=403)
            turn_request = request.method == 'POST' and route == '/v1/agent/turn' and self._turns_enabled
            if request.method != 'GET' and not turn_request:
                return JSONResponse({'detail': 'Read-only API fixture'}, status_code=405)
            try:
                self._check()
            except (ValueError, AttributeError):
                return JSONResponse({'detail': 'Owned API fixture unavailable'}, status_code=503)
            if route != '/v1/agent/config':
                expected = 'Bearer ' + self._plans[case]['owner_id']
                if not hmac.compare_digest(request.headers.get('authorization', '').encode(), expected.encode()):
                    return JSONResponse({'detail': 'Exact synthetic case authorization required'}, status_code=401)
            projects = request.query_params.getlist('project_id')
            path_project = re.match(r'/v1/(?:user/)?projects/([^/]+)(?:/|$)', route)
            if (projects and projects != [self._plans[case]['project_id']]
                    or path_project and path_project[1] != self._plans[case]['project_id']):
                return JSONResponse({'detail': 'Exact synthetic project required'}, status_code=403)
            if turn_request:
                try:
                    from scripts.issue14_subscription_session import _json
                    raw = await request.body()
                    if len(raw) > 256 * 1024:
                        raise ValueError('Body too large')
                    self._accept_turn(case, _json(raw))
                except (ValueError, TypeError, KeyError, AttributeError):
                    return JSONResponse({'detail': 'No matching unconsumed original browser turn'}, status_code=409)
            principal = self._adapters[case][1]
            token = principal.set({'authorization': request.headers.get('authorization')})
            try:
                response = await call_next(request)
            except httpx.HTTPStatusError:
                response = JSONResponse({'detail': 'Read-only storage operation unavailable'}, status_code=503)
            finally:
                principal.reset(token)
            if turn_request and response.status_code >= 400 and self._armed and not self._armed['future'].done():
                self._armed['state'] = 'failed'
                self._armed['future'].set_result({'ok': False})
            self._requests.append({'case_id': case, 'method': request.method, 'path': route,
                                   'status_code': response.status_code})
            response.headers['X-Evaluation-Fixture'] = 'owned-fifty-armed-api' if self._turns_enabled else 'owned-fifty-readback-only'
            return response

    def enable_turns(self):
        """Explicit opt-in; no route is writable until a trusted round is armed."""
        self._check()
        if self._turns_enabled:
            raise ValueError('Owned browser turns already enabled')
        from apps.api import agent_routes
        from apps.api.store import MemoryStore
        self._runtime = self._session.runtime
        source = (Path(__file__).resolve().parents[1] / 'apps/web/client/memoir/client.js').read_text()
        profile = re.search(r'const PROFILE_INTAKE_PROMPT = `([^`]+)`;', source)
        ordinary = re.search(r'let instruction = profileIntake\s*\?\s*PROFILE_INTAKE_PROMPT\s*:\s*"([^"\n]+)";', source)
        if not profile or not ordinary:
            raise ValueError('Reviewed browser prompt grammar unavailable')
        self._wrapper_suffixes = (profile[1], ordinary[1])
        self.app.state.store = MemoryStore()
        for case in self._plans:
            def hints(store, project_id, user_id, selected=case):
                # The real route normally reaches main._project by module import.
                # Resolve that helper from this case's private binding instead.
                from apps.api.place_journey import validate_place_journey
                memory = self._adapters[selected][0]
                if project_id not in memory.projects:
                    return []
                project = self._main_globals[selected]['_project'](memory, project_id, user_id)
                history = project.get('profile', {}).get('memory_places') or []
                return [place for raw in history[-50:] if (place := validate_place_journey(raw))] if isinstance(history, list) else []
            endpoint = _bind(agent_routes.turn, authenticated_storage=self._storage_factory(case, writable=True),
                             runtime=_ArmedRuntime(self, case), _project_place_hints=hints)
            self.app.add_api_route('/cases/' + case + '/v1/agent/turn', endpoint, methods=['POST'])
            self._bindings.append({'case_id': case, 'path': '/v1/agent/turn', 'method': 'POST',
                'handler': 'apps.api.agent_routes.turn', 'admission': 'one_shot_owned_original_round'})
        self._turns_enabled = True

    def arm_turn(self, case, ordinal):
        self._check()
        key = (case, ordinal)
        if (not self._turns_enabled or type(ordinal) is not int or not 1 <= ordinal <= 50
                or case not in self._plans or self._session._active != key or key in self._armed_keys
                or self._armed and not self._armed['future'].done()):
            raise ValueError('A fresh exact active original round is required')
        bridge = self._session.bridge_for_case(case)
        text = bridge.driver_inputs()['rounds'][ordinal - 1]
        allowed = (text, *('The storyteller said: ' + text + '\n' + suffix for suffix in self._wrapper_suffixes))
        self._armed = {**self._plans[case], 'ordinal': ordinal, 'text': text, 'allowed_texts': allowed,
            'correlation': bridge.before_round(case, ordinal), 'state': 'armed', 'client_turn_id': None,
            'future': asyncio.get_running_loop().create_future()}
        self._armed_keys.add(key)
        return {key: deepcopy(self._armed[key]) for key in ('case_id', 'ordinal', 'project_id', 'language', 'text', 'allowed_texts')}

    def _accept_turn(self, case, payload):
        self._check()
        arm = self._armed
        allowed = {'text', 'conversation_text', 'source_kind', 'client_turn_id', 'project_id',
            'language', 'first_reply_localization', 'uploaded_photo_ids', 'photo_selection'}
        client_id = payload.get('client_turn_id')
        if (not arm or arm['state'] != 'armed' or arm['case_id'] != case
                or self._session._active != (case, arm['ordinal'])
                or set(payload) - allowed or payload.get('text') not in arm['allowed_texts']
                or payload.get('conversation_text', payload.get('text')) != arm['text']
                or payload.get('project_id') != arm['project_id'] or payload.get('language') != arm['language']
                or payload.get('source_kind', 'narrator_chat') != 'narrator_chat'
                or payload.get('uploaded_photo_ids', []) != [] or payload.get('photo_selection') is not None
                or type(payload.get('first_reply_localization', False)) is not bool
                or payload.get('first_reply_localization', False) and arm['ordinal'] != 1
                or type(client_id) is not str or str(UUID(client_id)) != client_id
                or client_id in self._client_turn_ids):
            raise ValueError('Unarmed or mismatched browser turn')
        # This synchronous transition consumes the only dispatch before the first
        # auth/storage await, so concurrent duplicate POSTs cannot both enter.
        arm.update(state='accepted', client_turn_id=client_id)
        self._client_turn_ids.add(client_id)

    async def wait_turn(self, case, ordinal):
        arm = self._armed
        if not arm or (arm['case_id'], arm['ordinal']) != (case, ordinal):
            raise ValueError('No matching owned browser turn')
        # Failure evidence must remain readable after the shared gate stops.
        # Completed/pending success still passes every original admission check.
        if arm['future'].done() and not arm['future'].cancelled():
            result = arm['future'].result()
            if not result['ok']:
                raise OwnedBrowserTurnFailed(result.get('worker_failure'))
        self._check()
        async with asyncio.timeout(self._session.run.remaining_seconds()):
            result = await asyncio.shield(arm['future'])
        if not result['ok']:
            raise OwnedBrowserTurnFailed(result.get('worker_failure'))
        return result['value']

    async def prepare_project(self, case):
        """Restore only an existing canonical case into a private memory adapter.

        This calls the real production restore handler without exposing its POST
        route. Only the local adapter is created; canonical data is read-only.
        No narrator text, reply, event or draft is seeded or substituted.
        """
        self._check()
        if case not in self._plans:
            raise ValueError('Unknown synthetic case')
        def restore():
            from apps.api.main import ProjectCreate
            memory, principal, function = self._adapters[case]
            if memory.persistence_path or memory.object_store_path:
                raise ValueError('Project adapter must remain task-local in memory')
            authorization = 'Bearer ' + self._plans[case]['owner_id']
            token = principal.set({'authorization': authorization})
            try:
                result = function(ProjectCreate(mode='self',
                    restore_project_id=self._plans[case]['project_id']),
                    x_account_id=None, idempotency_key=None, authorization=authorization)
            finally:
                principal.reset(token)
            if result['id'] != self._plans[case]['project_id'] or result['owner_id'] != self._plans[case]['owner_id']:
                raise ValueError('Canonical restore scope mismatch')
            return result
        return await asyncio.to_thread(restore)

    async def start(self):
        """Native owner only: bind an ephemeral loopback socket, never shared ports."""
        self._check()
        if self._task is not None:
            raise ValueError('Owned API listener already started')
        import uvicorn
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self._socket = sock
            sock.bind(('127.0.0.1', 0)); sock.listen(128); sock.setblocking(False)
            self._origin = f'http://127.0.0.1:{sock.getsockname()[1]}'
            self._server = uvicorn.Server(uvicorn.Config(self.app, host='127.0.0.1', lifespan='off',
                access_log=False, log_config=None, proxy_headers=False))
            self._task = asyncio.create_task(self._server.serve(sockets=[sock]))
            async with asyncio.timeout(min(5, self._session.run.remaining_seconds())):
                while not self._server.started:
                    if self._task.done():
                        await self._task
                        raise RuntimeError('Owned API listener failed to start')
                    await asyncio.sleep(.005)
            return self
        except BaseException:
            await self.close()
            raise

    def origin_for_case(self, case):
        self._check()
        if case not in self._plans or self._server is None or not self._server.started:
            raise ValueError('A running owned API case listener is required')
        return self._origin + '/cases/' + case

    def receipt(self):
        return {'schema_version': 'memoir-fifty-api-fixture/1', 'run_id': self._run_id,
            'source_revision': self._revision, 'scope': 'production_handlers_synthetic_auth' if self._turns_enabled else 'production_read_handlers_synthetic_auth',
            'listener_origin': self._origin, 'listener_started': bool(not self._closed and self._server
                and self._server.started and self._task and not self._task.done()),
            'closed': self._closed, 'endpoint_bindings': deepcopy(self._bindings),
            'requests': deepcopy(self._requests), 'browser_status': 'not_run',
            'project_adapters': {case: self._plans[case]['project_id'] in adapter[0].projects
                for case, adapter in self._adapters.items()}, 'turn_routes': 'armed_only' if self._turns_enabled else 'disabled',
            'turns_admitted': len(self._client_turn_ids), 'turn_dispatches': self._runtime_invocations, 'photo_routes': 'disabled', 'e2e_passed': False}

    async def close(self):
        if self._closed:
            return
        if self._armed and not self._armed['future'].done():
            self._armed['future'].set_result({'ok': False})
        running = [task for task in self._running_turns if task is not asyncio.current_task()]
        for task in running:
            task.cancel()
        if running:
            await asyncio.gather(*running, return_exceptions=True)
        self._closed = True
        if self._server is not None:
            self._server.should_exit = True
        if self._task is not None:
            try:
                async with asyncio.timeout(10):
                    await asyncio.shield(self._task)
            except BaseException:
                self._task.cancel()
                await asyncio.gather(self._task, return_exceptions=True)
                raise
            finally:
                if self._socket is not None:
                    self._socket.close()
        elif self._socket is not None:
            self._socket.close()
