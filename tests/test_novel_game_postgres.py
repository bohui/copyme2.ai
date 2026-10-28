"""Disposable SQL verifies NovelToGame receipts, selected passages and stage fences."""
import copy
import hashlib
import json
from pathlib import Path
import pytest

from apps.api import novel_game
from apps.api.novel_game_bundle import journey, validate_bundle
from test_story_game_runtime_postgres import (database, ready, prepare, read)
from test_lifetime_memory_postgres import attachment_database, private_database, event_database
from test_shared_memory_events_postgres import sql, literal
from test_formal_memoir_postgres import service
from test_agent_commit_postgres import OTHER,OWNER


def prepared_bundle(packet,scenes):
    source=novel_game.confirmed_source(packet)
    raw=dict(version=1,blend=180,segments=[dict(id='garden',scene='garden',title='A remembered garden',start=0,end=2400)],
        stops=[dict(chapter='C'+str(i+1),segment='garden',x=700+i*400) for i in range(len(scenes))])
    return validate_bundle(dict(version=1,source=novel_game.runner.public_source(source),
        plan=journey.bind_journey(raw,source),css='.memory-marker > span {color:#234}',scene_bindings={'garden':'garden'}),scenes)


def build_receipt(packet):
    checks={k:'PASS' for k in ('launch','render','input','coreLoop','outcome','restart')}
    return dict(status='completed',skill='novel-to-game',requested_model='gpt-6.1-sol',model='gpt-6.1-sol',
        reasoning_effort='max',response_id='controlled-novel-final',skill_sha256='b'*64,
        stages=[dict(stage=s,response_id='controlled-'+s) for s in novel_game.STAGES],
        selection_digest=packet['selection_digest'],qa={k:dict(status='PASS',checks=checks) for k in ('desktop','touch')})


@pytest.mark.parametrize('generated',[False,True])
@pytest.mark.parametrize('effort',['low','max'])
def test_novel_save_preserves_selection_and_private_delivery(sql,ready,generated,effort,tmp_path,monkeypatch):
    project,_,_=ready
    game,claim,packet,proposal=prepare(sql,project,count=2)
    bundle=prepared_bundle(packet,proposal['scenes'])
    if generated:
        from test_novel_game_art import png
        from apps.api.novel_game_art import cache_root
        monkeypatch.setenv('MEMORY_SPARK_OBJECT_STORE_PATH',str(tmp_path/'objects'))
        key='a'*64+'/'+ 'b'*64
        path=cache_root()/(key+'.png');path.parent.mkdir(parents=True);path.write_bytes(png())
        bundle.update(version=2,scene_bindings={},illustrations=[dict(cache_key='a'*64+'/'+ 'b'*64,
            sha256=hashlib.sha256(png()).hexdigest(),width=768,height=512,scenes=['garden'])])
        validate_bundle(bundle,proposal['scenes'])
    artifact={**proposal,'novel_game':bundle}
    receipt=build_receipt(packet)
    receipt['reasoning_effort']=effort
    unsupported=copy.deepcopy(receipt); unsupported['reasoning_effort']='medium'
    assert service(sql,'stage_story_game',f"'{game['game_id']}','{claim['token']}',{literal(artifact)},{literal(unsupported)}",check=False).returncode
    bad=copy.deepcopy(artifact); bad['novel_game']['source']['chapters'][0]['text']='An invented memory.'
    assert service(sql,'stage_story_game',f"'{game['game_id']}','{claim['token']}',{literal(bad)},{literal(receipt)}",check=False).returncode
    incomplete=copy.deepcopy(receipt); incomplete['qa']['touch']['status']='FAIL'
    assert service(sql,'stage_story_game',f"'{game['game_id']}','{claim['token']}',{literal(artifact)},{literal(incomplete)}",check=False).returncode
    for css in ['</style><script>bad</script>','body{background:url(https://outside.test)}']:
        unsafe=copy.deepcopy(artifact);unsafe['novel_game']['css']=css
        assert service(sql,'stage_story_game',f"'{game['game_id']}','{claim['token']}',{literal(unsafe)},{literal(receipt)}",check=False).returncode
    if generated:
        unsafe=copy.deepcopy(artifact);unsafe['novel_game']['illustrations'][0]['cache_key']='../../secret'
        assert service(sql,'stage_story_game',f"'{game['game_id']}','{claim['token']}',{literal(unsafe)},{literal(receipt)}",check=False).returncode
    result=service(sql,'stage_story_game',f"'{game['game_id']}','{claim['token']}',{literal(artifact)},{literal(receipt)}")
    assert result['status']=='published'
    played=read(sql,project,game)['game']
    assert played['renderer']=='memoir-linear-v2' and played['novel_game']==bundle and 'webpage' not in played
    assert len(played['novel_game']['source']['chapters'])==2
    from jsonschema import validate
    validate(played,json.loads((Path(__file__).parents[1]/'skills/memoir-story-game/schemas/game.schema.json').read_text()))
    assert read(sql,project,game,owner=OTHER,check=False).returncode
    if generated:
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from apps.api.story_game_routes import StoryGameResponse
        monkeypatch.setenv('MEMOIR_PUBLICATION_DATABASE_URL',sql.publication_dsn)
        app=FastAPI()
        @app.get('/owner')
        def owner():return StoryGameResponse(OWNER,project,game['game_id'])
        @app.get('/other')
        def other():return StoryGameResponse(OTHER,project,game['game_id'])
        with TestClient(app) as client:
            assert client.get('/other').status_code==403
            delivered=client.get('/owner');assert delivered.status_code==200
            assert delivered.json()['game']['novel_game']['illustrations'][0]['data_url'].startswith('data:image/png;base64,')
            assert delivered.headers['cache-control']=='private, no-store'


@pytest.mark.parametrize('effort',['low','max'])
def test_checkpoint_reads_and_writes_require_current_build_authority(sql,ready,effort):
    project,_,_=ready
    game,claim,packet,_=prepare(sql,project,count=1)
    prefix=f"'{game['game_id']}','{claim['token']}','analyze','"+'c'*64+"'"
    result=dict(value=dict(files=[dict(path='analysis/SOURCE_BIBLE.md',content='Controlled selected source.')],notes='Fixture'),
        receipt=dict(status='completed',requested_model='gpt-6.1-sol',reasoning_effort=effort,stage='analyze',request_sha256='c'*64))
    assert service(sql,'read_story_game_stage',prefix) is None
    unsupported=copy.deepcopy(result); unsupported['receipt']['reasoning_effort']='medium'
    assert service(sql,'save_story_game_stage',prefix+','+literal(unsupported),check=False).returncode
    assert service(sql,'save_story_game_stage',prefix+','+literal(result))==result
    assert service(sql,'read_story_game_stage',prefix)==result
    changed=copy.deepcopy(result); changed['value']['notes']='Changed bytes'
    assert service(sql,'save_story_game_stage',prefix+','+literal(changed),check=False).returncode
    sql(f"update public.user_story_game set lease_until=clock_timestamp()-interval '1 second' where id='{game['game_id']}';")
    assert service(sql,'read_story_game_stage',prefix,check=False).returncode
    assert service(sql,'save_story_game_stage',prefix+','+literal(result),check=False).returncode
