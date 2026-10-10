"""One explicitly admitted collector observation; no campaign acceptance."""
import asyncio
from copy import deepcopy
import fcntl
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
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


async def _execute_child(plan,directory,api_key):
    """Native work stays in the supervised process, including setup threads."""
    from scripts import run_issue14_subscription_evaluation as launcher
    from scripts.issue14_subscription_session import OwnedSubscriptionSession
    from scripts.memoir_subscription_profiles import profile_for
    directory=Path(directory)
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
    cleanup_deadline=None
    interrupted=False

    def stop(reason):
        try:run.stop(reason)
        except Exception:receipt['status']='incomplete'

    def begin_cleanup():
        nonlocal cleanup_deadline
        if cleanup_deadline is None:
            receipt['cleanup_started_monotonic']=time.monotonic()
            cleanup_deadline=asyncio.get_running_loop().time()+60
        receipt['cleanup_deadline_monotonic']=cleanup_deadline

    def record():
        if session is not None:receipt['worker_receipts']=session.worker_receipts()
        receipt['request_accounting']=run.snapshot()
        launcher._save(directory/'receipt.json',receipt)

    def failure(error):
        receipt['status']='incomplete'
        if isinstance(error,asyncio.CancelledError):
            receipt.update(cancelled=True)
            receipt['observation']['outcome']='cancelled'
        elif receipt['observation']['outcome']=='not_dispatched':
            receipt['observation']['outcome']='collector_failed' if session is not None else 'setup_failed'
        if session is not None and session.worker_receipts():
            if session.worker_receipts()[-1].get('worker_deadline_expired') is True:
                receipt['observation']['outcome']='worker_timeout'

    root=asyncio.current_task()
    def interrupt():
        nonlocal interrupted
        if interrupted:return
        interrupted=True
        failure(asyncio.CancelledError())
        stop('send_interrupted_or_failed')
        begin_cleanup()
        record()  # Retain accounting even if native setup's thread join hangs.
        root.cancel()
    loop=asyncio.get_running_loop()
    loop.add_signal_handler(signal.SIGTERM,interrupt)
    record()

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
                except BaseException as error:
                    failure(error)
                finally:
                    begin_cleanup()
                    stop('closed')
                    record()  # Seal before any cancellation-suppressing cleanup.
                    if session is not None:
                        await session.close()
                        receipt['session_cleanup_complete']=True
        except BaseException as error:
            failure(error)
        finally:
            begin_cleanup()

    try:
        async with asyncio.timeout_at(run.global_deadline):await pipeline()
        receipt['cleanup_complete']=(receipt.get('native',{}).get('cleanup_complete') is True
            and receipt['session_cleanup_complete'])
    except BaseException as error:
        failure(error)
        stop(run.timeout_reason() if isinstance(error,TimeoutError) else 'send_interrupted_or_failed')
        begin_cleanup()
    finally:
        begin_cleanup()
        record()
        try:
            async with asyncio.timeout_at(cleanup_deadline):await transport.aclose()
            receipt['transport_cleanup_complete']=True
        except BaseException:receipt.update(status='incomplete',cleanup_complete=False)
        try:run.close()
        except Exception:receipt['status']='incomplete'
        accounting=run.snapshot()
        receipt['request_accounting']=accounting
        if accounting['stop_reason'] in {'requests_limit','case_requests_limit','elapsed_limit','case_elapsed_limit'}:
            receipt['observation']['outcome']='limit_guard'
        receipt['cumulative_accounting']={'charged':35+accounting['client_requests_started'],
            'unresolved':2+accounting['unresolved_requests'],'prior_charged':35,'prior_unresolved':2}
        launcher._save(directory/'receipt.json',receipt)
        loop.remove_signal_handler(signal.SIGTERM)
    return receipt


