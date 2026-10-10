"""Single collector scope uses synthetic storage/wire; never native/model calls."""
import asyncio
from contextlib import asynccontextmanager
from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest

from scripts import run_issue14_subscription_evaluation as launcher
from scripts import issue14_subscription_session as sessions
from scripts import issue14_subscription_transport as budget
from test_native_collector_timeout import plan as campaign_plan, resources, close_resources


def plan(**changes):
    return campaign_plan(single_collector_observation=True, **{
        'max_client_requests':4,'max_elapsed_seconds':300,
        'max_case_client_requests':4,'max_case_elapsed_seconds':300,
        'collector_timeout_seconds':180, **changes})


def test_observation_plan_is_fixed_one_collector_and_preserves_original_profile():
    value=plan()
    assert value['single_collector_observation']=={
        'case_id':value['case_ids'][0],'round':1,'dispatches':1,'allowed_roles':['collector'],
        'cleanup_seconds':60,'prior_charged':35,'prior_unresolved':2,
        'campaign_execution':False,'semantic_acceptance':False}
    assert value['collector_timeout_seconds']==180
    assert value['max_client_requests']==value['max_case_client_requests']==4
    assert value['max_elapsed_seconds']==value['max_case_elapsed_seconds']==300
    assert value['worker_deadlines']['timeout_override_inherited'] is False
    assert value['dataset_sha256']==campaign_plan()['dataset_sha256']


@pytest.mark.parametrize('change',[
    {'max_client_requests':5},{'max_client_requests':3},{'max_elapsed_seconds':301},
    {'max_elapsed_seconds':299},{'max_case_client_requests':5},
    {'max_case_elapsed_seconds':301},{'collector_timeout_seconds':120},
    {'collector_timeout_seconds':181},{'evaluation_profile':'subscription_progressive'},
    {'enable_public_photo_research':True},{'enable_browser_readback':True}])
def test_observation_scope_drift_fails_before_allocation(change,tmp_path,monkeypatch):
    monkeypatch.setattr(launcher,'native_resources',lambda *a:pytest.fail('Native allocation'))
    with pytest.raises(ValueError):plan(**change)
    assert not list(tmp_path.iterdir())


def test_plan_only_cli_selects_mode_without_credentials_or_execution(tmp_path,monkeypatch,capsys):
    p=plan()
    monkeypatch.setattr(launcher,'configured_credential',lambda:pytest.fail('Credential discovery'))
    monkeypatch.setattr(launcher,'execute_native',lambda *a:pytest.fail('Live execution'))
    argv=['--single-collector-observation','--evaluation-profile','subscription_fifty',
        '--run-id',p['run_id'],'--source-revision',p['source_revision'],'--run-dir',str(tmp_path/'run'),
        '--max-client-requests','4','--max-elapsed-seconds','300',
        '--max-case-client-requests','4','--max-case-elapsed-seconds','300',
        '--collector-timeout-seconds','180',
        '--codex-binary',p['codex_binary'],'--codex-sha256',p['codex_sha256'],
        '--temporal-binary',p['temporal_binary'],'--temporal-sha256',p['temporal_sha256']]
    assert launcher.main(argv)==0
    assert json.loads(capsys.readouterr().out)['single_collector_observation']==p['single_collector_observation']
    assert not (tmp_path/'run').exists()


@pytest.mark.parametrize('field,value',[('dispatches',2),('prior_charged',0),
    ('prior_unresolved',0),('cleanup_seconds',61),('semantic_acceptance',True),
    ('allowed_roles',['collector','workspace']),('round',2)])
def test_saved_observation_plan_tampering_cannot_allocate(tmp_path,monkeypatch,field,value):
    p=plan();p['single_collector_observation'][field]=value
    monkeypatch.setattr(launcher,'native_resources',lambda *a:pytest.fail('Native allocation'))
    with pytest.raises(ValueError,match='Exact freshly validated'):
        asyncio.run(launcher.execute_native(p,tmp_path/'run','synthetic-token'))
    assert not (tmp_path/'run').exists()


