"""Authenticated HTTP → collector → real SQL → canonical event → memoir seam.

Only authentication exchange, external models and optional enrichment are
controlled. Run with native PostgreSQL for policy enforcement. The explicit
single-user fallback exercises real persistence, never claims RLS acceptance.
"""
import asyncio
import base64
from copy import deepcopy
import json
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from apps.api import agent_routes
from apps.api.agent_storage import UserStorage
from apps.api.codex_runtime import CodexRuntime
from apps.api.canonical_composer import composer_request
from test_interview_photos_postgres import database, upload
from test_guest_conversation_transfer import attachment_database
from test_private_rounds_postgres import private_database
from test_shared_memory_events_postgres import event_database, sql, rpc, literal, extract, OWNER, as_user


class SqlStorage(UserStorage):
    def __init__(self, sql):
        self.sql=sql;self.user_id=OWNER;self.client=SimpleNamespace(close=lambda:None)
    def call(self,name,arguments):
        return rpc(self.sql,name,arguments)
    def row(self,table,where='true'):
        result=self.sql(as_user(f"select coalesce((select to_jsonb(t) from public.{table} t where user_id='{OWNER}' and {where} limit 1),'null'::jsonb);"))
        return json.loads(result.stdout.splitlines()[-1])
    def request(self,method,path,**kwargs):
        assert path.startswith('/rest/v1/rpc/'), path
        args=[]
        for name,value in (kwargs.get('json') or kwargs.get('params') or {}).items():
            if value is None: rendered='null'
            elif name=='p_source_paths':rendered='array['+','.join(literal(x) for x in value)+']::text[]'
            elif isinstance(value,(dict,list)):rendered=literal(value)+'::jsonb'
            elif isinstance(value,bool):rendered='true' if value else 'false'
            elif isinstance(value,int):rendered=str(value)
            else:rendered="convert_from(decode('"+base64.b64encode(str(value).encode()).decode()+"','base64'),'UTF8')" if '\n' in str(value) else literal(value)
            args.append(name+'=>'+rendered)
        value=self.call(path.rsplit('/',1)[-1],','.join(args))
        return httpx.Response(200,json=value,request=httpx.Request(method,'http://disposable-sql.test'+path))
    def agent_turn_by_id(self,project,turn):return self.row('user_memory',f"project_id={literal(project)} and client_turn_id={literal(turn)}")
    def narrator_source_by_turn(self,project,turn):return self.row('user_narrator_source',f"project_id={literal(project)} and client_turn_id={literal(turn)}")
    def completed_round_by_turn(self,project,turn):return self.row('user_completed_round',f"project_id={literal(project)} and turn_id={literal(turn)}")
    def agent_session(self):return self.row('user_agent_session')
    def memories(self):return []
    def profile(self):return (self.row('user_profile') or {}).get('profile',{})
    def save_profile(self,profile,**kwargs):
        self.sql(as_user(f"insert into public.user_profile(user_id,profile) values('{OWNER}',{literal(profile)}::jsonb) on conflict(user_id) do update set profile=excluded.profile;"))
    def first_narrator_reply(self):return self.row('user_narrator_source')
    def place_journey(self):return None
    def story_entitlement(self):return None
    def recall_rounds_completed(self):return (self.row('user_recall_usage') or {}).get('rounds_completed',0)


