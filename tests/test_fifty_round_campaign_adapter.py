"""Closed synthetic transports: no sockets, accounts, services or native actors."""
import asyncio
from copy import deepcopy
import hashlib
import importlib
import json
from time import monotonic

import httpx
import pytest

from scripts.single_fifty_campaign import build_campaign_plan
from scripts.fifty_round_budget_contract import build_budget_proposal


def api():
    return importlib.import_module('scripts.fifty_round_campaign_adapter')


def plan(family=True, **limits):
    value = build_campaign_plan(case_id='harbour-copper-notebook', family_enabled=family)
    value['budget'] = build_budget_proposal(family_enabled=family, **limits)
    return value


def fixture(count=1, *, sends=1, delay=0, failure=None):
    return [api().SyntheticWorkerReply(result={'reply': 'Synthetic reply', 'thread_id': 'synthetic-thread'}, sends=tuple(
        api().SyntheticSend(response_id=f'response-{i}-{j}', delay_seconds=delay,
                            failure=failure) for j in range(sends))) for i in range(count)]


def create(tmp_path, p=None, replies=None):
    return api().FiftyRoundSyntheticAdapter.create(plan=p or plan(),
        reservation_root=tmp_path, replies=fixture() if replies is None else replies)


def payload(adapter, role='collector', **extra):
    case = adapter.plan['cases'][0]
    return {'user_id': case['owner_id'], 'project_id': case['project_id'],
        'family_enabled': case['family_enabled'] if role in ('collector','workspace') else False, 'agent_role': role,
        'text': 'synthetic input', 'evaluation': adapter.correlation(), **extra}


async def post(adapter, data):
    async with httpx.AsyncClient(transport=adapter, base_url=api().SYNTHETIC_ORIGIN) as client:
        return await client.post('/internal/codex/turn', json=data)


def test_red_shared_cap_counts_continuations_not_only_workers(tmp_path):
    async def scenario():
        a = create(tmp_path, plan(max_actual_requests=2), fixture(sends=3))
        a.before_round(a.plan['cases'][0]['case_id'], 1)
        with pytest.raises(api().CampaignStopped):
            await post(a, payload(a))
        await a.finish()
        r = a.receipt()
        assert r['dispatch']['worker_requests'] == 1
        assert r['dispatch']['send_reservations'] == r['dispatch']['synthetic_contacts_started'] == 2
        assert r['provider_requests_started'] is None and r['live_ready'] is False
        assert r['status'] == 'incomplete' and r['budget']['approval_status'] == 'unapproved'
    asyncio.run(scenario())


@pytest.mark.parametrize(('role','fields','expected'), [
    ('collector', {}, 'collector'), ('workspace', {}, 'broad_workspace'),
    ('workspace', {'extraction_focus':'place_journey'}, 'focused_place'),
    ('workspace', {'extraction_focus':'family_tree'}, 'focused_family'),
    ('author_timeline', {}, 'canonical_extraction'), ('memory_context', {}, 'initial_locale'),
    ('composer', {'composer_phase':'prepare'}, 'event_preparation'),
    ('composer', {'composer_phase':'draft'}, 'composer_draft'),
    ('composer', {'composer_phase':'review'}, 'composer_review'),
])
def test_structured_classifier(role, fields, expected):
    assert api().classify_worker_request({'agent_role':role, **fields}) == expected


@pytest.mark.parametrize('data', [
    {'agent_role':'organiser'}, {'agent_role':'judge'}, {'agent_role':[]},
    {'agent_role':'workspace','extraction_focus':'author_timeline'},
    {'agent_role':'composer','composer_phase':'index'},
    {'agent_role':'collector','extraction_focus':'place_journey'},
])
def test_unclassified_roles_fail_closed(data):
    with pytest.raises(api().CampaignStopped): api().classify_worker_request(data)


