"""Production integration keeps selection, upstream identity, resume and trusted execution."""
import asyncio
from contextlib import asynccontextmanager
import copy
import json

import httpx
import pytest

from apps.api import novel_game, model_request, memoir_story_game
from apps.api.novel_game_bundle import runtime_bundle, runtime_asset, scene_library, validate_bundle, validate_style
from apps.api.story_game_runtime import GamePublication
from test_story_game_runtime import build_packet, GAME, TOKEN


@pytest.fixture
def approved():
    packet=build_packet()
    packet['brief']=dict(design_brief='One continuous illustrated memory walk.',scene_indices=[0])
    for e in packet['timeline']: e.update(life_stage='childhood',age=dict(minimum=8,maximum=8))
    return packet


@pytest.fixture
def draft_prompts(monkeypatch):
    # Unit tests inspect draft bytes; live runs still require actual published receipts.
    monkeypatch.setattr(novel_game,'load_prompt_artifact',lambda path:path.read_text())
    monkeypatch.setattr(model_request,'load_prompt_artifact',lambda path:path.read_text())


def outputs(stage):
    plan=dict(version=1,blend=180,segments=[dict(id='garden',scene='garden',title='Garden',start=0,end=1200)],
        stops=[dict(chapter='C1',segment='garden',x=700)])
    return {
        'analyze':{'analysis/SOURCE_BIBLE.md':'selected-1 event-1: the father tended the garden.'},
        'concept':{'concepts/CONCEPT.md':'One continuous chronological memory walk.'},
        'design':{'design/GAME_DESIGN.md':'Read the selected memory.','design/JOURNEY_PLAN.json':json.dumps(plan)},
        'whitebox':{'build/BUILD_BRIEF.md':'Test proximity reading.','build/app/game.css':'body{color:#263d37}'},
        'art':{'design/ART_DIRECTION.md':'Reuse garden artwork.','design/SCENE_BINDINGS.json':'{"garden":"garden"}'},
        'production':{'build/BUILD_BRIEF.md':'Ready for actual browser replay.','build/app/game.css':'body{color:#263d37;background:#faf6e9}'},
    }[stage]


@pytest.mark.parametrize('missing_background',[False,True])
def test_resumable_live_transport_uses_only_the_confirmed_subset_and_sol_max(approved,draft_prompts,tmp_path,monkeypatch,missing_background):
    calls,stored,verified=[],{},[]
    @asynccontextmanager
    async def guard(self,fence):
        assert str(fence['game_id'])==GAME and str(fence['token'])==TOKEN
        yield
    monkeypatch.setattr(GamePublication,'guard',guard)
    monkeypatch.setenv('MEMOIR_PUBLICATION_DATABASE_URL','controlled-database')
    monkeypatch.setenv('MEMORY_SPARK_LLM_BASE_URL','https://gateway.test/v1')
    monkeypatch.setenv('MEMORY_SPARK_LLM_API_KEY','controlled-secret-value')
    monkeypatch.setenv('MEMORY_SPARK_OBJECT_STORE_PATH',str(tmp_path/'objects'))
    async def load(_): return approved
    async def store(fence,stage,signature,value=None):
        if value is not None: stored[stage,signature]=copy.deepcopy(value)
        return copy.deepcopy(stored.get((stage,signature)))
    async def verify(workspace,stage,phone=False):
        verified.append((stage,phone))
        return dict(status='PASS',checks={k:'PASS' for k in ('launch','render','input','coreLoop','outcome','restart')})
    fail=True
    def transport(request):
        body=json.loads(request.content); stage=body['metadata']['stage']; calls.append(stage)
        assert body['model']=='gpt-6.1-sol' and body['reasoning']=={'effort':'max'} and body['stream'] is True
        payload=json.loads(body['input'])
        assert 'mother repaired' not in body['input'] and approved['chapters'][0]['chapter_id'] not in body['input']
        assert payload['source']['chapters'][0]['blocks']==[dict(text='My father tended the garden.')]
        assert novel_game.runner.STAGES[stage]['skill']+'/SKILL.md' in body['instructions']
        if stage=='art' and fail: raise httpx.ReadTimeout('controlled interrupted art stage')
        files=outputs(stage)
        if stage=='art' and missing_background:files['design/SCENE_BINDINGS.json']='{"garden":{"prompt":"A supported garden background."}}'
        value=dict(files=[dict(path=p,content=c) for p,c in files.items()],notes='Controlled transport, browser verifier is mocked.')
        result=dict(status='completed',id='resp-'+stage,model='gpt-6.1-sol',reasoning=dict(effort='max'),
            output=[dict(type='message',content=[dict(type='output_text',text=json.dumps(value))])])
        return httpx.Response(200,text='data: '+json.dumps(dict(type='response.completed',response=result))+'\n\n',headers={'Content-Type':'text/event-stream'})
    fence=dict(game_id=GAME,token=TOKEN,authority=approved['authority'])
    image_calls=[];image_fail=True
    async def image(prompt,_):
        image_calls.append(prompt)
        if image_fail:raise httpx.ReadTimeout('controlled missing-background interruption')
        from test_novel_game_art import png
        return png(),{'model':'controlled-image'}
    def run():
        return asyncio.run(novel_game.run_novel_game(fence,packet_loader=load,transport=httpx.MockTransport(transport),
            stage_store=store,verifier=verify,output=tmp_path,image_generator=image))
    with pytest.raises(httpx.ReadTimeout): run()
    assert calls==['analyze','concept','design','whitebox','art'] and len(stored)==4
    fail=False
    if missing_background:
        with pytest.raises(httpx.ReadTimeout):run()
        assert len(stored)==5, 'The art decision must survive an image-generation failure'
    image_fail=False
    result=run()
    assert calls==['analyze','concept','design','whitebox','art','art','production']
    bundle=result['webpage']['novel_game']
    assert bundle['source']['chapters']==[dict(id='C1',title='father',text='My father tended the garden.')]
    assert result['receipt']['skill']=='novel-to-game' and len(result['receipt']['stages'])==6
    assert ('production',False) in verified and ('production',True) in verified
    before=list(calls)
    run()
    assert calls==before, 'Matching completed stages must not call the model again'
    assert len(image_calls)==(2 if missing_background else 0)
    assert bundle['version']==(2 if missing_background else 1)
    assert len(stored)==6
    assert validate_bundle(bundle,[approved['scene_pool']['scenes'][0]])==bundle
    altered=copy.deepcopy(bundle); altered['source']['chapters'][0]['text']='Unselected invented text.'
    with pytest.raises(ValueError,match='selection_changed'): validate_bundle(altered,[approved['scene_pool']['scenes'][0]])


