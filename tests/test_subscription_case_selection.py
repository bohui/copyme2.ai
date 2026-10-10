"""One-case scope: source/unit orchestration only, no native/model calls."""
import asyncio
from contextlib import asynccontextmanager
import json
from types import SimpleNamespace
from uuid import uuid4

import pytest

from test_native_collector_timeout import plan as original_plan
from test_memoir_fifty_runner import campaign, CoverageStorage
from scripts import issue14_subscription_runner as runner
from scripts import issue14_subscription_transport as budget
from scripts import run_issue14_subscription_evaluation as launcher
from scripts.memoir_subscription_profiles import profile_for
from scripts import issue14_subscription_session as sessions

FIRST='harbour-copper-notebook'
SECOND='chengdu-tea-ledger'
SELECTION=(FIRST,)


def plan(**changes):
    return original_plan(**{'max_client_requests':569,'max_elapsed_seconds':7200,
        'max_case_client_requests':569,'max_case_elapsed_seconds':7200,
        'collector_timeout_seconds':180,'selected_case_ids':SELECTION,**changes})


def test_selected_plan_keeps_exact_fifty_originals_and_ten_checkpoints():
    value=plan()
    assert value['case_ids']==value['selected_case_ids']==[FIRST]
    assert list(value['cases'])==[FIRST]
    assert value['rounds_per_case']==50 and value['checkpoints']==list(range(5,51,5))
    assert value['dataset_sha256']==original_plan()['dataset_sha256']
    assert value['max_client_requests']==value['max_case_client_requests']==569
    assert value['max_elapsed_seconds']==value['max_case_elapsed_seconds']==7200
    launcher.validate_native_plan(value)


@pytest.mark.parametrize('selection',[(),[],[FIRST],FIRST,('',),('unknown',),
    (FIRST,FIRST),(FIRST,SECOND),(True,)])
def test_invalid_duplicate_empty_or_multiple_selection_cannot_allocate(selection,tmp_path,monkeypatch):
    monkeypatch.setattr(launcher,'native_resources',lambda *args:pytest.fail('Native allocation'))
    with pytest.raises(ValueError):plan(selected_case_ids=selection)
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize('change',[{'max_client_requests':570},{'max_elapsed_seconds':7201},
    {'max_case_client_requests':570},{'max_case_elapsed_seconds':7201},
    {'collector_timeout_seconds':240},{'single_collector_observation':True},
    {'evaluation_profile':'subscription_progressive'},
    {'enable_browser_readback':True},{'enable_public_photo_research':True}])
def test_selected_scope_preserves_approved_upper_bounds_and_full_campaign_mode(change):
    with pytest.raises(ValueError):plan(**change)


@pytest.mark.parametrize('change',['selection','cases','case_ids','missing_selection'])
def test_saved_plan_cannot_resume_with_different_selection_or_foreign_case(change,tmp_path,monkeypatch):
    value=plan()
    if change=='selection':value['selected_case_ids']=[SECOND]
    if change=='cases':value['cases'][SECOND]=original_plan()['cases'][SECOND]
    if change=='case_ids':value['case_ids'].append(SECOND)
    if change=='missing_selection':value.pop('selected_case_ids')
    monkeypatch.setattr(launcher,'verify_main_source',lambda *args:pytest.fail('Source preflight after bad plan'))
    monkeypatch.setattr(launcher,'native_resources',lambda *args:pytest.fail('Native allocation'))
    with pytest.raises(ValueError):asyncio.run(launcher.execute_native(value,tmp_path/'run','synthetic-token'))
    assert not (tmp_path/'run').exists()


@pytest.mark.parametrize('selection',[None,True,FIRST,{},[],[FIRST,FIRST]])
def test_saved_selection_requires_an_explicit_single_case_json_list(selection,tmp_path,monkeypatch):
    value=plan();value['selected_case_ids']=selection
    monkeypatch.setattr(launcher,'verify_main_source',lambda *args:pytest.fail('Source preflight'))
    monkeypatch.setattr(launcher,'native_resources',lambda *args:pytest.fail('Native allocation'))
    with pytest.raises(ValueError):asyncio.run(launcher.execute_native(value,tmp_path/'run','synthetic-token'))
    assert not (tmp_path/'run').exists()


def test_omitted_selection_preserves_original_profiles_plans_and_budgets():
    from scripts.memoir_fifty_readback import CASE_IDS,case_plans_for_run
    from scripts.issue14_progressive_readback import case_plans_for_run as progressive_plans
    run_id=str(uuid4())
    profile=profile_for('subscription_fifty')
    assert profile.selected_case_ids is None and profile.case_ids==CASE_IDS
    assert profile.plans(run_id)==case_plans_for_run(run_id)
    assert (profile.max_requests,profile.max_seconds,profile.case_max_requests,profile.case_max_seconds)==(3000,36000,600,7200)
    assert profile_for('subscription_progressive').plans(run_id)==progressive_plans(run_id)
    value=original_plan()
    assert 'selected_case_ids' not in value and value['case_ids']==list(CASE_IDS)


