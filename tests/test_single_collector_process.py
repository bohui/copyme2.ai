"""Owned Python process probes: no listeners, databases, leases or model calls."""
import asyncio
import json
import os
from pathlib import Path
import sys
import time

import pytest

from scripts import single_collector_observation as mode


CHILD = r'''
import asyncio, json, signal, sys, threading, time
from pathlib import Path
from scripts.issue14_subscription_runner import _settle_task
value=json.load(sys.stdin)
directory=Path(value['directory'])
receipt={'run_id':value['plan']['run_id'],'source_revision':value['plan']['source_revision'],
    'status':'observation','observation':{'outcome':'collector_completed','campaign_acceptance':False},
    'native':{'cleanup_complete':False},'cleanup_complete':False,
    'request_accounting':{'client_requests_started':3,'completed_http_responses':2,
        'unresolved_requests':1,'closed':True,'stop_reason':'closed'}}
def save(name, value):
    temporary=directory/(name+'.tmp')
    temporary.write_text(json.dumps(value))
    temporary.replace(directory/name)
async def run():
    if value['case']=='timeout_hang':receipt['observation']['outcome']='worker_timeout'
    root=asyncio.current_task()
    signals=[]
    def cancel():
        signals.append('term')
        save('signals.json',signals)
        root.cancel()
    asyncio.get_running_loop().add_signal_handler(signal.SIGTERM,cancel)
    # This is the real cancellation-suppressing join, including a live thread.
    hold=threading.Event()
    task=asyncio.create_task(asyncio.to_thread(hold.wait))
    try:
        if value['case']=='setup_hang':await asyncio.shield(task)
    except asyncio.CancelledError:
        receipt.update(status='incomplete',cancelled=True)
        receipt['observation']['outcome']='cancelled'
    finally:
        receipt['cleanup_started_monotonic']=time.monotonic()
        save('receipt.json',receipt)
        if value['case']=='complete':
            hold.set()
        await _settle_task(task)
        receipt['native']['cleanup_complete']=receipt['cleanup_complete']=True
        save('receipt.json',receipt)
        (directory/'late-write').write_text('cleanup completed')
asyncio.run(run())
'''


def payload(tmp_path, case):
    directory=tmp_path/'run'
    directory.mkdir()
    return directory,{'directory':str(directory),'case':case,'api_key':'synthetic-private-token',
        'plan':{'run_id':'synthetic-run','source_revision':'a'*40}}


@pytest.mark.parametrize('case',['cleanup_hang','setup_hang'])
def test_owned_process_bounds_cancellation_suppressing_thread_and_prevents_late_writes(tmp_path,case):
    directory,value=payload(tmp_path,case)
    started=time.monotonic()
    result=asyncio.run(mode._supervise([sys.executable,'-B','-c',CHILD],value,directory,
        execution_seconds=2,cleanup_seconds=.4,stop_grace=.1))
    assert time.monotonic()-started<4
    assert result['status']=='incomplete' and result['cleanup_complete'] is False
    assert result['cleanup_limit_reached'] is True
    assert result['process_supervision']['forced_stop'] is True
    assert result['process_supervision']['owned_group_gone'] is True
    assert result['process_supervision']['leader_reaped'] is True
    assert result['request_accounting']['client_requests_started']==3
    assert result['request_accounting']['completed_http_responses']==2
    assert result['request_accounting']['unresolved_requests']==1
    assert result['cumulative_accounting']['charged']==38
    assert result['cumulative_accounting']['unresolved']==3
    assert 'synthetic-private-token' not in json.dumps(result)
    async def no_late_write():await asyncio.sleep(.1)
    asyncio.run(no_late_write())
    assert not (directory/'late-write').exists()
    signals=directory/'signals.json'
    assert len(json.loads(signals.read_text()))<=1 if signals.exists() else True


def test_completed_process_is_reaped_before_receipt_return(tmp_path):
    directory,value=payload(tmp_path,'complete')
    result=asyncio.run(mode._supervise([sys.executable,'-B','-c',CHILD],value,directory,
        execution_seconds=2,cleanup_seconds=.4,stop_grace=.1))
    assert result['status']=='observation' and result['cleanup_complete'] is True
    assert result['process_supervision']['forced_stop'] is False
    assert result['process_supervision']['owned_group_gone'] is True
    assert result['process_supervision']['leader_reaped'] is True