@pytest.mark.parametrize('change', [
    {'user_id':'foreign'}, {'project_id':'foreign'}, {'family_enabled':1},
    {'model':'foreign-model'}, {'evaluation':{}}, {'agent_role':'judge'},
])
def test_scope_or_role_drift_fences_before_fixture_contact(tmp_path, change):
    async def scenario():
        a = create(tmp_path); a.before_round(a.plan['cases'][0]['case_id'], 1)
        with pytest.raises(api().CampaignStopped): await post(a, payload(a, **change))
        await a.finish()
        assert a.receipt()['dispatch']['synthetic_contacts_started'] == 0
        with pytest.raises(api().CampaignStopped): await post(a, payload(a))
    asyncio.run(scenario())


def test_background_requires_bound_job_and_replay_cannot_change_ids(tmp_path):
    async def scenario():
        a = create(tmp_path, replies=fixture(2)); a.before_round(a.plan['cases'][0]['case_id'], 1)
        data = payload(a, 'author_timeline', family_enabled=False); data.pop('evaluation')
        with a.background_job(round_number=1, job_id='timeline-1'):
            assert (await post(a, data)).status_code == 200
        with a.background_job(round_number=1, job_id='other-job'):
            with pytest.raises(api().CampaignStopped): await post(a, data)
        await a.finish()
        r = a.receipt()['dispatch']
        assert r['worker_requests'] == 1 and r['workers'][0]['correlation']['job_id'] == 'timeline-1'
    asyncio.run(scenario())


def test_unbound_background_rejected_and_locale_project_none_is_narrow(tmp_path):
    async def scenario():
        a = create(tmp_path); a.before_round(a.plan['cases'][0]['case_id'], 1)
        data = payload(a, 'author_timeline', family_enabled=False); data.pop('evaluation')
        with pytest.raises(api().CampaignStopped): await post(a, data)
        await a.finish()
    asyncio.run(scenario())


def test_model_policy_preserved_and_immutable(tmp_path):
    p = plan(); a = create(tmp_path, p)
    p['budget']['proposed_limits']['maximum_actual_requests'] = 999
    readback = a.plan; readback['cases'][0]['owner_id'] = 'changed'
    assert a.plan['cases'][0]['owner_id'] != 'changed'
    assert a.receipt()['budget']['proposed_limits']['maximum_actual_requests'] == 600
    assert a.receipt()['executing_source_verified'] is False
    routes = a.receipt()['dispatch']['scope']['roles']
    assert routes['collector']['reasoning'] == 'max'
    assert routes['composer_draft']['reasoning'] == 'low'
    asyncio.run(a.finish())


def test_cancellation_after_synthetic_start_is_unsettled(tmp_path):
    async def scenario():
        a = create(tmp_path, replies=fixture(delay=30)); a.before_round(a.plan['cases'][0]['case_id'], 1)
        task = asyncio.create_task(post(a, payload(a)))
        while not a.receipt()['dispatch']['synthetic_contacts_started']: await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError): await task
        await a.finish()
        r = a.receipt()
        assert r['dispatch']['unsettled_requests'] == 1
        assert r['provider_requests_started'] is None and r['status'] == 'incomplete'
        assert r['cleanup']['synthetic_tasks_finished'] is True
    asyncio.run(scenario())


def test_noncooperative_cancel_has_bounded_drain_and_no_late_settlement(tmp_path, monkeypatch):
    async def scenario():
        a = create(tmp_path); a.before_round(a.plan['cases'][0]['case_id'], 1)
        entered, release = asyncio.Event(), asyncio.Event()
        async def stubborn(send):
            entered.set()
            try: await release.wait()
            except asyncio.CancelledError: await release.wait()
            return {'response_id':'late','wire_model':'synthetic-model','input_tokens':1,'output_tokens':1}
        monkeypatch.setattr(a, '_contact_fixture', stubborn)
        task = asyncio.create_task(post(a, payload(a))); await entered.wait(); task.cancel()
        start = monotonic()
        with pytest.raises(asyncio.CancelledError): await task
        await a.finish()
        assert monotonic() - start < 1
        r = a.receipt(); assert r['cleanup']['synthetic_tasks_finished'] is False
        assert r['dispatch']['completed_sends'] == 0 and r['dispatch']['unsettled_requests'] == 1
        release.set(); await asyncio.sleep(.02)
        assert a.receipt()['dispatch']['completed_sends'] == 0
    asyncio.run(scenario())


