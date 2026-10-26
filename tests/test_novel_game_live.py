"""Opt-in paid age-eight replay through real selection/API/SQL/worker/model boundaries."""
import asyncio
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

from apps.api import novel_game,story_game_routes,memory_event_worker
from test_agent_commit_postgres import database as base_database,OWNER
from test_lifetime_memory_postgres import attachment_database,private_database,event_database
from test_shared_memory_events_postgres import sql,rpc,literal
from test_conversation_attribution import Conversation,empty,episode
from test_story_game_runtime_postgres import compose_game_chapters
from test_formal_memoir_postgres import completed,consent,service
from memoir_postgres_workflow import PostgresRest
from test_background_profile_workflow import Broker

pytestmark=pytest.mark.skipif(os.getenv('MEMOIR_LIVE_NOVEL_GAME')!='1',reason='Explicit live generation opt-in required')
ROOT=Path(__file__).parents[1]


@pytest.fixture(scope='module')
def database():
    yield from base_database.__wrapped__(publication_tcp=True,deadline=time.monotonic()+7200)


def test_full_age_eight_live_with_scene_confirmation(sql,tmp_path,monkeypatch):
    output=Path(os.environ['MEMOIR_LIVE_NOVEL_GAME_OUTPUT']).resolve();output.mkdir(parents=True,exist_ok=True)
    fixture=json.loads((ROOT/'skills/memoir-story-game/tests/fixtures/age-eight.json').read_text())['input']
    texts=['\n\n'.join(b['text'] for b in c['blocks']) for c in fixture['chapters']]
    titles={text:event['title'] for text,event in zip(texts,fixture['timeline'])}
    def extract(packet):
        text=packet['sources'][0]['text']; event=episode(packet,text,title=titles[text])
        event.update(life_stage='childhood',stage_evidence=event['source_refs'],
            temporal=dict(expression='age eight',precision='age',basis=event['source_refs']))
        return {**empty(packet),'events':[event]}
    conversation=Conversation(sql,tmp_path,monkeypatch,extract,strategy='shape')
    with conversation.client:
        for text in texts: conversation.say(text);conversation.drain()
        asyncio.run(compose_game_chapters(conversation))
        edition=completed(sql,conversation.project,{'revision':0});consent(sql,conversation.project,edition,1)
        def storage(_): return PostgresRest(sql,OWNER).storage()
        monkeypatch.setattr(story_game_routes,'authenticated_storage',storage)
        class GameBroker(Broker):
            def __init__(self): super().__init__(sql);self.client=httpx.AsyncClient(trust_env=False)
        monkeypatch.setattr(memory_event_worker,'MemoirLaneBroker',GameBroker)
        from apps.api.codex_worker_service import app as worker_app
        from dotenv import dotenv_values
        settings=dotenv_values(os.environ['MEMOIR_LIVE_NOVEL_GAME_ENV'],interpolate=False)
        for key in ('MEMORY_SPARK_LLM_BASE_URL','MEMORY_SPARK_LLM_API_KEY'):
            monkeypatch.setenv(key,settings[key])
        monkeypatch.setenv('MEMOIR_GAME_BUILDER','novel-to-game')
        monkeypatch.setenv('MEMORY_SPARK_CODEX_WORKER_SECRET','isolated-age-eight-worker')
        original=novel_game.run_novel_game
        async def retained(fence,**options):
            async def load(value): return {**await novel_game.load_build_packet(value),'fictional':True}
            return await original(fence,output=output,packet_loader=load,**options)
        monkeypatch.setattr(novel_game,'run_novel_game',retained)
        listener=socket.socket();listener.bind(('127.0.0.1',0));listener.listen()
        worker_port=listener.getsockname()[1]
        server=uvicorn.Server(uvicorn.Config(worker_app,log_level='warning'))
        worker_thread=threading.Thread(target=server.run,kwargs={'sockets':[listener]},daemon=True);worker_thread.start()
        monkeypatch.setenv('MEMORY_SPARK_CODEX_WORKER_URL','http://127.0.0.1:'+str(worker_port))
        deadline=time.monotonic()+10
        while not server.started and time.monotonic()<deadline: time.sleep(.05)
        assert server.started
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
                    response=conversation.client.request(self.command,path,headers={'Authorization':'Bearer isolated-owner','Content-Type':'application/json'},
                        content=self.rfile.read(int(self.headers.get('Content-Length',0))) or None)
                    content,mime,status=response.content,response.headers.get('Content-Type','application/json'),response.status_code
                else: self.send_error(404);return
                self.send_response(status);self.send_header('Content-Type',mime);self.send_header('Content-Length',str(len(content)));self.end_headers();self.wfile.write(content)
        browser_server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        browser_thread=threading.Thread(target=browser_server.serve_forever,daemon=True);browser_thread.start()
        try:
            with sync_playwright() as p:
                browser=p.chromium.launch(headless=True);page=browser.new_page(viewport={'width':1280,'height':1000})
                page.goto('http://127.0.0.1:'+str(browser_server.server_port));page.locator('#open').click()
                page.locator('[data-generate-game]').click()
                expect(page.locator('[data-scene-selection]')).to_be_visible(timeout=300000)
                defaults=page.locator('[data-scene-option]:checked').count();total=page.locator('[data-scene-option]').count()
                assert defaults>0 and total>=10
                assert sql('select count(*) from public.user_story_game_stage;').stdout.strip()=='0'
                page.screenshot(path=str(output/'selection-defaults.png'))
                status=rpc(sql,'read_story_game_status',literal(project));game_id=status['adaptation']['game_id']
                selected=rpc(sql,'read_story_game',f"{literal(project)},'{game_id}',false")
                (output/'pool.json').write_text(json.dumps(selected,indent=2)+'\n')
                assert sum(s['recommended'] for s in selected['pool']['scenes'])==defaults
                page.locator('[data-scene-count]').fill(str(total));page.locator('[data-scene-count]').dispatch_event('change')
                expect(page.locator('[data-scene-option]:checked')).to_have_count(total)
                page.locator('[data-confirm-scenes]').click()
                expect(page.locator('iframe.story-game-frame')).to_be_visible(timeout=3600000)
                frame=page.frame_locator('iframe');expect(frame.locator('#game')).to_have_attribute('data-x','80',timeout=30000)
                page.screenshot(path=str(output/'application-player.png'))
                published=rpc(sql,'read_story_game',f"{literal(project)},'{game_id}',false")
                assert published['status']=='published' and len(published['game']['novel_game']['source']['chapters'])==total
                assert sql('select count(*) from public.user_story_game_stage;').stdout.strip()=='6'
                (output/'game-package.json').write_text(json.dumps(published,indent=2)+'\n')
                sql_receipt=json.loads(sql(f"select model_receipt from public.user_story_game where id='{game_id}';").stdout.strip())
                (output/'application-receipt.json').write_text(json.dumps(sql_receipt,indent=2)+'\n')
                summary=dict(status='PASS',fictional=True,project_id=project,game_id=game_id,source_chapters=10,
                    offered_scenes=total,default_recommendations=defaults,confirmed_scenes=total,live_builder='novel-to-game',model='gpt-6.1-sol',effort='max')
                (output/'live-test.json').write_text(json.dumps(summary,indent=2)+'\n');print(json.dumps(summary),flush=True)
                browser.close()
        finally:
            browser_server.shutdown();browser_server.server_close();browser_thread.join(timeout=2)
            server.should_exit=True;worker_thread.join(timeout=10);listener.close()
