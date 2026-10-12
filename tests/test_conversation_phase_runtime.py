"""Streamed production collector orchestration with controlled provider only."""
import asyncio
from copy import deepcopy
from uuid import uuid4
import pytest
from apps.api.conversation_phase import PhaseState
from apps.api.interview_plan import validate_collector_result
from test_name_only_opening import Storage as BaseStorage, harness, proposal


class Storage(BaseStorage):
    def __init__(self,state=None):
        super().__init__(); self.phase=state or PhaseState().model_dump(mode='json')
    def interview_context(self,project): return {'conversation_phase':deepcopy(self.phase)}


@pytest.mark.parametrize('language,text,question',[('en-AU','My name is Joan','What would you enjoy talking about?'),('zh-CN','我叫韩凤江','您想先聊些什么？')])
def test_name_only_stream_is_gentle_and_has_one_collector(monkeypatch,tmp_path,language,text,question):
    storage=Storage(); name='Joan' if language=='en-AU' else '韩凤江'
    response=proposal(name=name,question=question); response['plan']['conversation_phase']='comfort'
    runtime,calls=harness(monkeypatch,tmp_path,storage,response,'worker')
    packets=[]; chunks=[]
    async def event(value): packets.append(value)
    async def delta(value): chunks.append(value)
    result=asyncio.run(runtime.turn(storage,text,project_id='project',client_turn_id=str(uuid4()),on_event=event,on_delta=delta))
    assert len(calls)==1 and question in result['reply'] and ''.join(chunks)==result['reply']
    assert storage.saved_plan['phase_update']=={'expected_revision':0,'phase':None}
    assert calls[0]['interview_context']['conversation_phase']['phase']=='comfort'


@pytest.mark.parametrize('text',['hello','继续','Actually, the year was 1966.'])
def test_continuing_or_correcting_never_requires_a_resume_action(text):
    state=PhaseState(phase='shape',selection='explicit',preferred_phase='shape')
    response=proposal(name=None);response['plan']['conversation_phase']=None
    context={'conversation_phase':state.model_dump(mode='json'),'source':{'id':str(uuid4()),'version':1,'status':'active','text':text}}
    assert validate_collector_result(response,context)['reply']


def test_model_cannot_create_explicit_choice():
    response=proposal(); response['plan']['conversation_phase']='shape'
    with pytest.raises(ValueError): validate_collector_result(response,{})


def test_collector_correction_cannot_propose_a_reset_to_comfort():
    state=PhaseState(phase='explore',revision=4,reason='narration')
    response=proposal('extract',name=None)
    response['plan']['conversation_phase']='comfort'
    context={'conversation_phase':state.model_dump(mode='json'),
        'source':{'id':str(uuid4()),'version':1,'status':'active','text':'Actually, school was in 1966.'}}
    validated=validate_collector_result(response,context)
    assert validated['plan']['work']['mode']=='extract'
    assert validated['plan']['phase_update']=={'expected_revision':4,'phase':None}

@pytest.mark.parametrize('language',['en-AU','zh-CN'])
@pytest.mark.parametrize('phase',['comfort','explore','shape'])
def test_returning_greeting_carries_saved_mode_without_accepting_a_new_round(monkeypatch,tmp_path,language,phase):
    from apps.api.conversation_phase import resolve_phase
    storage=Storage(resolve_phase(None,{'action':phase}).model_dump(mode='json'))
    storage.data={'preferred_language':language}
    storage.memoir_project=lambda _: {'project_id':'project'}
    storage.conversation_phase=lambda _: storage.phase
    response=proposal(name=None)
    runtime,calls=harness(monkeypatch,tmp_path,storage,response,'worker')
    result=asyncio.run(runtime.turn(storage,'The storyteller wants to continue with another memory.',project_id='project',user_response=False))
    assert len(calls)==1 and calls[0]['conversation_phase']==storage.phase
    assert calls[0].get('interview_context') is None
    assert storage.rounds==0 and storage.phase['phase']==phase