def test_fifty_round_real_canonical_driver_with_synthetic_dependencies(tmp_path, monkeypatch):
    from apps.api.agent_storage import UserStorage
    from scripts.canonical_evaluation import CanonicalEvaluationDriver
    monkeypatch.setenv('MEMORY_SPARK_PRIVATE_DRAFT_CADENCE','5')
    async def scenario():
        p = plan(False); case = p['cases'][0]
        a = create(tmp_path, p, fixture(180))  # 3/round plus 3 per checkpoint
        class Storage(UserStorage):
            def __init__(self): self.sources=[]; self.done=0; self.draft=None
            def memory_events(self, project):
                assert project == case['project_id']
                return {'sources':deepcopy(self.sources),'events':[], 'completed_rounds':len(self.sources),
                    'processing':{'extracted_through':self.done}}
            def saved_memoir_draft(self, project, language): return deepcopy(self.draft)
        storage = Storage()
        class Runtime:
            async def turn(self, storage, text, **kwargs):
                assert kwargs['evaluation'] == a.correlation()
                await post(a, payload(a)); await post(a, payload(a, 'workspace', family_enabled=False))
                n=len(storage.sources)+1; source=f'source-{n}'
                storage.sources.append({'id':source,'sequence':n,'version':1,'text':text})
                return {'reply':'Synthetic reply','accepted_source_id':source}
        class Handle:
            def __init__(self, id): self.id=id
            async def result(self): return {'status':'finished'}
        class Broker:
            async def drain_once(self): return [f'timeline-{len(storage.sources)}']
            async def rpc(self, *args, **kwargs): return []
        class Temporal:
            async def start_workflow(self, workflow, **kwargs):
                n=len(storage.sources)
                with a.background_job(round_number=n, job_id=f'timeline-{n}'):
                    data=payload(a,'author_timeline'); data.pop('evaluation'); await post(a,data)
                storage.done=n
                if n%5==0:
                    with a.background_job(round_number=n,job_id=f'composer-{n}'):
                        for phase in ('prepare','draft','review'):
                            data=payload(a,'composer',composer_phase=phase)
                            data.pop('evaluation')
                            if phase=='prepare': data['preparation_id']=hashlib.sha256(str(n).encode()).hexdigest()
                            await post(a,data)
                    storage.draft={'revision':n//5,'covered_round':n,'body':'Synthetic saved draft'}
                return Handle(kwargs['id'])
        driver=CanonicalEvaluationDriver(storage=storage,runtime=Runtime(),broker=Broker(),
            temporal_client=Temporal(),task_queue='canary-synthetic-fifty')
        result=await a.supervise(driver.run_case(case_id=case['case_id'],project_id=case['project_id'],
            rounds=case['rounds'],language=case['language'],evidence_mode='mock_only',single_attempt=True,
            before_round=a.before_round,progress=a.observe_progress))
        await a.finish(result)
        r=a.receipt()
        assert r['status']=='completed_synthetic' and r['synthetic_pipeline_complete'] is True
        assert len(r['cases'][0]['rounds'])==50 and len(r['cases'][0]['checkpoints'])==10
        assert r['dispatch']['worker_requests']==r['dispatch']['send_reservations']==180
        assert r['dispatch']['worker_requests_by_stage']['canonical_extraction']==50
        assert r['dispatch']['worker_requests_by_stage']['composer_review']==10
        assert all(w['correlation']['trace_id'] for w in r['dispatch']['workers'])
        assert r['provider_requests_started'] is None and r['acceptance_status']=='not_established'
        assert r['native_durable_checkpoints_verified'] is False
        assert r['cleanup']['synthetic_tasks_finished'] is True
    asyncio.run(scenario())


def test_production_collector_payload_defaults_and_normalized_correlation(tmp_path, monkeypatch):
    from apps.api.codex_runtime import CodexRuntime
    from apps.api.trajectory_evaluation import normalise_correlation
    monkeypatch.setattr('os.getenv', lambda key, default=None: default)
    async def scenario():
        a=create(tmp_path); c=a.before_round(a.plan['cases'][0]['case_id'],1)
        assert normalise_correlation(c)==c
        runtime=CodexRuntime(worker_url=api().SYNTHETIC_ORIGIN,worker_secret='synthetic',
            worker_transport=a,model=a.plan['budget']['routing']['stages']['collector']['configuration_alias'])
        result=await runtime._worker_turn(user_id=a.plan['cases'][0]['owner_id'],prior=None,
            memories=[],profile={},place_journey={},family_enabled=True,family_context={},
            project_id=a.plan['cases'][0]['project_id'],text='synthetic',language='en-AU',evaluation=c)
        assert result['reply']=='Synthetic reply'
        await a.finish()
    asyncio.run(scenario())


@pytest.mark.parametrize(('role','fields'), [('workspace',{}),('author_timeline',{}),
    ('memory_context',{'project_id':None}),('composer',{'composer_phase':'draft'})])
def test_production_role_family_policy_is_not_campaign_entitlement(tmp_path,role,fields):
    async def scenario():
        a=create(tmp_path); a.before_round(a.plan['cases'][0]['case_id'],1)
        if role=='composer':
            # Scope binding itself remains ordered; exercise composer at its first checkpoint.
            a._round=5
        data=payload(a,role,family_enabled=False,**fields)
        if role in ('author_timeline','composer'):
            data.pop('evaluation'); data.pop('family_enabled') if role=='composer' else None
            with a.background_job(round_number=a._round,job_id='synthetic-lane'):
                await post(a,data)
        else: await post(a,data)
        await a.finish()
        assert a.receipt()['dispatch']['completed_sends']==1
    asyncio.run(scenario())


def test_identical_family_semantic_repair_needs_trusted_attempt_scope(tmp_path):
    async def scenario():
        a=create(tmp_path,replies=fixture(3)); a.before_round(a.plan['cases'][0]['case_id'],1)
        data=payload(a,'workspace',extraction_focus='family_tree')
        await post(a,data)
        with a.semantic_attempt(stage='focused_family',attempt=2): await post(a,data)
        with a.semantic_attempt(stage='focused_family',attempt=3): await post(a,data)
        await a.finish()
        assert a.receipt()['dispatch']['worker_requests_by_stage']['focused_family']==3
    asyncio.run(scenario())


@pytest.mark.parametrize('failure',['quota','provider_error','usage_unknown','protocol_error'])
def test_failure_retains_unknown_usage_and_sticky_reason(tmp_path,failure):
    async def scenario():
        a=create(tmp_path,replies=fixture(failure=failure)); a.before_round(a.plan['cases'][0]['case_id'],1)
        with pytest.raises(api().CampaignStopped): await post(a,payload(a))
        await a.finish()
        r=a.receipt(); assert r['stop_reason']==failure and r['dispatch']['unsettled_requests']==1
        assert r['dispatch']['synthetic_contacts_started']==1 and r['provider_requests_started'] is None
    asyncio.run(scenario())


def test_request_deadline_returns_bounded_incomplete_receipt(tmp_path):
    async def scenario():
        a=create(tmp_path,plan(request_seconds=1),fixture(delay=5)); a.before_round(a.plan['cases'][0]['case_id'],1)
        start=monotonic()
        with pytest.raises(api().CampaignStopped): await post(a,payload(a))
        await a.finish(); assert monotonic()-start<2
        assert a.receipt()['dispatch']['unsettled_requests']==1
    asyncio.run(scenario())


@pytest.mark.parametrize('change',[lambda p:p['cases'][0]['rounds'].__setitem__(0,'changed'),
    lambda p:p['round_roots'][0].__setitem__('trace_id','changed'),
    lambda p:p.__setitem__('live_ready',True),lambda p:p['cases'][0].__setitem__('family_enabled',1)])
def test_invalid_plan_fails_before_journal(tmp_path,change):
    p=plan(); change(p)
    with pytest.raises(ValueError): create(tmp_path,p)
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize('checkpoint',[{'milestone':5,'draft':{'revision':1,'covered_round':5.0}},
    {'milestone':5,'draft':{'revision':0,'covered_round':5}}])
def test_checkpoint_and_failure_progress_cannot_claim_completion(tmp_path,checkpoint):
    async def scenario():
        a=create(tmp_path); a.before_round(a.plan['cases'][0]['case_id'],1)
        with pytest.raises(api().CampaignStopped):
            await a.observe_progress({'rounds':[{'round':1,'status':'completed','background_settled':True}],
                'checkpoints':[checkpoint]})
        await a.finish(); assert a.receipt()['synthetic_pipeline_complete'] is False
    asyncio.run(scenario())


def test_coherent_rewritten_input_is_not_original_fixture(tmp_path):
    p=plan(); p['cases'][0]['rounds'][0]='Changed original'
    p['round_roots'][0]['original_input_sha256']=hashlib.sha256(b'Changed original').hexdigest()
    with pytest.raises(ValueError): create(tmp_path,p)
    assert not list(tmp_path.iterdir())


def test_locale_absent_evaluation_and_false_family_matches_actual_client(tmp_path):
    async def scenario():
        a=create(tmp_path); a.before_round(a.plan['cases'][0]['case_id'],1)
        data=payload(a,'memory_context',project_id=None,family_enabled=False); data.pop('evaluation')
        await post(a,data); await a.finish()
        assert a.receipt()['dispatch']['worker_requests_by_stage']['initial_locale']==1
    asyncio.run(scenario())


def test_production_composer_client_uses_same_transport(tmp_path):
    from types import SimpleNamespace
    from apps.api.memoir_preview import composer_call
    async def scenario():
        a=create(tmp_path,replies=[api().SyntheticWorkerReply({'reply':'{"synthetic":true}'},
            (api().SyntheticSend('composer-response'),))])
        a.before_round(a.plan['cases'][0]['case_id'],1); a._round=5
        runtime=SimpleNamespace(worker_url=api().SYNTHETIC_ORIGIN,worker_secret='synthetic',worker_transport=a)
        storage=SimpleNamespace(user_id=a.plan['cases'][0]['owner_id'])
        with a.background_job(round_number=5,job_id='composer-5'):
            result=await composer_call(runtime,storage,a.plan['cases'][0]['project_id'],'en-AU','draft',{'synthetic':True})
        assert result=={'synthetic':True}
        await a.finish()
    asyncio.run(scenario())


def test_run_deadline_fences_driver_before_retry(tmp_path):
    async def scenario():
        a=create(tmp_path,plan(wall_seconds=1,request_seconds=1))
        with pytest.raises(api().CampaignStopped): await a.supervise(asyncio.sleep(5))
        await a.finish()
        assert a.receipt()['dispatch']['send_reservations']==0
        assert a.receipt()['synthetic_pipeline_complete'] is False
    asyncio.run(scenario())


def test_finish_failure_cannot_keep_success_flag(tmp_path,monkeypatch):
    async def scenario():
        a=create(tmp_path)
        a._complete=True
        original=a._ledger.close
        def broken_close():
            original()
            raise OSError('synthetic close failure')
        monkeypatch.setattr(a._ledger,'close',broken_close)
        with pytest.raises(OSError): await a.finish()
        assert a.receipt()['synthetic_pipeline_complete'] is False
    asyncio.run(scenario())


def test_complete_readback_without_worker_evidence_is_incomplete(tmp_path):
    from test_single_fifty_campaign import receipt_for
    async def scenario():
        a=create(tmp_path); normalized=receipt_for(a.plan)['cases'][0]
        a._round=50
        result={**normalized,'evidence_mode':'mock_only'}
        await a.finish(result)
        assert a.receipt()['synthetic_pipeline_complete'] is False
    asyncio.run(scenario())


@pytest.mark.parametrize('bad_round',[True,2,0,51])
def test_round_binding_rejects_skips_repeats_and_noninteger(tmp_path,bad_round):
    a=create(tmp_path)
    with pytest.raises(api().CampaignStopped): a.before_round(a.plan['cases'][0]['case_id'],bad_round)
    asyncio.run(a.finish())


def test_closed_fixture_rejects_callbacks_and_endpoint_network_fallback(tmp_path):
    with pytest.raises(ValueError): create(tmp_path,replies=lambda: None)
    async def scenario():
        a=create(tmp_path); a.before_round(a.plan['cases'][0]['case_id'],1)
        with pytest.raises(api().CampaignStopped):
            await a.handle_async_request(httpx.Request('POST','https://example.invalid/internal/codex/turn',json=payload(a)))
        await a.finish()
        assert a.receipt()['dispatch']['send_reservations']==0
    asyncio.run(scenario())


def test_finite_float_trajectory_survives_repeated_completed_progress(tmp_path):
    from test_single_fifty_campaign import receipt_for
    async def scenario():
        a=create(tmp_path); a.before_round(a.plan['cases'][0]['case_id'],1)
        record=receipt_for(a.plan)['cases'][0]['rounds'][0]
        record['trajectory']={'steps':[{'output':{'latitude':-33.8688,'duration':.01}}]}
        value={'status':'running','rounds':[record],'checkpoints':[]}
        await a.observe_progress(value)
        await a.observe_progress(deepcopy(value))
        await a.finish()
        assert a.receipt()['stop_reason'] is None
    asyncio.run(scenario())


@pytest.mark.parametrize('number',[float('nan'),float('inf'),float('-inf')])
def test_nonfinite_trajectory_is_rejected_immediately(tmp_path,number):
    from test_single_fifty_campaign import receipt_for
    async def scenario():
        a=create(tmp_path); a.before_round(a.plan['cases'][0]['case_id'],1)
        record=receipt_for(a.plan)['cases'][0]['rounds'][0]; record['trajectory']={'duration':number}
        with pytest.raises(api().CampaignStopped):
            await a.observe_progress({'status':'running','rounds':[record],'checkpoints':[]})
        await a.finish()
    asyncio.run(scenario())


def test_parallel_preparations_serialize_through_one_shared_ledger(tmp_path):
    async def scenario():
        a=create(tmp_path,replies=fixture(3,delay=.01)); a.before_round(a.plan['cases'][0]['case_id'],1); a._round=5
        with a.background_job(round_number=5,job_id='composer-five'):
            results=await asyncio.gather(*(post(a,payload(a,'composer',composer_phase='prepare',
                preparation_id=hashlib.sha256(str(i).encode()).hexdigest())) for i in range(3)))
        assert all(r.status_code==200 for r in results)
        await a.finish(); r=a.receipt()['dispatch']
        assert r['worker_requests']==r['completed_sends']==3 and r['unsettled_requests']==0
    asyncio.run(scenario())


def test_cancelled_queue_wait_never_reserves_second_worker(tmp_path):
    async def scenario():
        a=create(tmp_path,replies=fixture(2,delay=5)); a.before_round(a.plan['cases'][0]['case_id'],1)
        first=asyncio.create_task(post(a,payload(a)))
        while a.receipt()['dispatch']['synthetic_contacts_started']==0: await asyncio.sleep(0)
        second=asyncio.create_task(post(a,payload(a,'workspace',family_enabled=False)))
        await asyncio.sleep(.01); second.cancel()
        with pytest.raises(asyncio.CancelledError): await second
        await a.finish()
        await asyncio.gather(first,return_exceptions=True)
        assert a.receipt()['dispatch']['worker_requests']==1
        assert a.receipt()['dispatch']['unsettled_requests']==1
    asyncio.run(scenario())
