"""Rollback and mixed-version worker admission, without live providers/DSNs."""
import asyncio
from contextlib import asynccontextmanager
from copy import deepcopy
import json
from types import SimpleNamespace
from uuid import UUID

import pytest

from apps.api.codex_worker_service import CodexWorker, WorkerTurnInput
from apps.api.lifetime_memory_publication import PublicationUnavailable


@pytest.fixture(autouse=True)
def isolate(monkeypatch):
    for name in ('MEMOIR_PUBLICATION_DATABASE_URL','MEMOIR_LEGACY_ONLY_DEPLOYMENT',
                 'MEMOIR_LIFETIME_MEMORY','MEMOIR_LIFETIME_GENERATION_PAUSED'):
        monkeypatch.delenv(name,raising=False)
    monkeypatch.setenv('MEMORY_SPARK_DISABLE_PRIVDROP','1')


def legacy(role='collector'):
    return WorkerTurnInput(user_id=UUID(int=4),project_id='project',agent_role=role,text='Synthetic original')


def test_legacy_worker_missing_authority_fails_closed_before_home_or_provider(tmp_path,monkeypatch):
    worker=CodexWorker(home_root=tmp_path)
    async def never_probe():pytest.fail('provider preflight before identity authority')
    monkeypatch.setattr(worker,'_ensure_composer_provider',never_probe)
    monkeypatch.setattr(worker,'_home',lambda *args:pytest.fail('legacy home opened without authority'))
    with pytest.raises(PublicationUnavailable):asyncio.run(worker.turn(legacy('composer')))


def fake_database(monkeypatch, *, mapped=False, missing=False):
    import psycopg
    calls=[];closed=[]
    class Database:
        @staticmethod
        async def connect(dsn,**kwargs):
            assert dsn=='synthetic-only';return Database()
        async def execute(self,statement,args=None):
            calls.append((statement,args))
            if missing and 'lock_lifetime_legacy_worker_admission' in statement:
                raise psycopg.errors.UndefinedFunction('synthetic missing migration')
            async def fetchone():return (not mapped,)
            return SimpleNamespace(fetchone=fetchone)
        async def rollback(self):pass
        async def close(self):closed.append(True)
    monkeypatch.setattr(psycopg,'AsyncConnection',Database)
    return calls,closed


@pytest.mark.parametrize('enabled',['true','false'])
def test_mapped_owner_raw_legacy_worker_request_rejected_even_if_legacy_only(tmp_path,monkeypatch,enabled):
    monkeypatch.setenv('MEMOIR_PUBLICATION_DATABASE_URL','synthetic-only')
    monkeypatch.setenv('MEMOIR_LEGACY_ONLY_DEPLOYMENT','true')
    monkeypatch.setenv('MEMOIR_LIFETIME_MEMORY',enabled)
    calls,closed=fake_database(monkeypatch,mapped=True)
    worker=CodexWorker(home_root=tmp_path)
    monkeypatch.setattr(worker,'_home',lambda *args:pytest.fail('mapped legacy home opened'))
    with pytest.raises(PublicationUnavailable):asyncio.run(worker.turn(legacy()))
    assert calls[1][1]==(str(UUID(int=4)),) and closed==[True]
    assert calls[-1][0]=='select public.lock_lifetime_legacy_worker_admission()'


def test_legacy_only_mode_cannot_override_broken_authoritative_lookup(tmp_path,monkeypatch):
    monkeypatch.setenv('MEMOIR_PUBLICATION_DATABASE_URL','synthetic-only')
    monkeypatch.setenv('MEMOIR_LEGACY_ONLY_DEPLOYMENT','true')
    calls,closed=fake_database(monkeypatch,missing=True)
    with pytest.raises(PublicationUnavailable):asyncio.run(CodexWorker(home_root=tmp_path).turn(legacy()))
    assert closed==[True]


@pytest.mark.parametrize('role',['collector','composer','author_timeline','organiser','workspace','memory_context'])
def test_no_raw_role_can_skip_identity_authority(tmp_path,role):
    with pytest.raises(PublicationUnavailable):asyncio.run(CodexWorker(home_root=tmp_path).turn(legacy(role)))


