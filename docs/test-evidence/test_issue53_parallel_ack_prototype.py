import asyncio
import importlib.util
import json
from pathlib import Path
import sys
REPO = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(REPO), str(REPO / 'tests')]
from test_lifetime_memory_engine import fixture, valid_reply, FakePublisher, BUDGET
from apps.api import lifetime_memory_engine as engine
spec=importlib.util.spec_from_file_location('prototype',str(Path(__file__).with_name('issue53-parallel-ack-prototype.py')))
p=importlib.util.module_from_spec(spec)
spec.loader.exec_module(p)

def test_worker_completion_uses_the_acknowledgement_already_streamed(tmp_path,monkeypatch):
    monkeypatch.setenv('MEMOIR_LIFETIME_MEMORY','true')
    async def scenario():
        early=asyncio.Event()
        new='Thank you for sharing this memory.'
        class Connection:
            def __init__(self,*args,**options):pass
            async def __aenter__(self):return self
            async def __aexit__(self,*args):pass
            async def request(self,method,params):return {'thread':{'id':'ack'}}
            async def turn(self,thread,prompt,**options):
                raw=json.dumps({'acknowledgement':new})
                await options['on_delta'](raw);early.set();return raw
        async def full(**options):
            await early.wait()
            raw=valid_reply()
            await options['on_delta'](json.dumps({'acknowledgement':json.loads(raw)['acknowledgement']}))
            await options['on_event']({'type':'provider_complete','data':{'thread_id':'full','reply':raw}})
            return {'thread_id':'full','reply':raw}
        monkeypatch.setattr(p,'CodexConnection',Connection)
        monkeypatch.setattr(p,'ProviderPublication',lambda *args,**kw:FakePublisher())
        monkeypatch.setattr(p,'original_run',full)
        governed,context=fixture();visible=[];events=[]
        async def delta(chunk):visible.append(json.loads(chunk)['acknowledgement'])
        async def event(value):events.append(value)
        result=await p.run_with_parallel_ack(governed=governed,interview_context=context,model=BUDGET.model,
            command=['fake'],api_key='synthetic',base_url='http://invalid',home_root=tmp_path,on_delta=delta,on_event=event,effort='max')
        assert visible==[new]
        assert json.loads(result['reply'])['acknowledgement']==new
        assert events[-1]['data']['reply']==result['reply']
    asyncio.run(asyncio.wait_for(scenario(),3))