@pytest.fixture
def client(sql,monkeypatch):
    storage=SqlStorage(sql); storage.save_profile({'preferred_language':'zh-CN'})
    runtime=CodexRuntime(worker_url='http://controlled-model.test',worker_secret='synthetic')
    calls=[]
    async def collector(**kwargs):
        context=kwargs['interview_context'];source=context['source'];photos=context.get('photo_context') or context.get('photos',[])
        text=source['text'] if source else '';photo=photos[0] if photos else None
        visits=next((e for e in context['events'] if e['title']=='Childhood gate visits'),None)
        chinese=kwargs.get('language') == 'zh-CN'
        recognizing='照片' in text or 'recognise' in text
        discussing=recognizing or '爸爸妈妈' in text or 'my parents' in text
        event_id=visits['id'] if visits and discussing else None
        question=('那时您通常和谁一起去？' if recognizing else '那次游览还让您记得什么？' if discussing else '您把捉到的虫子放在哪里？') if chinese else ('Who usually visited with you?' if recognizing else 'What else do you remember about those visits?' if discussing else 'Where did you keep the insects?')
        p={'acknowledgement':('您确认照片拍的是丽正门，并回忆起小时候去离宫。' if recognizing else '您记得和爸爸妈妈一起去游览。' if discussing else '您提到小时候捉虫子的经历。') if chinese else ('You recognise Lizheng Gate in the photo and recall your childhood visits.' if recognizing else 'You remember visiting with your parents.' if discussing else 'You caught insects as a child.'),
           'plan':{'candidates':[
               {'id':'current','question':question,'context':{'event_id':event_id,'photo_id':photo['photo_id'] if photo and discussing else None,'life_stage':None,'year':None},'order':0,'bridge':''},
               {'id':'deferred-photo','question':'这张照片让您想起了什么？','context':{'event_id':None,'photo_id':photo['photo_id'] if photo else None,'life_stage':None,'year':None},'order':1,'bridge':'您先前选了一张照片。'}],
               'chosen_id':'current','active_event_id':event_id},
           'associations':[], 'response_photo_ids':[photo['photo_id']] if photo else [],'stopped':False}
        if recognizing:
            p['associations']=[{'photo_id':photo['photo_id'],'event_id':None,'source_id':source['id'],'source_version':source['version'],
                 'quote':source['text'],'description':'您确认照片拍的是丽正门，并记起小时候常去离宫。','provenance':'narrator_metadata'}]
        calls.append(deepcopy(context));return {'thread_id':'controlled-thread','reply':json.dumps(p,ensure_ascii=False),'_workspace_capable':True}
    async def noop(*a,**kw):return None
    async def workspace(*a,**kw):return {'place_journey':None,'place_journey_change':None,'family_context':None,'family_context_update':None,'tasks':[],'task_errors':[],'source_paths':[]}
    monkeypatch.setattr(runtime,'_worker_turn',collector)
    for name in ['_enqueue_workspace_intent','_resume_pending_workspace','_workspace_extraction']:monkeypatch.setattr(runtime,name,noop)
    monkeypatch.setattr(runtime,'_run_workspace_job',workspace)
    monkeypatch.setattr(agent_routes,'runtime',runtime)
    def authenticated(header):
        if header!='Bearer synthetic-owner':raise HTTPException(401,'Sign in required')
        return storage
    monkeypatch.setattr(agent_routes,'authenticated_storage',authenticated)
    from apps.api.store import MemoryStore
    app=FastAPI();app.state.store=MemoryStore();app.include_router(agent_routes.router)
    with TestClient(app) as client:yield client,storage,calls


def submit(client,text,**options):
    turn=options.pop('client_turn_id',str(uuid4()))
    response=client.post('/v1/agent/turn',headers={'Authorization':'Bearer synthetic-owner'},json={
        'project_id':'project','text':text,'conversation_text':text,'client_turn_id':turn,**options})
    assert response.status_code==200,response.text
    return turn,response.json()