@pytest.mark.parametrize('kind',['collector','lane','job'])
def test_direct_governed_worker_dispatch_disabled_by_rollout(tmp_path,kind):
    from apps.api.lifetime_memory_lane_engine import LaneGenerationPaused
    if kind=='collector':
        from test_lifetime_memory_engine import fixture
        governed,context=fixture()
        payload=WorkerTurnInput(user_id=governed.fence.identity.owner_id,
            project_id=governed.fence.identity.project_id,agent_role='collector',governed=governed,
            interview_context=context,model=governed.budget.model)
    elif kind=='lane':
        from test_lifetime_memory_lane_engine import transport
        bounded=transport()
        payload=WorkerTurnInput(user_id=bounded.fence.user_id,project_id=bounded.fence.project_id,
            agent_role='author_timeline',bounded_lane=bounded,model=bounded.budget.model)
    else:
        from test_lifetime_memory_job_engine import transport
        bounded=transport()
        payload=WorkerTurnInput(user_id=bounded.fence.user_id,project_id=bounded.fence.project_id,
            agent_role='organiser',bounded_job=bounded,model=bounded.budget.model)
    with pytest.raises(LaneGenerationPaused):asyncio.run(CodexWorker(home_root=tmp_path).turn(payload))
    assert not list(tmp_path.glob('governed-*')) and not list(tmp_path.glob('lane-*')) and not list(tmp_path.glob('job-*'))


def test_explicit_legacy_only_mode_is_separate_from_disabled_rollout(monkeypatch):
    from apps.api.lifetime_memory_legacy import LegacyPublication
    async def scenario():
        publisher=LegacyPublication(None,authenticated_owner=UUID(int=4))
        with pytest.raises(PublicationUnavailable):
            async with publisher.guard():pytest.fail('absence of rollout is not identity authority')
        monkeypatch.setenv('MEMOIR_LEGACY_ONLY_DEPLOYMENT','true')
        async with publisher.guard():pass
        monkeypatch.setenv('MEMOIR_LIFETIME_MEMORY','true')
        with pytest.raises(PublicationUnavailable):
            async with publisher.guard():pytest.fail('conflicting canonical adoption allowed')
    asyncio.run(scenario())


@pytest.mark.parametrize('accept',['application/json','application/x-ndjson'])
def test_old_shape_http_request_cannot_assert_unmapped_owner(tmp_path,monkeypatch,accept):
    from fastapi.testclient import TestClient
    import apps.api.codex_worker_service as module
    monkeypatch.setenv('MEMOIR_PUBLICATION_DATABASE_URL','synthetic-only')
    monkeypatch.setenv('MEMORY_SPARK_CODEX_WORKER_SECRET','synthetic')
    fake_database(monkeypatch,mapped=True)
    monkeypatch.setattr(module,'worker',CodexWorker(home_root=tmp_path))
    with TestClient(module.app) as client:
        response=client.post('/internal/codex/turn',headers={
            'X-Codex-Worker-Secret':'synthetic','Accept':accept},json={
                **legacy().model_dump(mode='json'),'project_id':'other-project','lifetime_mapped':False})
    assert response.status_code==409
    assert response.headers['X-Error-Code']=='LIFETIME_GOVERNED_REQUEST_REQUIRED'


class Cohort:
    def __init__(self):self.lock=asyncio.Lock();self.mapped=False;self.active=False
    @asynccontextmanager
    async def guard(self):
        from apps.api.lifetime_memory_legacy import LegacyMappingConflict
        async with self.lock:
            if self.mapped:raise LegacyMappingConflict('mapped')
            self.active=True
            try:yield
            finally:self.active=False


def test_queued_legacy_json_is_rejected_after_adoption():
    from apps.api.lifetime_memory_legacy import LegacyJSONResponse,LegacyMappingConflict
    async def scenario():
        publisher=Cohort();response=LegacyJSONResponse({'reply':'private'},publisher=publisher)
        publisher.mapped=True;sent=[]
        async def send(message):sent.append(message)
        async def receive():return {'type':'http.request'}
        with pytest.raises(LegacyMappingConflict):await response({'type':'http'},receive,send)
        assert not any(message['type']=='http.response.body' for message in sent)
    asyncio.run(scenario())