@asynccontextmanager
async def issued(tmp_path,monkeypatch):
    p=plan()
    run=budget.SubscriptionRun.create(reservation_root=tmp_path,run_id=p['run_id'],
        source_revision=p['source_revision'],limits=budget.SubscriptionLimits(4,300),
        case_ids=tuple(p['case_ids']),case_limits=budget.SubscriptionLimits(4,300))
    transport=budget.SubscriptionTransport.controlled(run=run,endpoint='http://127.0.0.1:12345/v1/responses')
    r=resources(run)
    async def ready(self):self._workflow_ready=True
    monkeypatch.setattr(sessions.OwnedSubscriptionSession,'_start_workflows',ready)
    owner=await sessions.OwnedSubscriptionSession.create(run=run,provider_transport=transport,**r,
        home_root=tmp_path/'homes',codex_binary=p['codex_binary'],codex_sha256=p['codex_sha256'],
        api_key='synthetic-token',evaluation_profile='subscription_fifty',collector_timeout_seconds=180,
        single_collector_observation=True)
    try:yield owner,p
    finally:await owner.close();await close_resources(r)


def payload(owner,role='collector'):
    case=owner.case_ids[0];p=owner.case_plans[case]
    return {'user_id':p['owner_id'],'project_id':p['project_id'],'language':p['language'],
        'text':'synthetic original narrator input','agent_role':role,
        'evaluation':owner.bridge_for_case(case).before_round(case,1)}


@pytest.mark.parametrize('role',['workspace','memory_context','author_timeline','composer','organiser','unknown'])
def test_other_roles_never_enter_workers(tmp_path,monkeypatch,role):
    async def scenario():
        async with issued(tmp_path,monkeypatch) as (owner,p):
            owner.activate_round(owner.case_ids[0],1)
            for worker in owner._workers.values():
                async def forbidden(*a,**k):pytest.fail('Forbidden worker ran')
                monkeypatch.setattr(worker,'turn',forbidden)
            async with httpx.AsyncClient(transport=owner.worker_transport) as client:
                with pytest.raises(ValueError):
                    await client.post(owner.worker_url+'/internal/codex/turn',json=payload(owner,role))
            assert owner.worker_receipts()==[] and owner.run.snapshot()['client_requests_started']==0
    asyncio.run(scenario())


def test_original_source_preparation_reaches_only_the_owned_collector_boundary(tmp_path,monkeypatch):
    from scripts import single_collector_observation as mode
    async def scenario():
        async with issued(tmp_path,monkeypatch) as (owner,p):
            case=owner.case_ids[0];storage=owner.storage_for_case(case);inputs=owner.bridge_for_case(case).driver_inputs()
            accepted=[]
            def accept(project,turn,text,**kwargs):
                accepted.append((project,text,kwargs))
                return {'source':{'id':str(uuid4())},'photo_context':[]}
            for name,value in {'agent_turn_by_id':None,'agent_session':None,'memories':[],
                'interview_context':{},'memory_events':{'sources':[],'events':[]},
                'profile':launcher.native_case_profile(owner.case_plans[case],'subscription_fifty'),
                'place_journey':None,'family_context':{},'recall_rounds_completed':0}.items():
                monkeypatch.setattr(storage,name,lambda *a,value=value,**k:deepcopy(value))
            monkeypatch.setattr(storage,'accept_interview_turn',accept)
            monkeypatch.setattr(storage,'save_interview_plan',lambda *a,**k:pytest.fail('Post-collector commit'))
            monkeypatch.setattr(owner.runtime,'_workspace_extraction',lambda *a,**k:pytest.fail('Workspace'))
            monkeypatch.setattr(owner.runtime,'_resolve_language',lambda *a,**k:pytest.fail('Language model'))
            class Lease:
                async def io(self,fn,*args,**kwargs):return fn(*args,**kwargs)
                async def check(self):pass
            @asynccontextmanager
            async def lease(*a,**k):yield Lease()
            monkeypatch.setattr(owner.runtime,'_storage_lease',lease)
            async def generated(payload,**kwargs):
                assert payload.interview_context['source'] is not None
                assert payload.language==inputs['language'] and payload.text==inputs['rounds'][0]
                return {'thread_id':'synthetic-thread','reply':'SYNTHETIC_PRIVATE_REPLY'}
            monkeypatch.setattr(owner._workers['collector'],'_turn',generated)
            result=await mode.observe(owner)
            assert len(accepted)==1 and accepted[0][1]==inputs['rounds'][0]
            assert accepted[0][2]['kind']=='narrator_chat'
            assert result['outcome']=='collector_completed' and result['conversation_commit_verified'] is False
            assert [v['role'] for v in owner.worker_receipts()]==['collector']
            with pytest.raises(ValueError):await mode.observe(owner)
            assert len(accepted)==1 and 'SYNTHETIC_PRIVATE_REPLY' not in json.dumps(result)
    asyncio.run(scenario())