def _read_receipt(directory,plan):
    # Only this process's declared content-free receipt; never session homes.
    try:
        fd=os.open(directory/'receipt.json',os.O_RDONLY|os.O_NOFOLLOW)
        with os.fdopen(fd,'rb') as stream:raw=stream.read(1024*1024+1)
        if len(raw)>1024*1024:return {}
        receipt=json.loads(raw)
        if (type(receipt) is dict and receipt.get('run_id')==plan['run_id']
                and receipt.get('source_revision')==plan['source_revision']):return receipt
    except (OSError,ValueError):pass
    return {}


def _journal_accounting(directory,plan):
    """Recover bounded durable counts after a hard stop; never refund uncertainty."""
    try:
        fd=os.open(directory/'journal'/(plan['run_id']+'.jsonl'),os.O_RDONLY|os.O_NOFOLLOW)
        with os.fdopen(fd,'rb') as stream:
            raw=stream.read(1024*1024+1)
        if len(raw)>1024*1024 or not raw.endswith(b'\n'):return None
        events=[json.loads(line) for line in raw.splitlines()]
        first=events[0]
        if (first['event']!='created' or first['run_id']!=plan['run_id']
                or first['source_revision']!=plan['source_revision']):return None
        reserved={};started=set();completed=set()
        for event in events[1:]:
            ordinal=event.get('ordinal')
            if event['event'] in {'send_reserved','send_started','http_response_completed'}:
                if type(ordinal) is not int or not 1<=ordinal<=4:return None
            if event['event']=='send_reserved':
                if ordinal!=len(reserved)+1:return None
                reserved[ordinal]={key:event[key] for key in ('ordinal','payload_bytes',
                    'reserved_at_monotonic','case_id','case_ordinal') if key in event}
                reserved[ordinal]['status']='reserved'
            if event['event']=='send_started':
                if ordinal not in reserved or ordinal in started:return None
                started.add(ordinal)
                if 'started_at_monotonic' in event:
                    reserved[ordinal]['started_at_monotonic']=event['started_at_monotonic']
            if event['event']=='http_response_completed':
                if ordinal not in started or ordinal in completed:return None
                completed.add(ordinal)
                reserved[ordinal].update(status='completed',**{key:event[key] for key in
                    ('status_code','response_bytes','completed_at_monotonic','elapsed_ms') if key in event})
            if event['event']=='response_observed' and ordinal in reserved:
                reserved[ordinal]['response_observation']=event['response_observation']
        if not completed<=started<=set(reserved) or len(reserved)>4:return None
        return {'client_requests_reserved':len(reserved),'client_requests_started':len(started),
            'completed_http_responses':len(completed),'unresolved_requests':len(reserved)-len(completed),
            'attempts':list(reserved.values()),
            'journal_durable':None,'closed':False,'recovered_from_journal':True,
            'journal_durability_verified':False,
            'upstream_cancellation_verified':False,'restart_allowed':False}
    except (OSError,ValueError,KeyError,IndexError,TypeError):return None


