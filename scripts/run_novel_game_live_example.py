"""Opt-in paid age-eight replay through real selection/API/SQL/worker/model boundaries."""
import argparse
import asyncio
from contextlib import closing,contextmanager
import hashlib
import sys
import tempfile
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import json
import os
from pathlib import Path
import socket
import threading
import time

import httpx
import pytest
from playwright.sync_api import sync_playwright,expect
import uvicorn

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
sys.path.insert(0,str(ROOT/'tests'))

from apps.api import novel_game,story_game_routes,memory_event_worker
from test_agent_commit_postgres import database as base_database,OWNER,ProcessDeadline
from test_lifetime_memory_postgres import attachment_database,private_database,event_database
from test_shared_memory_events_postgres import sql,rpc,literal
from test_conversation_attribution import Conversation,empty,episode
from test_story_game_runtime_postgres import compose_game_chapters
from test_formal_memoir_postgres import completed,consent,service
from memoir_postgres_workflow import PostgresRest
from test_background_profile_workflow import Broker

def run(sql,tmp_path,monkeypatch,output,env_file,*,resume=False,prepare_only=False):
    monkeypatch.setenv('MEMORY_SPARK_TASK_DB',str(tmp_path/'receipts.sqlite3'))
    output=Path(output).resolve();output.mkdir(parents=True,exist_ok=True,mode=0o700)
    def status(phase):
        (output/'live-progress.json').write_text(json.dumps(dict(phase=phase))+'\n')
        print(json.dumps(dict(phase=phase)),flush=True)
    status('preparing-fictional-source')
    fixture=json.loads((ROOT/'skills/memoir-story-game/tests/fixtures/age-eight.json').read_text())['input']
    texts=['\n\n'.join(b['text'] for b in c['blocks']) for c in fixture['chapters']]
    titles={text:event['title'] for text,event in zip(texts,fixture['timeline'])}
    def extract(packet):
        text=packet['sources'][0]['text']; event=episode(packet,text,title=titles[text])
        event.update(life_stage='childhood',stage_evidence=event['source_refs'])
        return {**empty(packet),'events':[event]}
    conversation=Conversation(sql,tmp_path,monkeypatch,extract,strategy='shape')
    with conversation.client:
        if resume:
            conversation.project=sql('select project_id from public.user_story_game order by created_at desc limit 1;').stdout.strip()
            if not conversation.project:
                conversation.project=sql(f"select project_id from public.user_lifetime_conversation where user_id='{OWNER}';").stdout.strip()
            if not conversation.project: raise ValueError('No prepared fixture game to resume')
        else:
            for text in texts: conversation.say(text);conversation.drain()
            asyncio.run(compose_game_chapters(conversation))
            edition=completed(sql,conversation.project,{'revision':0});consent(sql,conversation.project,edition,1)
        status('source-ready')
        if prepare_only:
            count=int(sql('select count(*) from public.user_narrator_source;').stdout.strip())
            print(json.dumps(dict(status='SOURCE_READY',calls=0,source_chapters=count,project_id=conversation.project)),flush=True)
            return
        def storage(_): return PostgresRest(sql,OWNER).storage()
        monkeypatch.setattr(story_game_routes,'authenticated_storage',storage)
        class GameBroker(Broker):
            def __init__(self): super().__init__(sql);self.client=httpx.AsyncClient(trust_env=False)
            async def rpc(self,name,**parameters):
                value=await super().rpc(name,**parameters)
                return {**value,'fictional':True} if name=='read_story_game_input' else value
        monkeypatch.setattr(memory_event_worker,'MemoirLaneBroker',GameBroker)
        from apps.api.codex_worker_service import app as worker_app
        from dotenv import dotenv_values
        settings=dotenv_values(env_file,interpolate=False)
        for key in ('MEMORY_SPARK_LLM_BASE_URL','MEMORY_SPARK_LLM_API_KEY',
                'MEMORY_SPARK_LLM_MODEL','MEMORY_SPARK_LLM_REASONING_EFFORT',
                'MEMORY_SPARK_MEMOIR_COMPOSER_MODEL','MEMORY_SPARK_MEMOIR_COMPOSER_REASONING_EFFORT',
                'MEMOIR_GAME_MODEL','MEMOIR_GAME_REASONING_EFFORT','MEMOIR_GAME_IMAGE_MODEL',
                'MEMOIR_GAME_IMAGE_BASE_URL','MEMOIR_GAME_IMAGE_API_KEY'):
            if settings.get(key) is not None:
                monkeypatch.setenv(key,settings[key])
        original_model=novel_game.model_stage
        async def observed(body,fence,**options):
            stage=body['metadata']['stage']
            def record(kind,value):
                novel_game.assets.write_json(output,'model-observations/'+stage+'-'+kind+'.json',value)
            try:
                return await original_model(body,fence,observer=record,**options)
            except BaseException as error:
                record('failure',dict(type=type(error).__name__,reason=str(error)[:200]))
                raise
        monkeypatch.setattr(novel_game,'model_stage',observed)
        monkeypatch.setenv('MEMOIR_GAME_BUILDER','novel-to-game')
        monkeypatch.setenv('MEMORY_SPARK_CODEX_WORKER_SECRET','isolated-age-eight-worker')
        original=novel_game.run_novel_game
        async def retained(fence,**options):
            async def load(value): return {**await novel_game.load_build_packet(value),'fictional':True}
            try:
                return await original(fence,output=output,packet_loader=load,**options)
            except Exception as error:
                novel_game.assets.write_json(output,'build-failure.json',dict(type=type(error).__name__,reason=str(error)[:200]))
                raise
        monkeypatch.setattr(novel_game,'run_novel_game',retained)
        listener=socket.socket();listener.bind(('127.0.0.1',0));listener.listen()
        worker_port=listener.getsockname()[1]
        server=uvicorn.Server(uvicorn.Config(worker_app,log_level='warning',timeout_graceful_shutdown=2))
        worker_thread=threading.Thread(target=server.run,kwargs={'sockets':[listener]},daemon=True);worker_thread.start()
        monkeypatch.setenv('MEMORY_SPARK_CODEX_WORKER_URL','http://127.0.0.1:'+str(worker_port))
        deadline=time.monotonic()+10
        while not server.started and time.monotonic()<deadline: time.sleep(.05)
        assert server.started
        api_listener=socket.socket();api_listener.bind(('127.0.0.1',0));api_listener.listen()
        api_port=api_listener.getsockname()[1]
        api_server=uvicorn.Server(uvicorn.Config(conversation.client.app,log_level='warning',lifespan='off',timeout_graceful_shutdown=2))
        api_thread=threading.Thread(target=api_server.run,kwargs={'sockets':[api_listener]},daemon=True);api_thread.start()
        deadline=time.monotonic()+10
        while not api_server.started and time.monotonic()<deadline:time.sleep(.05)
        assert api_server.started
        project=conversation.project
        labels=json.loads((ROOT/'apps/web/messages/en-AU.json').read_text())
        html='''<!doctype html><html><head><link rel="stylesheet" href="/story-game.css"><style>body{font-family:system-ui;background:#faf6e9}iframe{height:780px;width:100%;border:0}.story-game-modal{width:min(1100px,95vw);max-height:95vh}.story-game-body{overflow:auto;max-height:85vh}</style></head><body><h1>Fictional age-eight live test</h1><button id="open">Story game</button><script type="module">import {createStoryGameDialog} from '/client/memoir/story-game.mjs';const labels=LABELS,scope={projectId:PROJECT};const dialog=createStoryGameDialog({state:{currentInterviewMode:{mode:'shape'}},captureProjectScope:()=>scope,isCurrentProjectScope:s=>s.projectId===scope.projectId,translate:key=>key.split('.').reduce((v,k)=>v?.[k],labels)||key,storyApi:async(path,options)=>{const r=await fetch(path,options);if(!r.ok)throw Error('API '+r.status);return r.json();}});document.querySelector('#open').onclick=()=>dialog.open(document.querySelector('#open'));</script></body></html>'''.replace('LABELS',json.dumps(labels)).replace('PROJECT',json.dumps(project))
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*_): pass
            def do_GET(self): self.handle_request()
            def do_POST(self): self.handle_request()
            def do_PUT(self): self.handle_request()
            def handle_request(self):
                path=self.path
                if path=='/': content,mime,status=html.encode(),'text/html',200
                elif path.startswith('/client/') or path=='/story-game.css':
                    file=ROOT/'apps/web'/path.lstrip('/') if path.startswith('/client/') else ROOT/'apps/web/public/story-game.css'
                    content,mime,status=file.read_bytes(),'text/javascript' if path.endswith('.mjs') else 'text/css',200
                elif path.startswith(('/v1/','/api/v1/memoir/')):
                    path=path.replace('/api/v1/memoir/','/v1/',1)
                    response=httpx.request(self.command,'http://127.0.0.1:'+str(api_port)+path,
                        headers={'Authorization':'Bearer isolated-owner','Content-Type':'application/json'},
                        content=self.rfile.read(int(self.headers.get('Content-Length',0))) or None,timeout=30,trust_env=False)
                    content,mime,status=response.content,response.headers.get('Content-Type','application/json'),response.status_code
                else: self.send_error(404);return
                self.send_response(status);self.send_header('Content-Type',mime);self.send_header('Content-Length',str(len(content)));self.end_headers();self.wfile.write(content)
        browser_server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        browser_thread=threading.Thread(target=browser_server.serve_forever,daemon=True);browser_thread.start()
        try:
            with sync_playwright() as p:
                browser=p.chromium.launch(headless=True);page=browser.new_page(viewport={'width':1280,'height':1000})
                page.goto('http://127.0.0.1:'+str(browser_server.server_port));page.locator('#open').click()
                status('preparing-scene-pool')
                page.locator('[data-generate-game], [data-scene-selection], iframe.story-game-frame').first.wait_for(state='visible',timeout=30000)
                if page.locator('iframe.story-game-frame').is_visible():
                    print(json.dumps(dict(status='REUSED_PUBLISHED_GAME',calls=0)),flush=True)
                    browser.close();return
                if page.locator('[data-generate-game]').is_visible():page.locator('[data-generate-game]').click()
                expect(page.locator('[data-scene-selection]')).to_be_visible(timeout=900000)
                defaults=page.locator('[data-scene-option]:checked').count();total=page.locator('[data-scene-option]').count()
                assert defaults>0 and total>=10
                if not resume:assert sql('select count(*) from public.user_story_game_stage;').stdout.strip()=='0'
                status('confirming-all-offered-scenes')
                job_status=rpc(sql,'read_story_game_status',literal(project));game_id=job_status['adaptation']['game_id']
                selected=rpc(sql,'read_story_game',f"{literal(project)},'{game_id}',false")
                recommended_count=sum(s['recommended'] for s in selected['pool']['scenes'])
                picture=output/('selection-confirmed.png' if selected.get('selected_scene_ids') else 'selection-defaults.png')
                if not picture.exists():page.screenshot(path=str(picture))
                (output/'pool.json').write_text(json.dumps(selected,indent=2)+'\n')
                assert defaults==(len(selected['selected_scene_ids']) if selected.get('selected_scene_ids') else
                    sum(s['recommended'] for s in selected['pool']['scenes']))
                if not selected.get('selected_scene_ids'):
                    page.locator('[data-scene-count]').fill(str(total));page.locator('[data-scene-count]').dispatch_event('change')
                expect(page.locator('[data-scene-option]:checked')).to_have_count(total)
                previous_attempts=int(sql(f"select attempts from public.user_story_game where id='{game_id}';").stdout.strip()) if selected.get('selected_scene_ids') else 0
                with page.expect_response(lambda response:response.request.method=='POST' and response.url.endswith('/selection')) as confirmation:
                    page.locator('[data-confirm-scenes]').click()
                assert confirmation.value.status==202
                status('building-confirmed-scenes')
                deadline=time.monotonic()+3600
                while not page.locator('iframe.story-game-frame').is_visible():
                    job=json.loads(sql(f"select jsonb_build_object('state',state,'attempts',attempts) from public.user_story_game where id='{game_id}';").stdout.strip())
                    if job['state']=='failed' and job['attempts']>previous_attempts:
                        raise RuntimeError('Live build failed; inspect the retained progress and build-failure receipts')
                    if time.monotonic()>=deadline:raise TimeoutError('Live build did not finish within its deadline')
                    page.wait_for_timeout(2000)
                frame=page.frame_locator('iframe');expect(frame.locator('#game')).to_have_attribute('data-x','80',timeout=30000)
                page.screenshot(path=str(output/'application-player.png'))
                published=rpc(sql,'read_story_game',f"{literal(project)},'{game_id}',false")
                assert published['status']=='published' and len(published['game']['novel_game']['source']['chapters'])==total
                assert sql(f"select count(distinct stage) from public.user_story_game_stage where game_id='{game_id}';").stdout.strip()=='6'
                (output/'game-package.json').write_text(json.dumps(published,indent=2)+'\n')
                sql_receipt=json.loads(sql(f"select model_receipt from public.user_story_game where id='{game_id}';").stdout.strip())
                (output/'application-receipt.json').write_text(json.dumps(sql_receipt,indent=2)+'\n')
                summary=dict(status='PASS',fictional=True,project_id=project,game_id=game_id,source_chapters=10,
                    offered_scenes=total,default_recommendations=recommended_count,confirmed_scenes=total,live_builder='novel-to-game',
                    model=sql_receipt['requested_model'],effort=sql_receipt['reasoning_effort'],resumed=resume)
                (output/'live-test.json').write_text(json.dumps(summary,indent=2)+'\n');print(json.dumps(summary),flush=True)
                browser.close()
        finally:
            browser_server.shutdown();browser_server.server_close();browser_thread.join(timeout=2)
            api_server.should_exit=True;api_thread.join(timeout=10);api_listener.close()
            server.should_exit=True;worker_thread.join(timeout=10);listener.close()