@pytest.mark.parametrize('outcome',['complete','cap','headers','body','terminal'])
def test_real_worker_boundary_four_requests_and_stream_failures_stop_once(tmp_path,monkeypatch,outcome):
    async def scenario():
        async with issued(tmp_path,monkeypatch) as (owner,p):
            from scripts.single_collector_observation import CollectorObserved
            owner.activate_round(owner.case_ids[0],1)
            worker=owner._workers['collector'];contacts=[];cleanups=[]
            assert (worker.model,worker.reasoning_effort,worker.timeout)==('gpt-5.6-luna-pooled','max',180)
            monkeypatch.setattr(worker,'_execution_timeout',lambda *a:.03)
            class Body(httpx.AsyncByteStream):
                async def __aiter__(self):
                    yield b'data: {"type":"response.completed"}\n\n' if outcome=='terminal' else b': synthetic\n\n'
                    try:await asyncio.Event().wait()
                    finally:cleanups.append('cancelled')
                async def aclose(self):cleanups.append('closed')
            class Wire(httpx.AsyncBaseTransport):
                async def handle_async_request(self,request):
                    contacts.append(True)
                    if outcome=='headers':await asyncio.Event().wait()
                    if outcome in {'body','terminal'}:
                        return httpx.Response(200,headers={'content-type':'text/event-stream'},stream=Body())
                    return httpx.Response(200,stream=httpx.ByteStream(b'{}'))
            await owner.provider_transport._wire.aclose();owner.provider_transport._wire=Wire()
            async def turn(*a,**k):
                async with httpx.AsyncClient(transport=owner.provider_transport) as client:
                    for _ in range(5 if outcome=='cap' else 4 if outcome=='complete' else 1):
                        await client.post(owner.provider_transport.endpoint,json={},headers={'authorization':'Bearer synthetic-token'})
                return {'thread_id':'synthetic-thread','reply':'synthetic-private-reply'}
            monkeypatch.setattr(worker,'_turn',turn)
            async with httpx.AsyncClient(transport=owner.worker_transport) as client:
                with pytest.raises(CollectorObserved if outcome=='complete' else budget.SubscriptionStopped if outcome=='cap' else TimeoutError):
                    await client.post(owner.worker_url+'/internal/codex/turn',json=payload(owner))
                with pytest.raises((ValueError,budget.SubscriptionStopped)):
                    await client.post(owner.worker_url+'/internal/codex/turn',json=payload(owner))
            receipt=owner.run.snapshot()
            assert len(contacts)==receipt['client_requests_started']==(4 if outcome in {'complete','cap'} else 1)
            assert len(owner.worker_receipts())==1
            if outcome in {'headers','body','terminal'}:
                record=owner.worker_receipts()[0]
                assert record['worker_deadline_expired'] is True
                observed=receipt['attempts'][0]['response_observation']
                assert observed['failure_phase']=={'headers':'awaiting_headers','body':'reading_body','terminal':'awaiting_eof'}[outcome]
                assert observed['eof_observed'] is False and receipt['unresolved_requests']==1
                if outcome=='terminal':assert observed['terminal_sse_category']=='response.completed'
            assert 'synthetic-private-reply' not in json.dumps(receipt)
    asyncio.run(scenario())