@pytest.mark.parametrize('case',profile_for('subscription_fifty').case_ids)
def test_each_explicit_selection_keeps_the_original_case_identity_and_fifty_inputs(case):
    value=plan(selected_case_ids=(case,))
    original=original_plan(run_id=value['run_id'])
    assert value['cases']=={case:original['cases'][case]}
    assert value['case_ids']==value['selected_case_ids']==[case]
    assert value['rounds_per_case']==50 and value['checkpoints']==list(range(5,51,5))
    assert value['dataset_sha256']==original['dataset_sha256']


def ledger(tmp_path,selection=SELECTION,run_id=None):
    return budget.SubscriptionRun.create(reservation_root=tmp_path,run_id=run_id or str(uuid4()),
        source_revision='a'*40,limits=budget.SubscriptionLimits(569,7200),
        case_ids=selection,case_limits=budget.SubscriptionLimits(569,7200),selected_case_ids=selection)


def test_ledger_stops_before_second_case_and_cannot_reopen_with_different_selection(tmp_path):
    run=ledger(tmp_path)
    assert run.selected_case_ids==SELECTION
    run.start_case(FIRST);run.finish_case(FIRST)
    with pytest.raises(budget.SubscriptionStopped):run.start_case(SECOND)
    run.close()
    assert run.snapshot()['selected_case_ids']==[FIRST]
    assert run.snapshot()['client_requests_started']==0
    with pytest.raises(budget.SubscriptionStopped,match='reservation_exists'):
        ledger(tmp_path,(SECOND,),run.run_id)


def selected_session(campaign,tmp_path):
    session=campaign();session.run.close()
    journal=tmp_path/'selected';journal.mkdir()
    session.run=ledger(journal)
    profile=profile_for('subscription_fifty',selected_case_ids=SELECTION)
    session.selected_case_ids=SELECTION
    session.case_ids=profile.case_ids
    session.case_plans=profile.plans(session.run.run_id)
    session.bridges={case:profile.bridge(case_id=case,run_id=session.run.run_id,
        project_id=p['project_id'],source_revision=session.run.source_revision)
        for case,p in session.case_plans.items()}
    session.storages={case:CoverageStorage(session,p) for case,p in session.case_plans.items()}
    return session


def test_runner_dispatches_only_fifty_harbour_rounds_and_never_claims_fixture_live(campaign,tmp_path):
    session=selected_session(campaign,tmp_path)
    value=asyncio.run(runner.SubscriptionProgressiveRunner(session,evidence_mode='subscription_fifty',
        selected_case_ids=SELECTION).run())
    assert value['status']=='completed' and value['selected_case_ids']==[FIRST]
    assert [case for case,_,_ in session.calls]==[FIRST]*50
    assert len(value['cases'])==1 and len(value['cases'][0]['rounds'])==50
    assert [item['milestone'] for item in value['cases'][0]['checkpoints']]==list(range(5,51,5))
    assert value['live_ready'] is False and value['e2e_passed'] is False
    assert value['semantic_acceptance']=='human_review_required'
    assert value['request_accounting']['actual_upstream_provider_requests'] is None
    assert value['request_accounting']['case_ids']==[FIRST]


def test_partial_failure_keeps_rounds_and_never_dispatches_a_second_case(campaign,tmp_path):
    session=selected_session(campaign,tmp_path)
    turn=session.turn
    async def fail(storage,text,**kwargs):
        if len(session.calls)==12:raise RuntimeError('synthetic private failure')
        return await turn(storage,text,**kwargs)
    session.turn=fail
    value=asyncio.run(runner.SubscriptionProgressiveRunner(session,evidence_mode='subscription_fifty',
        selected_case_ids=SELECTION).run())
    assert value['status']=='incomplete' and value['output'] is None
    assert len(session.calls)==12 and all(case==FIRST for case,_,_ in session.calls)
    assert len(value['cases'])==1 and len(value['cases'][0]['rounds'])==13
    assert value['cleanup']['session_closed'] is True
    assert 'synthetic private failure' not in json.dumps(value)


def test_runner_rejects_differing_selection_before_any_dispatch(campaign,tmp_path):
    session=selected_session(campaign,tmp_path)
    try:
        with pytest.raises(runner.SubscriptionRunnerError):
            runner.SubscriptionProgressiveRunner(session,evidence_mode='subscription_fifty',selected_case_ids=(SECOND,))
        assert session.calls==[]
    finally:session.run.close()