def test_no_selection_never_dispatches_novel_game(approved):
    approved['selection']=None
    async def load(_): return approved
    with pytest.raises(ValueError,match='human_selection'):
        asyncio.run(novel_game.run_novel_game(dict(game_id=GAME,token=TOKEN,authority=approved['authority']),packet_loader=load))


def test_completed_stream_returns_without_waiting_for_provider_disconnect(approved,monkeypatch):
    @asynccontextmanager
    async def guard(self,fence): yield
    monkeypatch.setattr(GamePublication,'guard',guard)
    monkeypatch.setenv('MEMOIR_PUBLICATION_DATABASE_URL','controlled')
    monkeypatch.setenv('MEMORY_SPARK_LLM_BASE_URL','https://gateway.test/v1')
    monkeypatch.setenv('MEMORY_SPARK_LLM_API_KEY','controlled-terminal-secret')
    result=dict(status='completed',id='resp-terminal',model='gpt-6.1-sol',reasoning={'effort':'max'},output=[])
    class Stream(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield ('data: '+json.dumps(dict(type='response.completed',response=result))+'\n\n').encode()
            raise AssertionError('Read continued after terminal response')
    async def transport(request): return httpx.Response(200,stream=Stream())
    observed=[]
    actual=asyncio.run(novel_game.model_stage(dict(model='gpt-6.1-sol',metadata={'stage':'concept'}),
        novel_game.GameFence(game_id=GAME,token=TOKEN,authority=approved['authority']),
        transport=httpx.MockTransport(transport),observer=lambda kind,value:observed.append(kind)))
    assert actual==result and observed[0]=='request' and observed[-1]=='response'


@pytest.mark.parametrize('css', ['body{background:url(https://outside.test)}','/* </style><script>bad</script> */',
    '@import "outside";','#interact{display:none}','p{content:"invented quote"}','body{background:u/**/rl(outside)}'])
def test_model_css_cannot_replace_behavior_or_load_assets(css):
    with pytest.raises(ValueError): validate_style(css)


def test_model_css_accepts_child_selectors_without_allowing_markup():
    css='.memory-marker > span {color:#263d36}'
    assert validate_style(css)==css


def test_runtime_bundle_contains_no_memoir_and_asset_lookup_is_closed():
    bundle=runtime_bundle()
    assert len(json.dumps(bundle))<100000
    assert 'memoir-source' not in bundle['javascript'] or 'JSON.parse' in bundle['javascript']
    assert 'http' not in bundle['css']
    library=scene_library()
    assert runtime_asset(library['sha256'],'places.png').is_file()
    with pytest.raises(ValueError): runtime_asset(library['sha256'],'../../.env')
    with pytest.raises(ValueError): runtime_asset('0'*64,'places.png')


@pytest.mark.parametrize('builder,expected',[('novel-to-game','novel'),('higgsfield','backup')])
def test_worker_defaults_to_novel_and_retains_explicit_backup(approved,monkeypatch,builder,expected):
    from fastapi.testclient import TestClient
    from apps.api import codex_worker_service,higgsfield_game
    monkeypatch.setenv('MEMORY_SPARK_CODEX_WORKER_SECRET','controlled-worker-secret')
    if builder=='novel-to-game': monkeypatch.delenv('MEMOIR_GAME_BUILDER',raising=False)
    else: monkeypatch.setenv('MEMOIR_GAME_BUILDER',builder)
    async def novel(*_,**kwargs): return {'selected':'novel'}
    async def backup(*_,**kwargs): return {'selected':'backup'}
    monkeypatch.setattr(novel_game,'run_novel_game',novel)
    monkeypatch.setattr(higgsfield_game,'run_higgsfield_game',backup)
    with TestClient(codex_worker_service.app) as client:
        payload=dict(game_id=GAME,token=TOKEN,authority=approved['authority'])
        assert client.post('/internal/story-game/build',json=payload).status_code==401
        response=client.post('/internal/story-game/build',json=payload,headers={'X-Codex-Worker-Secret':'controlled-worker-secret'})
        assert response.status_code==200 and response.json()=={'selected':expected}
