"""One explicitly admitted collector observation; no campaign acceptance."""
import asyncio
from copy import deepcopy
from pathlib import Path
from uuid import uuid4

from scripts.issue14_subscription_transport import SubscriptionLimits, SubscriptionRun, SubscriptionTransport


def observation_scope(case_id):
    return {'case_id':case_id,'round':1,'dispatches':1,'allowed_roles':['collector'],
        'cleanup_seconds':60,'prior_charged':35,'prior_unresolved':2,
        'campaign_execution':False,'semantic_acceptance':False}


def validate_observation_limits(profile, requests, seconds, case_requests, case_seconds, collector):
    if (profile != 'subscription_fifty' or type(requests) is not int or requests != 4
            or type(case_requests) is not int or case_requests != 4
            or type(seconds) not in (int,float) or seconds != 300
            or type(case_seconds) not in (int,float) or case_seconds != 300
            or type(collector) not in (int,float) or collector != 180):
        raise ValueError('Single collector observation requires exact 4-request/300-second/180-second scope')


class CollectorObserved(BaseException):
    """Owned terminal sentinel; carries no collector output or arbitrary text."""


class CollectorObservationGate:
    def __init__(self, run):
        validate_observation_limits('subscription_fifty',run.limits.max_requests,
            run.limits.max_elapsed_seconds,run.case_limits.max_requests,
            run.case_limits.max_elapsed_seconds,180)
        self.run, self.scope = run, (run.case_ids[0],1)
        self.dispatched = self.completed = False
        self.terminal = CollectorObserved()

    def admit(self, role, scope):
        if role != 'collector' or scope != self.scope or self.dispatched:
            self.run.stop('protocol_invalid')
            raise ValueError('Single collector dispatch scope exhausted or forbidden')
        self.dispatched = True

    def complete(self):
        self.completed = True
        self.run.stop('closed')
        raise self.terminal


async def observe(session):
    from scripts.issue14_subscription_session import assert_owned_subscription_session
    assert_owned_subscription_session(session)
    gate = session._collector_observation
    if type(gate) is not CollectorObservationGate or gate.dispatched:
        raise ValueError('A fresh issued collector observation is required')
    case, ordinal = gate.scope
    bridge = session.bridge_for_case(case)
    inputs = bridge.driver_inputs()
    storage = session.storage_for_case(case)
    correlation = session.activate_round(case,ordinal)
    if correlation != bridge.before_round(case,ordinal):
        raise ValueError('Original collector correlation differs')
    try:
        # The real runtime accepts the original source and constructs the same
        # collector schema/context. No renderer callbacks launch early workspace
        # extraction; the owned terminal sentinel stops before follow-on work.
        await session.runtime.turn(storage,inputs['rounds'][0],project_id=inputs['project_id'],
            language=inputs['language'],client_turn_id=str(uuid4()),
            evaluation=deepcopy(correlation),conversation_text=inputs['rounds'][0],source_kind='narrator_chat')
    except CollectorObserved as terminal:
        if terminal is not gate.terminal or not gate.completed:
            raise ValueError('Unowned collector terminal') from None
        return {'outcome':'collector_completed','collector_dispatches':1,
            'campaign_acceptance':False,'conversation_commit_verified':False}
    raise ValueError('Collector observation returned beyond its owned boundary')