def test_plan_only_cli_requires_explicit_selector_and_makes_no_execution_calls(tmp_path,monkeypatch,capsys):
    value=plan()
    monkeypatch.setattr(launcher,'configured_credential',lambda:pytest.fail('Credential discovery'))
    monkeypatch.setattr(launcher,'execute_native',lambda *args:pytest.fail('Native execution'))
    argv=['--evaluation-profile','subscription_fifty','--case-id',FIRST,
        '--run-id',value['run_id'],'--source-revision',value['source_revision'],'--run-dir',str(tmp_path/'run'),
        '--max-client-requests','569','--max-elapsed-seconds','7200',
        '--max-case-client-requests','569','--max-case-elapsed-seconds','7200','--collector-timeout-seconds','180',
        '--codex-binary',value['codex_binary'],'--codex-sha256',value['codex_sha256'],
        '--temporal-binary',value['temporal_binary'],'--temporal-sha256',value['temporal_sha256']]
    assert launcher.main(argv)==0
    assert json.loads(capsys.readouterr().out)['selected_case_ids']==[FIRST]
    assert launcher.main(argv+['--case-id',FIRST])==3
    assert not (tmp_path/'run').exists()


@pytest.mark.parametrize('field',['selected_case_ids','case_ids'])
def test_foreign_case_in_final_accounting_cannot_promote_receipt(campaign,tmp_path,field):
    session=selected_session(campaign,tmp_path)
    snapshot=session.run.snapshot
    def changed():
        value=snapshot()
        value[field]=[SECOND]
        return value
    session.run.snapshot=changed
    value=asyncio.run(runner.SubscriptionProgressiveRunner(session,evidence_mode='subscription_fifty',
        selected_case_ids=SELECTION).run())
    assert value['status']=='incomplete' and value['output'] is None
    assert len(session.calls)==50 and all(case==FIRST for case,_,_ in session.calls)


@pytest.mark.parametrize('case,ordinal',[(SECOND,1),(FIRST,51)])
def test_owned_activation_rejects_unselected_case_and_round_fifty_one_before_dispatch(tmp_path,monkeypatch,case,ordinal):
    run=ledger(tmp_path)
    owner=object.__new__(sessions.OwnedSubscriptionSession)
    owner.run=run;owner._active=None;owner._pending=set();owner._finished={FIRST:50}
    owner._profile=profile_for('subscription_fifty',selected_case_ids=SELECTION)
    monkeypatch.setattr(sessions,'assert_owned_subscription_session',lambda value:None)
    try:
        with pytest.raises(ValueError):owner.activate_round(case,ordinal)
        assert run.snapshot()['client_requests_started']==0
        assert run.snapshot()['stop_reason']=='protocol_invalid'
    finally:run.close()


def test_native_executor_propagates_exact_selection_to_session_runner_and_receipt(tmp_path,monkeypatch):
    value=plan();calls=[]
    monkeypatch.setattr(launcher,'verify_main_source',lambda revision:calls.append('main_verified'))
    @asynccontextmanager
    async def resources(plan,run,directory,receipt):
        assert plan['selected_case_ids']==[FIRST] and run.selected_case_ids==SELECTION
        assert run.case_ids==SELECTION
        receipt['native']={'cleanup_complete':True}
        yield {}
    async def create(**kwargs):
        assert kwargs['selected_case_ids']==SELECTION and kwargs['collector_timeout_seconds']==180
        calls.append('session')
        async def close():
            await kwargs['provider_transport'].aclose();kwargs['run'].close()
        return SimpleNamespace(close=close,worker_receipts=lambda:[],run=kwargs['run'])
    class Runner:
        def __init__(self,session,**kwargs):
            assert kwargs=={'evidence_mode':'subscription_fifty','selected_case_ids':SELECTION}
            calls.append('runner')
        async def run(self,**kwargs):return {'status':'incomplete','selected_case_ids':[FIRST]}
    monkeypatch.setattr(launcher,'native_resources',resources)
    monkeypatch.setattr(sessions.OwnedSubscriptionSession,'create',create)
    monkeypatch.setattr(runner,'SubscriptionProgressiveRunner',Runner)
    receipt=asyncio.run(launcher.execute_native(value,tmp_path/'run','synthetic-token'))
    assert calls==['main_verified','session','runner']
    assert receipt['status']=='incomplete' and receipt['selected_case_ids']==[FIRST]
    assert receipt['request_accounting']['case_ids']==[FIRST]
    assert receipt['request_accounting']['client_requests_started']==0


def test_owned_constructor_rejects_differing_ledger_selection_before_resource_setup(tmp_path):
    run=ledger(tmp_path)
    transport=budget.SubscriptionTransport.controlled(run=run,endpoint='http://127.0.0.1:65432/v1/responses')
    async def scenario():
        try:
            with pytest.raises(ValueError,match='Request gate'):
                await sessions.OwnedSubscriptionSession.create(run=run,provider_transport=transport,
                    storages=None,broker=None,temporal_client=None,home_root=tmp_path/'homes',
                    codex_binary=None,codex_sha256=None,api_key='synthetic-token',
                    evaluation_profile='subscription_fifty',collector_timeout_seconds=180,
                    selected_case_ids=(SECOND,))
            assert run.snapshot()['client_requests_started']==0 and not (tmp_path/'homes').exists()
        finally:await transport.aclose();run.close()
    asyncio.run(scenario())