def test_dequeued_legacy_stream_body_is_rejected_after_adoption():
    from apps.api.lifetime_memory_legacy import LegacyStreamingResponse,LegacyMappingConflict
    async def scenario():
        publisher=Cohort();sent=[]
        async def chunks():
            publisher.mapped=True
            yield b'private queued delta'
        async def send(message):sent.append(message)
        async def receive():return {'type':'http.request'}
        response=LegacyStreamingResponse(chunks(),publisher=publisher)
        with pytest.raises(LegacyMappingConflict):
            await response({'type':'http','asgi':{'spec_version':'2.4'}},receive,send)
        assert not any(message['type']=='http.response.body' for message in sent)
    asyncio.run(scenario())


def test_legacy_json_actual_send_serializes_with_adoption():
    from apps.api.lifetime_memory_legacy import LegacyJSONResponse
    async def scenario():
        publisher=Cohort();sending=asyncio.Event();release=asyncio.Event();adopted=asyncio.Event()
        async def send(message):
            if message['type']=='http.response.body':
                assert publisher.active;sending.set();await release.wait()
        async def receive():return {'type':'http.request'}
        task=asyncio.create_task(LegacyJSONResponse({'reply':'private'},publisher=publisher)({'type':'http'},receive,send))
        await sending.wait()
        async def adopt():
            async with publisher.lock:publisher.mapped=True;adopted.set()
        adoption=asyncio.create_task(adopt());await asyncio.sleep(0)
        assert not adopted.is_set()
        release.set();await task;await adoption
        assert adopted.is_set() and not publisher.active
    asyncio.run(scenario())


@pytest.mark.parametrize('method',['thread/start','thread/resume','turn/start'])
def test_legacy_pipe_admission_rejects_adopted_owner_before_actual_write(tmp_path,method):
    from apps.api.codex_agent import CodexConnection
    from apps.api.lifetime_memory_legacy import LegacyMappingConflict
    async def scenario():
        publisher=Cohort();publisher.mapped=True;writes=[]
        async def drain():pytest.fail('adopted request drained')
        connection=CodexConnection(['fake'],tmp_path,request_admission=publisher.guard)
        connection.process=SimpleNamespace(stdin=SimpleNamespace(write=writes.append,drain=drain))
        with pytest.raises(LegacyMappingConflict):await connection.send({'method':method,'params':{'text':'private'}})
        assert writes==[]
    asyncio.run(scenario())


def test_legacy_database_send_timeout_closes_authority_lock(monkeypatch):
    from apps.api.lifetime_memory_legacy import LegacyPublication
    calls,closed=fake_database(monkeypatch)
    async def scenario():
        publisher=LegacyPublication('synthetic-only',authenticated_owner=UUID(int=4),send_timeout=.01)
        with pytest.raises(TimeoutError):
            async with publisher.guard():await asyncio.Event().wait()
        assert closed==[True]
    asyncio.run(scenario())


def test_legacy_publication_allows_database_connect_beyond_two_seconds(monkeypatch):
    import psycopg
    from apps.api.lifetime_memory_legacy import LegacyPublication
    calls, closed = fake_database(monkeypatch)
    connect = psycopg.AsyncConnection.connect
    async def slow_connect(*args, **kwargs):
        await asyncio.sleep(2.05)
        return await connect(*args, **kwargs)
    monkeypatch.setattr(psycopg.AsyncConnection, 'connect', slow_connect)
    async def scenario():
        publisher = LegacyPublication('synthetic-only', authenticated_owner=UUID(int=4))
        async with publisher.guard():
            assert calls[-1][0] == 'select public.lock_lifetime_legacy_worker_admission()'
        assert closed == [True]
    asyncio.run(scenario())