@contextmanager
def resume_database(output):
    """Restart only the task-owned native fixture; never restore SQL into a shared database."""
    info=json.loads((output/'fixture.json').read_text())
    fixture=ROOT/'skills/memoir-story-game/tests/fixtures/age-eight.json'
    directory=Path(info['directory']).resolve()
    if (info.get('fixture_sha256')!=hashlib.sha256(fixture.read_bytes()).hexdigest()
            or not directory.is_relative_to((output/'fixture-db').resolve()) or directory.stat().st_uid!=os.getuid()):
        raise ValueError('Fixture identity or private directory changed')
    data=directory/'data'
    if (data/'postmaster.pid').exists():raise ValueError('This fixture database is already running')
    environment={k:v for k,v in os.environ.items() if not k.startswith('PG')}
    commands=ProcessDeadline(time.monotonic()+7200,environment=environment)
    with socket.socket() as listener:
        listener.bind(('127.0.0.1',0));port=listener.getsockname()[1]
    commands.run(['pg_ctl','-D',str(data),'-l',str(directory/'server.log'),'-o',
        '-h 127.0.0.1 -p '+str(port)+" -k ''",'-w','start'],check=True)
    command=['psql','-X','-qAt','-v','ON_ERROR_STOP=1','-h','127.0.0.1','-p',str(port),'-U','postgres','-d','postgres']
    def sql(query,*,check=True):return commands.run(command,input=query,text=True,check=check)
    sql.command=command;sql.env=environment
    from psycopg.conninfo import make_conninfo
    sql.publication_dsn=make_conninfo(host='127.0.0.1',port=port,user='postgres',dbname='postgres')
    try:
        sql("update public.user_story_game set lease_until=clock_timestamp()-interval '1 second' where state='running';")
        yield sql
    finally:
        ProcessDeadline(time.monotonic()+10,environment=environment).run(['pg_ctl','-D',str(data),'-m','fast','-w','stop'],check=True)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute',action='store_true',help='Run paid live calls with an isolated fictional source')
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--env-file',type=Path,default=ROOT/'.env')
    parser.add_argument('--resume',action='store_true',help='Resume this stopped private native fixture and its saved model stages')
    parser.add_argument('--prepare-only',action='store_true',help='Prepare or check the fixture without any paid model calls')
    args=parser.parse_args()
    if not args.execute:
        from dotenv import dotenv_values
        from apps.api.model_configuration import game_configuration
        settings={**os.environ,**{key:value for key,value in dotenv_values(args.env_file,interpolate=False).items() if value is not None}}
        model,effort=game_configuration(settings)
        print(json.dumps(dict(calls=0,source='fictional full age-eight benchmark',builder='novel-to-game',model=model,effort=effort,human_selection_ui=True)))
        return
    if not args.resume and args.output.exists() and any(args.output.iterdir()):
        parser.error('Use a fresh private output directory; previous live attempts are preserved')
    with tempfile.TemporaryDirectory(prefix='memoir-age-eight-') as temporary,pytest.MonkeyPatch.context() as monkeypatch:
        for key,value in dict(MEMORY_SPARK_ENTITLEMENT_MODEL='legacy',MEMORY_SPARK_TEST_MODE='1',MEMOIR_LEGACY_ONLY_DEPLOYMENT='1',LANGFUSE_TRACING_ENABLED='false').items():
            monkeypatch.setenv(key,value)
        from controlled_policy import install_policy_review_transport
        install_policy_review_transport(monkeypatch,())
        if args.resume:
            with resume_database(args.output.resolve()) as sql:
                run(sql,Path(temporary),monkeypatch,args.output,args.env_file,resume=True,prepare_only=args.prepare_only)
        else:
            database_root=args.output.resolve()/'fixture-db';database_root.mkdir(parents=True,mode=0o700)
            with closing(base_database.__wrapped__(publication_tcp=True,tcp=True,deadline=time.monotonic()+7200,directory_root=database_root)) as database:
                sql=next(database)
                if sql.command[0]!='psql':raise ValueError('The resumable live example requires native PostgreSQL')
                directory=next(database_root.glob('memoir-lease-pg-*')).resolve()
                fixture=ROOT/'skills/memoir-story-game/tests/fixtures/age-eight.json'
                (args.output/'fixture.json').write_text(json.dumps(dict(directory=str(directory),fixture_sha256=hashlib.sha256(fixture.read_bytes()).hexdigest()))+'\n')
                sql=attachment_database.__wrapped__(sql)
                sql=private_database.__wrapped__(sql)
                sql=event_database.__wrapped__(sql)
                from test_shared_memory_events_postgres import sql as fresh_sql
                sql=fresh_sql.__wrapped__(sql)
                run(sql,Path(temporary),monkeypatch,args.output,args.env_file,prepare_only=args.prepare_only)


if __name__=='__main__':
    main()