@pytest.mark.parametrize('case',['cleanup_hang','timeout_hang'])
def test_parent_cancellation_is_not_success_and_does_not_renew_cleanup(tmp_path,case):
    directory,value=payload(tmp_path,case)
    async def scenario():
        task=asyncio.create_task(mode._supervise([sys.executable,'-B','-c',CHILD],value,directory,
            execution_seconds=2,cleanup_seconds=.4,stop_grace=.1))
        while not (directory/'receipt.json').exists() and not task.done():await asyncio.sleep(.01)
        assert (directory/'receipt.json').exists()
        task.cancel()
        await asyncio.sleep(.05)
        task.cancel()
        return await task
    started=time.monotonic()
    result=asyncio.run(scenario())
    assert time.monotonic()-started<4
    assert result['status']=='incomplete' and result['cancelled'] is True
    assert result['observation']['outcome']==('worker_timeout' if case=='timeout_hang' else 'cancelled')
    assert result['process_supervision']['owned_group_gone'] is True
    assert len(json.loads((directory/'signals.json').read_text()))==1


@pytest.mark.parametrize('state',['held','stale','available','wrong_parent'])
def test_child_requires_exact_parent_identity_and_held_existing_lease(tmp_path,monkeypatch,state):
    path=tmp_path/'synthetic-lease'
    parent=os.getppid()
    path.write_text(json.dumps({'run_id':'run' if state!='stale' else 'other','pid':parent}))
    calls=[]
    def lock(fd,flags):
        calls.append(flags)
        if state=='held':raise BlockingIOError()
    monkeypatch.setattr(mode.fcntl,'flock',lock)
    if state=='held':mode._require_parent_lease({'run_id':'run'},parent,path=path)
    else:
        with pytest.raises(ValueError):
            mode._require_parent_lease({'run_id':'run'},parent if state!='wrong_parent' else parent+1,path=path)
    assert len(calls)==(1 if state in {'held','available'} else 0)


@pytest.mark.parametrize('damage',['none','partial_tail','duplicate_start','fifth'])
def test_hard_stop_accounting_recovers_three_sends_without_refunding_uncertain_tail(tmp_path,damage):
    plan={'run_id':'run','source_revision':'a'*40}
    journal=tmp_path/'journal';journal.mkdir()
    events=[{'event':'created',**plan}]
    for ordinal in range(1,4):
        events.extend([{'event':'send_reserved','ordinal':ordinal,'reserved_at_monotonic':100+ordinal},
            {'event':'send_started','ordinal':ordinal,'started_at_monotonic':101+ordinal}])
        if ordinal<=2:events.append({'event':'http_response_completed','ordinal':ordinal,
            'completed_at_monotonic':102+ordinal,'elapsed_ms':1000,'status_code':200})
    if damage=='duplicate_start':events.append({'event':'send_started','ordinal':3})
    if damage=='fifth':events.append({'event':'send_reserved','ordinal':5})
    raw=''.join(json.dumps(event)+'\n' for event in events)
    if damage=='partial_tail':raw+='{"event":"send_started"'
    (journal/'run.jsonl').write_text(raw)
    result=mode._journal_accounting(tmp_path,plan)
    if damage=='none':
        assert result['client_requests_started']==3 and result['completed_http_responses']==2
        assert result['unresolved_requests']==1 and result['restart_allowed'] is False
        assert len(result['attempts'])==3
        assert result['attempts'][0]['completed_at_monotonic']==103
        assert result['attempts'][2]['started_at_monotonic']==104
        assert result['journal_durability_verified'] is False
    else:assert result is None


def test_receipt_reader_refuses_symlink_and_other_run_identity(tmp_path):
    plan={'run_id':'run','source_revision':'a'*40}
    target=tmp_path/'synthetic-other-receipt'
    target.write_text(json.dumps({**plan,'status':'observation'}))
    (tmp_path/'receipt.json').symlink_to(target)
    assert mode._read_receipt(tmp_path,plan)=={}
    (tmp_path/'receipt.json').unlink()
    (tmp_path/'receipt.json').write_text(json.dumps({**plan,'run_id':'other'}))
    assert mode._read_receipt(tmp_path,plan)=={}


def test_pipe_failure_still_settles_owned_child_and_reports_uncertain_charges(tmp_path,monkeypatch):
    directory,value=payload(tmp_path,'setup_hang')
    def unavailable(*args):raise OSError('SYNTHETIC_PRIVATE_FAILURE')
    monkeypatch.setattr(mode.os,'write',unavailable)
    result=asyncio.run(mode._supervise([sys.executable,'-B','-c',CHILD],value,directory,
        execution_seconds=.4,cleanup_seconds=.4,stop_grace=.1))
    assert result['status']=='incomplete' and result['supervisor_failed'] is True
    assert result['process_supervision']['owned_group_gone'] is True
    assert result['process_supervision']['leader_reaped'] is True
    assert result['accounting_verified'] is False
    assert result['cumulative_accounting']['charged_upper_bound']==39
    assert 'SYNTHETIC_PRIVATE_FAILURE' not in json.dumps(result)