@pytest.mark.parametrize('kind',['narrator_chat','narrator_transcript'])
@pytest.mark.parametrize('locale',['zh-CN','en-AU'])
def test_recognized_photo_continuation_evidence_and_memoir_projection(client,sql,kind,locale):
    http,storage,calls=client
    photo={'key':'https://example.org/gate.jpg','image_url':'https://example.org/gate.jpg','title':'Generic archive title'}
    storage.save_profile({'preferred_language':locale,'photo_memories':{'project':{'favorites':[photo],'selected':photo['key'],'selection_revision':'cue-1'}}})
    first_text=('小时候还经常去离宫，这张照片就是丽正门的照片' if locale=='zh-CN' else
        'I often visited the palace as a child, and I recognise Lizheng Gate in this photo.')
    first,reply=submit(http,first_text,source_kind=kind,photo_selection={'key':photo['key'],'revision':'cue-1'})
    assert reply['photo_cue']=={'consumed':True,'key':photo['key'],'revision':'cue-1'}
    assert reply['reply'].count('？' if locale=='zh-CN' else '?')==1
    assert ('丽正门' if locale=='zh-CN' else 'Lizheng Gate') in reply['reply']
    assert 'plan' not in reply and 'candidates' not in reply['reply']
    assert storage.profile()['photo_memories']['project']=={'favorites':[photo],'selected':None,'selection_revision':'cue-1'}
    source=storage.narrator_source_by_turn('project',first)
    assert source['text']==first_text and source['kind']==kind and source['version']==1
    ref={'source_id':source['id'],'version':1,'quote':first_text}
    visit=extract(sql,[source],[{'kind':'event','title':'Childhood gate visits','source_refs':[ref]}])['events'][0]
    assert len(visit['photo_associations'])==1
    second_text=('大概是6、7岁以后搬到市区后我和爸爸妈妈经常去离宫。之前住在大石庙，爸爸学校也就是承德师范学校的家属院里' if locale=='zh-CN' else
        'After moving into the city at about six or seven, I often visited the palace with my parents. Before that I lived in Dashimiao, in the teachers housing at Chengde Normal School where my father worked.')
    visit_quote='我和爸爸妈妈经常去离宫' if locale=='zh-CN' else 'I often visited the palace with my parents'
    move_quote='6、7岁以后搬到市区' if locale=='zh-CN' else 'moving into the city at about six or seven'
    residence_quote='之前住在大石庙，爸爸学校也就是承德师范学校的家属院里' if locale=='zh-CN' else 'Before that I lived in Dashimiao, in the teachers housing at Chengde Normal School where my father worked'
    second,later=submit(http,second_text,source_kind=kind)
    assert later['response_photos'][0]['photo_id']==reply['response_photos'][0]['photo_id']
    later_source=storage.narrator_source_by_turn('project',second)
    ref2={'source_id':later_source['id'],'version':1,'quote':visit_quote}
    view=extract(sql,[later_source],[
        {'kind':'event','existing_id':visit['id'],'expected_revision':visit['revision'],'title':visit['title'],'source_refs':[ref2]},
        {'kind':'event','title':'Moved into the city','source_refs':[{'source_id':later_source['id'],'version':1,'quote':move_quote}]},
        {'kind':'event','title':'Earlier residence','source_refs':[{'source_id':later_source['id'],'version':1,'quote':residence_quote}]}])
    assert len(view['events'])==3
    assert [e['id'] for e in view['events'] if e['photo_associations']]==[visit['id']]
    packet={'project_id':'project','sources':view['sources'],'events':view['events'],'locale':locale,'policy_epoch':storage.row('user_memoir_project')['policy_epoch'],
        'base_revision':0,'coverage_round':5,'previous':None,'source_manifest':[{'id':s['id'],'version':s['version']} for s in view['sources']],
        'event_manifest':[{'id':e['id'],'revision':e['revision']} for e in view['events']]}
    assert composer_request(packet)['context']['photo_associations'][0]['quote']==first_text
    receipt=http.get(f'/v1/agent/turns/{first}',params={'project_id':'project'},headers={'Authorization':'Bearer synthetic-owner'}).json()
    assert receipt['state']=='conversation_saved' and receipt['reply']==reply['reply']
    assert receipt['response_photos']==reply['response_photos']
    assert len(calls)==2


def test_selected_undiscussed_photo_is_deferred_without_false_event(client,sql):
    http,storage,calls=client;photo=upload(sql)
    turn,result=submit(http,'小时候我喜欢在大门旁捉虫子。',uploaded_photo_ids=[photo['id']])
    assert '虫子' in result['reply'] and result['response_photos'][0]['kind']=='private_upload'
    saved=storage.interview_context('project')
    assert saved['photo_associations']==[]
    assert any(c['context']['photo_id']=='upload:'+photo['id'] for c in saved['plan']['candidates'])
    before=len(calls)
    _,replayed=submit(http,'小时候我喜欢在大门旁捉虫子。',client_turn_id=turn)
    assert replayed['reply']==result['reply'] and len(calls)==before