async def execute(plan,directory,api_key):
    from scripts import run_issue14_subscription_evaluation as launcher
    from scripts.issue14_subscription_session import OwnedSubscriptionSession
    from scripts.memoir_subscription_profiles import profile_for
    directory=Path(directory)
    directory.mkdir(parents=True,exist_ok=False,mode=0o700)
    (directory/'journal').mkdir(mode=0o700)
    launcher._save(directory/'plan.json',plan)
    profile=profile_for(plan['evaluation_profile'])
    run=SubscriptionRun.create(reservation_root=directory/'journal',run_id=plan['run_id'],
        source_revision=plan['source_revision'],limits=SubscriptionLimits(4,300),
        case_ids=profile.case_ids,case_limits=SubscriptionLimits(4,300))
    receipt={'schema_version':'memoir-single-collector-observation/1','run_id':run.run_id,
        'source_revision':run.source_revision,'status':'observation','execution_started':True,
        'observation':{'outcome':'not_dispatched','campaign_acceptance':False},
        'scope':deepcopy(plan['single_collector_observation']),
        'execution_deadline_monotonic':run.global_deadline,'cleanup_complete':False,
        'session_cleanup_complete':True,'transport_cleanup_complete':False}
    transport=SubscriptionTransport.existing_route(run=run,authorization='Bearer '+api_key)
    session=None
    execution_finished=asyncio.Event()
    cleanup_deadline=None

    def stop(reason):
        try:run.stop(reason)
        except Exception:receipt['status']='incomplete'

    def begin_cleanup():
        nonlocal cleanup_deadline
        if cleanup_deadline is None:cleanup_deadline=asyncio.get_running_loop().time()+60
        receipt['cleanup_deadline_monotonic']=cleanup_deadline
        execution_finished.set()

    def cleanup_remaining():
        return max(0,cleanup_deadline-asyncio.get_running_loop().time())

    async def pipeline():
        nonlocal session
        try:
            async with launcher.native_resources(plan,run,directory,receipt) as resources:
                try:
                    receipt['session_cleanup_complete']=False
                    session=await OwnedSubscriptionSession.create(run=run,provider_transport=transport,
                        **resources,home_root=directory/'homes',codex_binary=plan['codex_binary'],
                        codex_sha256=plan['codex_sha256'],api_key=api_key,
                        evaluation_profile=profile.name,collector_timeout_seconds=180,
                        single_collector_observation=True)
                    receipt['observation']=await observe(session)
                finally:
                    begin_cleanup()
                    stop('closed')
                    if session is not None:
                        await session.close()
                        receipt['session_cleanup_complete']=True
        except BaseException:
            if receipt['observation']['outcome']=='not_dispatched':
                receipt['observation'].update(outcome='collector_failed' if session is not None else 'setup_failed')
            if session is not None and session.worker_receipts():
                failure=session.worker_receipts()[-1]
                if failure.get('worker_deadline_expired') is True:
                    receipt['observation']['outcome']='worker_timeout'
            if (receipt.get('native',{}).get('cleanup_complete') is False
                    or not receipt['session_cleanup_complete']):
                receipt['status']='incomplete'
        finally:
            begin_cleanup()

    task=asyncio.create_task(pipeline())
    terminal=asyncio.create_task(execution_finished.wait())
    try:
        done,_=await asyncio.wait({task,terminal},timeout=run.remaining_seconds(),return_when=asyncio.FIRST_COMPLETED)
        if not done:
            begin_cleanup()
            stop(run.timeout_reason())
            receipt['observation']['outcome']='execution_limit'
            task.cancel()
        # One separate cleanup window; a timeout cannot authorize further sends.
        begin_cleanup()
        done,_=await asyncio.wait({task},timeout=cleanup_remaining())
        if not done:
            task.cancel()
            receipt.update(status='incomplete',cleanup_limit_reached=True)
        else:
            task.result()
            receipt['cleanup_complete']=(receipt.get('native',{}).get('cleanup_complete') is True
                and receipt['session_cleanup_complete'])
    except BaseException:
        task.cancel()
        stop('send_interrupted_or_failed')
        receipt.update(status='incomplete',cancelled=True)
        begin_cleanup()
        done,_=await asyncio.wait({task},timeout=cleanup_remaining())
        if not done:receipt['cleanup_limit_reached']=True
    finally:
        terminal.cancel()
        await asyncio.gather(terminal,return_exceptions=True)
        if session is not None:receipt['worker_receipts']=session.worker_receipts()
        try:
            async with asyncio.timeout_at(cleanup_deadline):await transport.aclose()
            receipt['transport_cleanup_complete']=True
        except BaseException:receipt.update(status='incomplete',cleanup_complete=False)
        try:run.close()
        except Exception:receipt['status']='incomplete'
        accounting=run.snapshot()
        receipt['request_accounting']=accounting
        if accounting['stop_reason'] in {'request_limit','case_request_limit','elapsed_limit','case_elapsed_limit'}:
            receipt['observation']['outcome']='limit_guard'
        receipt['cumulative_accounting']={'charged':35+accounting['client_requests_started'],
            'unresolved':2+accounting['unresolved_requests'],'prior_charged':35,'prior_unresolved':2}
        launcher._save(directory/'receipt.json',receipt)
    return receipt