@pytest.mark.parametrize('adopt_after_first', [False, True])
def test_stream_reuses_connection_but_rechecks_adoption_for_every_body(monkeypatch, adopt_after_first):
    import psycopg
    from apps.api.lifetime_memory_legacy import LegacyPublication, LegacyStreamingResponse, LegacyMappingConflict
    database = SimpleNamespace(active=False, mapped=False, connects=0, checks=0, rollbacks=0, closes=0)
    class Connection:
        @staticmethod
        async def connect(*args, **kwargs):
            database.connects += 1
            assert database.connects == 1, 'A reply must not open a connection for every chunk'
            return Connection()
        async def execute(self, statement, args=None):
            if 'lock_lifetime_legacy_worker_admission' in statement:
                database.checks += 1
                database.active = True
            async def fetchone(): return (not database.mapped,)
            return SimpleNamespace(fetchone=fetchone)
        async def rollback(self):
            database.rollbacks += 1
            database.active = False
        async def close(self):
            database.closes += 1
            database.active = False
    monkeypatch.setattr(psycopg, 'AsyncConnection', Connection)
    async def scenario():
        sent = []
        async def chunks():
            for i in range(40):
                assert not database.active, 'Generation must not hold the adoption lock'
                if i == 1 and adopt_after_first:
                    database.mapped = True
                yield str(i).encode()
        async def send(message):
            if message['type'] == 'http.response.body':
                assert database.active
                sent.append(message['body'])
        async def receive(): return {'type': 'http.request'}
        response = LegacyStreamingResponse(chunks(), publisher=LegacyPublication(
            'synthetic-only', authenticated_owner=UUID(int=4)))
        call = response({'type': 'http', 'asgi': {'spec_version': '2.4'}}, receive, send)
        if adopt_after_first:
            with pytest.raises(LegacyMappingConflict): await call
            assert sent == [b'0'] and database.checks == 2
        else:
            await call
            assert len(sent) == 41 and database.checks == 41
        assert database.rollbacks == database.checks
        assert database.connects == database.closes == 1 and not database.active
    asyncio.run(scenario())


def test_legacy_owner_cannot_be_relabelled_after_body_is_built():
    from apps.api.lifetime_memory_legacy import LegacyPublication
    publisher=LegacyPublication('synthetic-only',authenticated_owner=UUID(int=4))
    with pytest.raises(AttributeError):publisher.owner=UUID(int=99)
    with pytest.raises(AttributeError):publisher._owner=UUID(int=99)
    assert 'synthetic-only' not in repr(publisher)


def test_error_trajectory_body_cannot_bypass_post_adoption_publication(monkeypatch):
    from fastapi.testclient import TestClient
    import apps.api.codex_worker_service as module
    cohort=Cohort()
    async def fail(*args,**kwargs):
        cohort.mapped=True
        raise module.WorkerTurnError('generic failure',{'private':'old-owner-transcript'})
    monkeypatch.setenv('MEMORY_SPARK_CODEX_WORKER_SECRET','synthetic')
    monkeypatch.setattr(module,'_legacy_publication',lambda payload:cohort)
    monkeypatch.setattr(module,'worker',SimpleNamespace(turn=fail))
    with TestClient(module.app,raise_server_exceptions=False) as client:
        response=client.post('/internal/codex/turn',headers={'X-Codex-Worker-Secret':'synthetic'},
            json=legacy().model_dump(mode='json'))
    assert cohort.mapped and 'old-owner-transcript' not in response.text


@pytest.mark.parametrize('mode',['in_process','worker'])
def test_runtime_legacy_adoption_before_actual_admission_blocks_both_modes(tmp_path,monkeypatch,mode):
    import httpx
    import apps.api.codex_runtime as module
    from apps.api.codex_agent import CodexConnection
    from apps.api.lifetime_memory_legacy import LegacyMappingConflict
    cohort=Cohort();writes=[]
    monkeypatch.setattr(module,'LegacyPublication',lambda *args,**kwargs:cohort,raising=False)
    class Connection(CodexConnection):
        async def __aenter__(self):
            cohort.mapped=True
            async def drain():pass
            self.process=SimpleNamespace(stdin=SimpleNamespace(write=writes.append,drain=drain))
            return self
        async def __aexit__(self,*args):pass
        async def request(self,method,params):
            await self.send({'method':method,'params':params})
            return {'thread':{'id':'test'}}
        async def turn(self,*args,**kwargs):
            return '{"preferred_language":"en-AU"}'
    class Transport(httpx.AsyncBaseTransport):
        async def handle_async_request(self,request):
            cohort.mapped=True
            writes.append(await request.aread())
            return httpx.Response(200,json={'thread_id':'test','reply':'{"preferred_language":"en-AU"}','artifacts':[]})
    monkeypatch.setattr(module,'CodexConnection',Connection)
    runtime=module.CodexRuntime(home_root=tmp_path,worker_url='http://controlled.invalid' if mode=='worker' else None,
        worker_secret='synthetic',worker_transport=Transport())
    with pytest.raises(LegacyMappingConflict):
        asyncio.run(runtime._resolve_language(str(UUID(int=4)),'Synthetic original','en-AU'))
    assert writes==[]


