"""Collector flow contract through the production runtime with controlled models."""
import asyncio
from copy import deepcopy
import json
from uuid import uuid4

import pytest

from apps.api.agent_storage import UserStorage
from apps.api.codex_runtime import CodexRuntime
from test_interview_plan import CONTEXT, proposal


class Storage(UserStorage):
    def __init__(self):
        self.user_id='11111111-1111-4111-8111-111111111111';self.turn=None;self.memory=None;self.rounds=0;self.saved_plan=None;self.failed_commit=False
    def acquire_agent_turn_lease(self,*args):return True
    def renew_agent_turn_lease(self,*args):return True
    def release_agent_turn_lease(self,*args):return True
    def agent_turn_by_id(self,*args):return self.memory
    def accept_interview_turn(self,project_id,turn_id,text,**kwargs):
        if self.turn is None:
            self.turn={'source':deepcopy(CONTEXT['source']) if text else None,'photo_context':deepcopy(CONTEXT['photo_context']),
                       'consumed_photo_key':'https://images.example/one.jpg','consumed_photo_revision':'cue-1','client_turn_id':turn_id,'sequence':1}
        return deepcopy(self.turn)
    def interview_context(self,*args):return deepcopy(CONTEXT)
    def interview_turn_by_id(self,*args):return deepcopy(self.turn)
    def memory_events(self,*args):return {'sources':deepcopy(CONTEXT['sources']),'events':[]}
    def agent_session(self):return None
    def memories(self):return []
    def profile(self):return {'preferred_language':'zh-CN','conversation_locale':{'locale':'zh-CN'}}
    def first_narrator_reply(self):return None
    def save_profile(self,*args,**kwargs):return None
    def place_journey(self):return None
    def story_entitlement(self):return None
    def recall_rounds_completed(self):return self.rounds
    def save_interview_plan(self,project,turn,plan,associations,lease,**kwargs):
        self.saved_plan=deepcopy(plan);self.turn.update(plan=deepcopy(plan),**kwargs);return deepcopy(self.turn)
    def commit_agent_turn(self,lease,thread,text,paths,**kwargs):
        if self.failed_commit:self.failed_commit=False;raise RuntimeError('controlled lost database response')
        self.rounds+=int(kwargs.get('user_response',False))
        self.memory={'id':str(uuid4()),'content':text,'source_sequence':1}
        return self.memory


def harness(monkeypatch,storage):
    runtime=CodexRuntime(worker_url='http://controlled-worker',worker_secret='synthetic');calls=[]
    async def worker(**kwargs):
        calls.append(kwargs)
        result=proposal()
        if not kwargs['text']:result['associations']=[]
        raw=json.dumps(result,ensure_ascii=False)
        if kwargs.get('on_delta'):
            for offset in range(0,len(raw),7):await kwargs['on_delta'](raw[offset:offset+7])
        return {'thread_id':'thread-1','reply':raw,'_workspace_capable':True}
    async def noop(*args,**kwargs):return None
    async def workspace(*args,**kwargs):
        return {'place_journey':None,'place_journey_change':None,'family_context':None,'family_context_update':None,'tasks':[],'task_errors':[],'source_paths':[]}
    monkeypatch.setattr(runtime,'_worker_turn',worker);monkeypatch.setattr(runtime,'_workspace_extraction',noop)
    monkeypatch.setattr(runtime,'_enqueue_workspace_intent',noop);monkeypatch.setattr(runtime,'_resume_pending_workspace',noop);monkeypatch.setattr(runtime,'_run_workspace_job',workspace)
    return runtime,calls


def test_accepted_cue_stream_and_saved_private_plan(monkeypatch):
    storage=Storage();runtime,calls=harness(monkeypatch,storage);events=[];deltas=[]
    async def on_event(value):events.append(value)
    async def on_delta(value):deltas.append(value)
    result=asyncio.run(runtime.turn(storage,CONTEXT['source']['text'],project_id='project',client_turn_id=str(uuid4()),on_event=on_event,on_delta=on_delta))
    assert next(e for e in events if e['type']=='source_accepted')['data']['photo_cue']=={'consumed':True,'key':'https://images.example/one.jpg','revision':'cue-1'}
    assert result['reply']==''.join(deltas)
    assert result['reply'].count('？')==1 and 'candidates' not in ''.join(deltas)
    assert storage.saved_plan['chosen_id']=='parents'
    assert 'plan' not in result and 'associations' not in result
    assert calls[0]['interview_context']['source']['text']==CONTEXT['source']['text']
    saved=next(e['data'] for e in events if e['type']=='conversation_saved')
    assert saved['response_photos']==result['response_photos']


def test_retry_after_generated_plan_preserves_same_question_without_model_reexecution(monkeypatch):
    storage=Storage();runtime,calls=harness(monkeypatch,storage);storage.failed_commit=True;turn=str(uuid4())
    with pytest.raises(RuntimeError):asyncio.run(runtime.turn(storage,CONTEXT['source']['text'],project_id='project',client_turn_id=turn))
    assert storage.turn.get('reply')
    result=asyncio.run(runtime.turn(storage,CONTEXT['source']['text'],project_id='project',client_turn_id=turn))
    assert len(calls)==1 and storage.rounds==1
    assert result['reply']==storage.turn['reply']


def test_photo_only_does_not_create_narrator_round(monkeypatch):
    storage=Storage();runtime,calls=harness(monkeypatch,storage)
    result=asyncio.run(runtime.turn(storage,'',project_id='project',client_turn_id=str(uuid4()),uploaded_photo_ids=[str(uuid4())]))
    assert result['accepted_source_id'] is None and storage.rounds==0
    assert result['response_photos']


def test_private_collector_contract_is_identical_for_local_and_remote_execution(tmp_path,monkeypatch):
    from apps.api.codex_worker_service import CodexWorker, WorkerTurnInput
    from apps.api.interview_plan import collector_schema
    observed=[]
    class Connection:
        def __init__(self,*a,**kw):pass
        async def __aenter__(self):return self
        async def __aexit__(self,*a):pass
        async def request(self,method,params):
            observed.append(params['baseInstructions'])
            return {'thread':{'id':'local-thread'}}
        async def turn(self,thread,prompt,**kwargs):
            assert kwargs['output_schema']==collector_schema()
            raw=json.dumps(proposal(),ensure_ascii=False)
            if kwargs.get('on_delta'):await kwargs['on_delta'](raw)
            return raw
    monkeypatch.setattr('apps.api.codex_runtime.CodexConnection',Connection)
    monkeypatch.setattr('apps.api.codex_worker_service.CodexConnection',Connection)
    storage=Storage();runtime,_=harness(monkeypatch,storage)
    runtime.worker_url=None;monkeypatch.setattr(runtime,'_home',lambda *a:tmp_path)
    result=asyncio.run(runtime.turn(storage,CONTEXT['source']['text'],project_id='project',client_turn_id=str(uuid4())))
    worker=CodexWorker(home_root=tmp_path/'worker')
    monkeypatch.setattr(worker,'_home',lambda *a:tmp_path)
    monkeypatch.setattr('apps.api.codex_worker_service.iter_artifacts',lambda *a,**kw:[])
    remote=asyncio.run(worker.turn(WorkerTurnInput(user_id=storage.user_id,project_id='project',text=CONTEXT['source']['text'],
                  interview_context=CONTEXT,language='zh-CN')))
    assert json.loads(remote['reply'])==proposal()
    assert 'candidates' not in result['reply'] and result['reply'].count('？')==1
    assert all('Private structured interview contract' in prompt for prompt in observed)
