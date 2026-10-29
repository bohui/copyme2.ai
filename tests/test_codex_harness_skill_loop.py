"""Actual installed Codex harness with a loopback scripted Responses provider."""
import asyncio
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import shutil
import threading
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from apps.api.memoir_skill_agent import run_skill_agent
from apps.api.prompt_artifact import load_prompt_artifact, prompt_path
from test_memoir_skill_agent import Publication


@pytest.mark.skipif(not shutil.which('codex'), reason='Codex app-server is not installed')
@pytest.mark.parametrize('background', [False, True])
def test_native_codex_runs_tool_loop_and_receives_real_skill_instructions(tmp_path,monkeypatch,background):
    from apps.api import llm_tracing
    from test_gateway_trace_correlation import ApplicationTracer
    tracer=ApplicationTracer()
    monkeypatch.setattr(llm_tracing,'_client_cache',tracer)
    requests=[]
    parents=[]
    class Provider(BaseHTTPRequestHandler):
        def log_message(self,*args):
            pass

        def do_POST(self):
            if self.headers.get('Transfer-Encoding')=='chunked':
                chunks=[]
                while True:
                    size=int(self.rfile.readline().strip(),16)
                    if not size:
                        self.rfile.readline()
                        break
                    chunks.append(self.rfile.read(size))
                    self.rfile.read(2)
                raw=b''.join(chunks)
            else:
                raw=self.rfile.read(int(self.headers['Content-Length']))
            body=json.loads(raw)
            requests.append(body)
            parents.append(self.headers.get('traceparent'))
            schema=body.get('text',{}).get('format',{}).get('schema')
            if schema and schema['properties']['status'].get('type')!='string':
                # The real Responses provider rejects an untyped const before inference.
                error=json.dumps({'error':{'message':'status schema must have a type key',
                    'type':'invalid_request_error','code':'invalid_json_schema'}}).encode()
                self.send_response(400)
                self.send_header('Content-Type','application/json')
                self.send_header('Content-Length',str(len(error)))
                self.end_headers()
                self.wfile.write(error)
                return
            ordinal=len(requests)
            if ordinal==1:
                output={'type':'function_call','id':'fc_read','call_id':'read-skill',
                    'name':'memoir_read_skill','arguments':json.dumps({'skill':'memoir-interview-guidance'}),
                    'status':'completed'}
            else:
                output={'type':'message','id':'message','role':'assistant','status':'completed',
                    'content':[{'type':'output_text','text':'{"status":"finished"}','annotations':[]}]}
            response={'id':f'resp_{ordinal}','object':'response','status':'completed',
                'model':'gpt-6.1-sol','output':[output],
                'usage':{'input_tokens':100,'output_tokens':20,'total_tokens':120}}
            events=[{'type':'response.created','response':{**response,'status':'in_progress','output':[]}},
                {'type':'response.output_item.added','output_index':0,'item':output},
                {'type':'response.output_item.done','output_index':0,'item':output},
                {'type':'response.completed','response':response}]
            wire=''.join('data: '+json.dumps(event)+'\n\n' for event in events).encode()
            self.send_response(200)
            self.send_header('Content-Type','text/event-stream')
            self.send_header('Content-Length',str(len(wire)))
            self.end_headers()
            self.wfile.write(wire)

    server=ThreadingHTTPServer(('127.0.0.1',0),Provider)
    thread=threading.Thread(target=server.serve_forever,daemon=True)
    thread.start()
    try:
        if background:
            from apps.api.codex_worker_service import CodexWorker, WorkerTurnInput
            from apps.api.memoir_background_agent import run_background_agent
            from test_memoir_background_agent import fence
            monkeypatch.setenv('MEMORY_SPARK_DISABLE_PRIVDROP','1')
            monkeypatch.setenv('MEMORY_SPARK_LLM_MODEL','gpt-6.1-sol')
            monkeypatch.setenv('MEMORY_SPARK_MEMOIR_COMPOSER_MODEL','gpt-6.1-sol')
            current=fence()
            worker=CodexWorker(home_root=tmp_path / 'homes',command=[shutil.which('codex'),'app-server'],
                base_url=f'http://127.0.0.1:{server.server_port}/v1',api_key='synthetic-loopback-key')
            broker=SimpleNamespace(rpc=AsyncMock(return_value={
                'lanes':[{'id':'guidance-id','skill':'guidance'}],'selection':None}))
            payload=WorkerTurnInput(user_id=current['user_id'],project_id=current['project_id'],
                agent_role='background_agent',background_agent=current)
            result=asyncio.run(run_background_agent(worker,payload,publisher=Publication(),broker=broker))
        else:
            result=asyncio.run(run_skill_agent(command=[shutil.which('codex'),'app-server'],
                home_root=tmp_path / 'homes',base_url=f'http://127.0.0.1:{server.server_port}/v1',
                api_key='synthetic-loopback-key',model='gpt-6.1-sol',
                instructions=load_prompt_artifact(prompt_path('memoir/shared/background-agent')),
                packet={'lane':'B','work':[]},skills=['memoir-interview-guidance'],
                publisher=Publication(),fence={},timeout=20,effort='low'))
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
    assert json.loads(result['reply'])=={'status':'finished'}
    assert len(requests)==2
    assert all('<skills_instructions>' not in json.dumps(request.get('input',[])) for request in requests)
    observation,=tracer.observations
    assert parents==[f'00-{observation.trace_id}-{observation.id}-01']*2
    assert not any(tool.get('type') in {'web_search','web_search_preview'} for tool in requests[0].get('tools',[]))
    assert result['skill_receipt']['skills_read']==['memoir-interview-guidance']
    artifacts={item['name'] for item in result['skill_receipt']['prompt_manifest']['artifacts']}
    assert {'memoir/shared/skill-agent','memoir/shared/background-agent',
        'memoir/skills/memoir-interview-guidance/instructions'}<=artifacts
    # The second inference contains the actual tool result, not just a skill label.
    assert '# Memoir Interview Guidance' in json.dumps(requests[1],ensure_ascii=False)