@pytest.mark.parametrize('endpoint',['worker','store'])
def test_legacy_task_ingress_rejects_mapped_owner_before_snapshot_store(monkeypatch,endpoint):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    import apps.api.codex_worker_service as worker_module
    import apps.api.internal_tasks as store_module
    monkeypatch.setenv('MEMOIR_PUBLICATION_DATABASE_URL','synthetic-only')
    monkeypatch.setenv('MEMORY_SPARK_CODEX_WORKER_SECRET','synthetic')
    monkeypatch.setenv('MEMORY_SPARK_TASK_STORE_URL','http://controlled.invalid')
    fake_database(monkeypatch,mapped=True)
    monkeypatch.setattr(store_module,'configured_queue',lambda:pytest.fail('mapped snapshot reached store'))
    app=worker_module.app if endpoint=='worker' else FastAPI()
    if endpoint=='store':app.include_router(store_module.router)
    with TestClient(app) as client:
        response=client.post('/internal/tasks',headers={'X-Codex-Worker-Secret':'synthetic'},json={
            'user_id':str(UUID(int=4)),'project_id':'project','task':{
                'kind':'BuildFreePreview','sources':[{'id':'source','content':'Synthetic original'}]}})
    assert response.status_code==409
    assert response.headers['X-Error-Code']=='LIFETIME_GOVERNED_REQUEST_REQUIRED'


def test_legacy_request_body_guard_lasts_through_transport_consumption_and_closes():
    from apps.api.lifetime_memory_legacy import LegacyRequestBody
    async def scenario():
        cohort=Cohort();original=bytearray(b'private');body=LegacyRequestBody(original,publisher=cohort)
        original[:]=b'changed';iterator=body.__aiter__()
        assert await anext(iterator)==b'private' and cohort.active
        await body.aclose()
        assert not cohort.active
        with pytest.raises(RuntimeError):body.__aiter__()
    asyncio.run(scenario())


def test_locked_sqlite_ingress_releases_guard_without_late_enqueue(tmp_path,monkeypatch):
    import sqlite3
    from fastapi import HTTPException
    import apps.api.internal_tasks as module
    from apps.api.task_queue import TaskQueue
    from apps.api.memoir_tasks import PublishTaskInput
    path=tmp_path/'tasks.sqlite';queue=TaskQueue(path);lock=sqlite3.connect(path)
    lock.execute('BEGIN IMMEDIATE')
    cohort=Cohort()
    monkeypatch.setenv('MEMORY_SPARK_CODEX_WORKER_SECRET','synthetic')
    monkeypatch.setenv('MEMORY_SPARK_TASK_DB',str(path))
    monkeypatch.setattr(module,'LegacyPublication',lambda *args,**kwargs:cohort)
    payload=PublishTaskInput(user_id=UUID(int=4),project_id='project',task={
        'kind':'BuildFreePreview','sources':[{'id':'source','content':'Synthetic original'}]})
    async def scenario():
        with pytest.raises(HTTPException) as caught:await module.persist_task(payload,'synthetic')
        assert caught.value.status_code==503 and not cohort.active
        lock.rollback();lock.close()
        # No off-thread operation can wake up and submit after authority release.
        await asyncio.sleep(.05)
        with queue._connect() as db:assert db.execute('SELECT count(*) FROM tasks').fetchone()[0]==0
    try:asyncio.run(scenario())
    finally:lock.close()


def test_sqlite_ingress_commit_finishes_inside_adoption_guard(tmp_path,monkeypatch):
    import apps.api.internal_tasks as module
    from apps.api.task_queue import TaskQueue
    from apps.api.memoir_tasks import PublishTaskInput
    queue=TaskQueue(tmp_path/'tasks.sqlite');cohort=Cohort();submit=queue.submit
    def guarded_submit(*args):
        assert cohort.active
        result=submit(*args)
        assert cohort.active
        return result
    monkeypatch.setenv('MEMORY_SPARK_CODEX_WORKER_SECRET','synthetic')
    monkeypatch.setattr(module,'LegacyPublication',lambda *args,**kwargs:cohort)
    monkeypatch.setattr(module,'configured_queue',lambda **kwargs:queue)
    monkeypatch.setattr(queue,'submit',guarded_submit)
    payload=PublishTaskInput(user_id=UUID(int=4),project_id='project',task={
        'kind':'BuildFreePreview','sources':[{'id':'source','content':'Synthetic original'}]})
    response=asyncio.run(module.persist_task(payload,'synthetic'))
    assert response.status_code==202 and not cohort.active
    with queue._connect() as db:assert db.execute('SELECT count(*) FROM tasks').fetchone()[0]==1