async def _supervise(command,payload,directory,*,execution_seconds=300,cleanup_seconds=60,stop_grace=5):
    """Own one process group; no thread/task join can outlive the cleanup budget."""
    from scripts import run_issue14_subscription_evaluation as launcher
    plan=payload['plan']
    execution_deadline=time.monotonic()+execution_seconds
    raw=json.dumps(payload,allow_nan=False,separators=(',',':')).encode()
    if len(raw)>64*1024:raise ValueError('Bounded observation control input required')
    # No key or environment dump in argv/output. Popen gives synchronous PID
    # ownership; cancellation cannot lose a subprocess during async creation.
    process=subprocess.Popen(command,stdin=subprocess.PIPE,stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,start_new_session=True,cwd=launcher.ROOT)
    cleanup_deadline=None
    cancelled=execution_expired=forced=supervisor_failed=False
    term_sent=kill_sent=False
    offset=0

    def group_exists():
        try:os.killpg(process.pid,0);return True
        except ProcessLookupError:return False

    def signal_owned(sig):
        try:os.killpg(process.pid,sig)
        except ProcessLookupError:pass

    def begin_cleanup(now):
        nonlocal cleanup_deadline
        if cleanup_deadline is None:cleanup_deadline=now+cleanup_seconds

    def terminate():
        nonlocal term_sent
        if not term_sent:
            term_sent=True
            signal_owned(signal.SIGTERM)

    try:
        os.set_blocking(process.stdin.fileno(),False)
        while True:
            now=time.monotonic()
            receipt=_read_receipt(directory,plan)
            marker=receipt.get('cleanup_started_monotonic')
            if type(marker) in (int,float) and execution_deadline-execution_seconds<=marker<=now:
                candidate=marker+cleanup_seconds
                cleanup_deadline=candidate if cleanup_deadline is None else min(cleanup_deadline,candidate)
            exited=process.poll() is not None
            if exited and not group_exists():break
            if exited:
                begin_cleanup(now)
                terminate()
            if cleanup_deadline is None and now>=execution_deadline:
                execution_expired=True
                begin_cleanup(now)
                terminate()
            if cleanup_deadline is not None and now>=cleanup_deadline-stop_grace and not kill_sent:
                forced=kill_sent=True
                signal_owned(signal.SIGKILL)
            if cleanup_deadline is not None and now>=cleanup_deadline:break
            if offset<len(raw) and not term_sent and not exited:
                try:offset+=os.write(process.stdin.fileno(),raw[offset:])
                except BlockingIOError:pass
                except BrokenPipeError:offset=len(raw)
                if offset==len(raw):process.stdin.close()
            try:await asyncio.sleep(min(.02,max(0,(cleanup_deadline or execution_deadline)-time.monotonic())))
            except asyncio.CancelledError:
                cancelled=True
                begin_cleanup(time.monotonic())
                terminate()  # Once only, even if the caller cancels repeatedly.
    except BaseException:
        supervisor_failed=True
        begin_cleanup(time.monotonic())
        terminate()
        # An unexpected pipe/control failure still retains ownership. No join
        # or to_thread call is used for this bounded process-group settlement.
        while process.poll() is None or group_exists():
            now=time.monotonic()
            if now>=cleanup_deadline-stop_grace and not kill_sent:
                forced=kill_sent=True
                signal_owned(signal.SIGKILL)
            if now>=cleanup_deadline:break
            try:await asyncio.sleep(min(.02,max(0,cleanup_deadline-time.monotonic())))
            except asyncio.CancelledError:cancelled=True
    finally:
        process.stdin.close()
    reaped=process.poll() is not None
    gone=not group_exists()
    receipt=_read_receipt(directory,plan) or {'run_id':plan['run_id'],
        'source_revision':plan['source_revision'],'status':'incomplete',
        'observation':{'outcome':'setup_failed','campaign_acceptance':False},'cleanup_complete':False}
    receipt['process_supervision']={'owned_group_id':process.pid,'leader_reaped':reaped,
        'owned_group_gone':gone,'forced_stop':forced,'term_sent':term_sent,
        'execution_deadline_monotonic':execution_deadline,'cleanup_deadline_monotonic':cleanup_deadline}
    if forced or not gone or not reaped:
        receipt.update(status='incomplete',cleanup_complete=False,cleanup_limit_reached=True)
        receipt.setdefault('native',{})['cleanup_complete']=False
        receipt['native_cleanup_verified']=False
    if cancelled:
        receipt.update(status='incomplete',cancelled=True)
        if receipt['observation']['outcome']!='worker_timeout':receipt['observation']['outcome']='cancelled'
    elif execution_expired:
        receipt['status']='incomplete'
        if receipt['observation']['outcome']!='worker_timeout':receipt['observation']['outcome']='execution_limit'
    if process.returncode!=0:receipt['status']='incomplete'
    if supervisor_failed:receipt.update(status='incomplete',supervisor_failed=True)
    journal=_journal_accounting(directory,plan)
    receipt['admission_closed']=gone
    accounting=receipt.get('request_accounting')
    if journal is not None:
        if (accounting is None or any(accounting.get(key)!=journal[key] for key in
                ('client_requests_started','completed_http_responses','unresolved_requests'))):
            accounting=receipt['request_accounting']=journal
    sealed=(accounting is not None and receipt.get('cleanup_started_monotonic') is not None
        and accounting.get('stop_reason') is not None)
    verified=(accounting is not None and (not forced or journal is not None or sealed))
    if not verified:
        receipt.update(status='incomplete',accounting_verified=False)
        receipt['accounting_uncertainty']={'additional_charges_max':4,'replay_allowed':False}
        started=0 if accounting is None else accounting['client_requests_started']
        unresolved=0 if accounting is None else accounting['unresolved_requests']
        receipt['cumulative_accounting']={'charged_lower_bound':35+started,'charged_upper_bound':39,
            'unresolved_lower_bound':2+unresolved,'unresolved_upper_bound':6,
            'prior_charged':35,'prior_unresolved':2}
    else:
        receipt['cumulative_accounting']={'charged':35+accounting['client_requests_started'],
            'unresolved':2+accounting['unresolved_requests'],'prior_charged':35,'prior_unresolved':2}
    # Read only after the writer has exited. Never return a live mutable pipeline.
    if gone and reaped:launcher._save(directory/'receipt.json',receipt)
    return receipt