@pytest.mark.parametrize('outcome',['complete','execution_limit','cleanup_limit','close_failure','cancelled','external_cancel','setup_failure'])
def test_executor_has_one_300_second_execution_and_one_60_second_cleanup_window(tmp_path,monkeypatch,outcome):
    from scripts import single_collector_observation as mode
    async def scenario():
        p=plan();counts=[];waits=[];started=asyncio.Event();closing=asyncio.Event()
        monkeypatch.setattr(launcher,'verify_main_source',lambda revision:counts.append('main_verified'))
        monkeypatch.setattr(budget,'time',SimpleNamespace(monotonic=lambda:100.0))
        @asynccontextmanager
        async def native(*args):
            receipt=args[-1];receipt['native']={'cleanup_complete':False}
            counts.append('resources')
            try:
                if outcome=='setup_failure':raise ValueError('SYNTHETIC_PRIVATE_ERROR')
                yield {}
            finally:counts.append('resources_closed');receipt['native']['cleanup_complete']=True
        class Owner:
            async def close(self):
                counts.append('session_closed');closing.set()
                if outcome=='cleanup_limit':await asyncio.Event().wait()
                if outcome=='close_failure':raise RuntimeError('SYNTHETIC_PRIVATE_ERROR')
            def worker_receipts(self):return []
        async def create(**kwargs):
            counts.append('session');assert kwargs['single_collector_observation'] is True
            assert kwargs['collector_timeout_seconds']==180
            return Owner()
        async def observe(owner):
            counts.append('collector');started.set()
            if outcome in {'execution_limit','external_cancel'}:await asyncio.Event().wait()
            if outcome=='cancelled':raise asyncio.CancelledError()
            return {'outcome':'collector_completed','campaign_acceptance':False}
        real_wait=asyncio.wait
        async def wait(tasks,*,timeout,**kwargs):
            waits.append(timeout)
            if outcome=='execution_limit' and len(waits)==1:
                await started.wait();return set(),set(tasks)
            if outcome=='external_cancel' and len(waits)==1:
                await started.wait();raise asyncio.CancelledError()
            if outcome=='cleanup_limit' and len(waits)==2:
                await closing.wait();return set(),set(tasks)
            return await real_wait(tasks,timeout=.1,**kwargs)
        monkeypatch.setattr(launcher,'native_resources',native)
        monkeypatch.setattr(sessions.OwnedSubscriptionSession,'create',create)
        monkeypatch.setattr(mode,'observe',observe)
        monkeypatch.setattr(mode.asyncio,'wait',wait)
        result=await launcher.execute_native(p,tmp_path/'run','synthetic-token')
        await asyncio.sleep(0)
        assert len(waits)==2 and waits[0]==300 and 59<waits[1]<=60
        assert counts.count('collector')<=1 and counts.count('session')<=1
        assert counts[0]=='main_verified' and counts.count('main_verified')==1
        assert counts.count('resources_closed')==1
        assert result['request_accounting']['client_requests_started']==0
        assert result['request_accounting']['closed'] is True
        assert result['cumulative_accounting']=={'charged':35,'unresolved':2,'prior_charged':35,'prior_unresolved':2}
        assert result['scope']['semantic_acceptance'] is False
        if outcome=='complete':assert result['observation']['outcome']=='collector_completed' and result['cleanup_complete']
        if outcome=='execution_limit':assert result['observation']['outcome']=='limit_guard'
        if outcome=='cleanup_limit':assert result['status']=='incomplete' and result['cleanup_limit_reached']
        if outcome=='close_failure':assert result['status']=='incomplete' and result['cleanup_complete'] is False
        if outcome=='setup_failure':assert result['observation']['outcome']=='setup_failed'
        if outcome=='external_cancel':assert result['status']=='incomplete' and result['cancelled']
        assert 'SYNTHETIC_PRIVATE_ERROR' not in json.dumps(result)
    asyncio.run(scenario())


@pytest.mark.parametrize('branch,remote',[('codex/unmerged','a'*40),('main','b'*40),('HEAD','a'*40)])
def test_real_evaluation_main_preflight_rejects_unmerged_or_stale_checkout(monkeypatch,branch,remote):
    monkeypatch.setattr(launcher,'git_read',lambda *args:branch if args[0]=='symbolic-ref' else remote)
    monkeypatch.setattr(launcher,'verify_source',lambda *a:pytest.fail('Full source check after invalid main'))
    with pytest.raises(ValueError,match='main branch'):launcher.verify_main_source('a'*40)


def test_verified_main_still_requires_full_exact_source_readback(monkeypatch):
    seen=[]
    monkeypatch.setattr(launcher,'git_read',lambda *args:'main' if args[0]=='symbolic-ref' else 'a'*40)
    monkeypatch.setattr(launcher,'verify_source',lambda revision:seen.append(revision))
    launcher.verify_main_source('a'*40)
    assert seen==['a'*40]


def test_native_executor_rejects_unmerged_source_before_output_or_resources(tmp_path,monkeypatch):
    p=plan()
    def reject(revision):raise ValueError('Evaluation requires the main branch')
    monkeypatch.setattr(launcher,'verify_main_source',reject)
    monkeypatch.setattr(launcher,'native_resources',lambda *a:pytest.fail('Native allocation'))
    with pytest.raises(ValueError,match='main branch'):
        asyncio.run(launcher.execute_native(p,tmp_path/'run','synthetic-token'))
    assert not (tmp_path/'run').exists()