@pytest.mark.parametrize('adopt_during_execution',[False,True])
def test_queued_legacy_task_cannot_publish_after_adoption(tmp_path,monkeypatch,adopt_during_execution):
    from temporalio.exceptions import ApplicationError
    from scripts import task_runtime as module
    from apps.api.task_queue import TaskQueue
    from apps.api.memoir_tasks import MemoirTask
    queue=TaskQueue(tmp_path/'tasks.sqlite');owner=str(UUID(int=4));cohort=Cohort();calls=[]
    entry=queue.submit(owner,'project',MemoirTask(kind='BuildSourceExport',
        sources=[{'id':'one','content':'Private synthetic memory'}]))
    monkeypatch.setattr(module,'configured_queue',lambda **kwargs:queue)
    def publisher(*args,authenticated_owner,**kwargs):
        assert str(authenticated_owner)==owner
        return cohort
    monkeypatch.setattr(module,'LegacyPublication',publisher,raising=False)
    def execute(task):
        calls.append(True);cohort.mapped=True
        return {'sources':[{'content':'Private synthetic memory'}]}
    monkeypatch.setattr(module,'execute_task',execute)
    cohort.mapped=not adopt_during_execution
    with pytest.raises(ApplicationError) as caught:asyncio.run(module.execute_memoir_task(entry['id']))
    assert caught.value.non_retryable and caught.value.type=='TaskRequiresGovernedWorkflow'
    assert len(calls)==int(adopt_during_execution)
    saved=queue.get(owner,entry['id'])
    assert saved['result'] is None and saved['status']=='FAILED' and not cohort.active


def test_authority_rejection_resets_original_dispatch_deadline_evidence(tmp_path,monkeypatch):
    import apps.api.codex_worker_service as module
    from apps.api.lifetime_memory_legacy import LegacyMappingConflict
    cohort=Cohort();monkeypatch.setattr(module,'_legacy_publication',lambda payload:cohort)
    worker=CodexWorker(home_root=tmp_path,timeout=.01);payload=legacy()
    async def blocked(*args,**kwargs):await asyncio.Event().wait()
    monkeypatch.setattr(worker,'_turn',blocked)
    async def scenario():
        with pytest.raises(TimeoutError):await worker.turn(payload)
        assert worker.execution_deadline_expired(payload)
        cohort.mapped=True
        with pytest.raises(LegacyMappingConflict):await worker.turn(payload)
        assert not worker.execution_deadline_expired(payload)
    asyncio.run(scenario())


def test_original_diagnostic_identity_does_not_replace_detached_execution_payload(tmp_path,monkeypatch):
    import apps.api.codex_worker_service as module
    payload=legacy();payload.profile={'name':'Original synthetic name'}
    class MutatingAdmission:
        @asynccontextmanager
        async def guard(self):
            payload.text='Changed after capture'
            payload.profile['name']='Changed after capture'
            payload.user_id=UUID(int=99)
            yield
    monkeypatch.setattr(module,'_legacy_publication',lambda value:MutatingAdmission())
    worker=CodexWorker(home_root=tmp_path,timeout=.01)
    async def blocked(snapshot,**kwargs):
        assert snapshot is not payload
        assert snapshot.user_id==UUID(int=4) and snapshot.text=='Synthetic original'
        assert snapshot.profile=={'name':'Original synthetic name'}
        assert worker.execution_progress(payload) is not None
        assert worker.execution_progress(snapshot) is None
        await asyncio.Event().wait()
    monkeypatch.setattr(worker,'_turn',blocked)
    async def scenario():
        with pytest.raises(TimeoutError):await worker.turn(payload)
        assert worker.execution_deadline_expired(payload)
        assert not worker.execution_deadline_expired(payload.model_copy())
    asyncio.run(scenario())