async def execute(plan,directory,api_key):
    from scripts import run_issue14_subscription_evaluation as launcher
    directory=Path(directory)
    directory.mkdir(parents=True,exist_ok=False,mode=0o700)
    launcher._save(directory/'plan.json',plan)
    return await _supervise([sys.executable,'-B','-m','scripts.single_collector_observation','--owned-child'],
        {'plan':plan,'directory':str(directory),'api_key':api_key,'supervisor_pid':os.getpid()},directory)


def _require_parent_lease(plan,supervisor_pid,*,path=Path('/tmp/memoir-native-heavy.lock')):
    """Verify the CLI parent's already-held lease; never allocate a new lease."""
    if type(supervisor_pid) is not int or supervisor_pid!=os.getppid():
        raise ValueError('Owned observation supervisor required')
    fd=os.open(path,os.O_RDWR|os.O_NOFOLLOW)
    try:
        if os.fstat(fd).st_uid!=os.getuid():raise ValueError('Lease owner differs')
        raw=os.read(fd,1025)
        if len(raw)>1024:raise ValueError('Lease metadata exceeds bound')
        if json.loads(raw)!={'run_id':plan['run_id'],'pid':supervisor_pid}:
            raise ValueError('Parent lease identity differs')
        try:fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:return
        raise ValueError('Parent native lease is not held')
    finally:os.close(fd)


def _child_main():
    # The supervised child independently checks main and the exact saved plan.
    from scripts import run_issue14_subscription_evaluation as launcher
    raw=sys.stdin.buffer.read(64*1024+1)
    if len(raw)>64*1024:raise ValueError('Bounded observation input required')
    value=json.loads(raw)
    plan=value['plan']
    launcher.validate_native_plan(plan)
    launcher.verify_main_source(plan['source_revision'])
    from scripts.issue14_subscription_source_contract_v6 import audit_subscription_source_v6
    audit_subscription_source_v6(launcher.ROOT)
    _require_parent_lease(plan,value['supervisor_pid'])
    if 'single_collector_observation' not in plan:raise ValueError('Collector observation required')
    asyncio.run(_execute_child(plan,Path(value['directory']),value['api_key']))


if __name__=='__main__':
    if sys.argv[1:]!=['--owned-child']:raise SystemExit(3)
    try:_child_main()
    except BaseException:raise SystemExit(3) from None
