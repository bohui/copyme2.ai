"""Disposable SQL verifies NovelToGame receipts, selected passages and stage fences."""
import copy
import json
from pathlib import Path

from apps.api import novel_game
from apps.api.novel_game_bundle import journey, validate_bundle
from test_story_game_runtime_postgres import (database, ready, prepare, read)
from test_lifetime_memory_postgres import attachment_database, private_database, event_database
from test_shared_memory_events_postgres import sql, literal
from test_formal_memoir_postgres import service
from test_agent_commit_postgres import OTHER


def prepared_bundle(packet,scenes):
    source=novel_game.confirmed_source(packet)
    raw=dict(version=1,blend=180,segments=[dict(id='garden',scene='garden',title='A remembered garden',start=0,end=2400)],
        stops=[dict(chapter='C'+str(i+1),segment='garden',x=700+i*400) for i in range(len(scenes))])
    return validate_bundle(dict(version=1,source=novel_game.runner.public_source(source),
        plan=journey.bind_journey(raw,source),css='body{color:#234}',scene_bindings={'garden':'garden'}),scenes)


def build_receipt(packet):
    checks={k:'PASS' for k in ('launch','render','input','coreLoop','outcome','restart')}
    return dict(status='completed',skill='novel-to-game',requested_model='gpt-6.1-sol',model='gpt-6.1-sol',
        reasoning_effort='max',response_id='controlled-novel-final',skill_sha256='b'*64,
        stages=[dict(stage=s,response_id='controlled-'+s) for s in novel_game.STAGES],
        selection_digest=packet['selection_digest'],qa={k:dict(status='PASS',checks=checks) for k in ('desktop','touch')})


def test_novel_save_preserves_selection_and_private_delivery(sql,ready):
    project,_,_=ready
    game,claim,packet,proposal=prepare(sql,project,count=2)
    bundle=prepared_bundle(packet,proposal['scenes'])
    artifact={**proposal,'novel_game':bundle}
    receipt=build_receipt(packet)
    bad=copy.deepcopy(artifact); bad['novel_game']['source']['chapters'][0]['text']='An invented memory.'
    assert service(sql,'stage_story_game',f"'{game['game_id']}','{claim['token']}',{literal(bad)},{literal(receipt)}",check=False).returncode
    incomplete=copy.deepcopy(receipt); incomplete['qa']['touch']['status']='FAIL'
    assert service(sql,'stage_story_game',f"'{game['game_id']}','{claim['token']}',{literal(artifact)},{literal(incomplete)}",check=False).returncode
    result=service(sql,'stage_story_game',f"'{game['game_id']}','{claim['token']}',{literal(artifact)},{literal(receipt)}")
    assert result['status']=='published'
    played=read(sql,project,game)['game']
    assert played['renderer']=='memoir-linear-v2' and played['novel_game']==bundle and 'webpage' not in played
    assert len(played['novel_game']['source']['chapters'])==2
    from jsonschema import validate
    validate(played,json.loads((Path(__file__).parents[1]/'skills/memoir-story-game/schemas/game.schema.json').read_text()))
    assert read(sql,project,game,owner=OTHER,check=False).returncode


def test_checkpoint_reads_and_writes_require_current_build_authority(sql,ready):
    project,_,_=ready
    game,claim,packet,_=prepare(sql,project,count=1)
    prefix=f"'{game['game_id']}','{claim['token']}','analyze','"+'c'*64+"'"
    result=dict(value=dict(files=[dict(path='analysis/SOURCE_BIBLE.md',content='Controlled selected source.')],notes='Fixture'),
        receipt=dict(status='completed',requested_model='gpt-6.1-sol',reasoning_effort='max',stage='analyze',request_sha256='c'*64))
    assert service(sql,'read_story_game_stage',prefix) is None
    assert service(sql,'save_story_game_stage',prefix+','+literal(result))==result
    assert service(sql,'read_story_game_stage',prefix)==result
    changed=copy.deepcopy(result); changed['value']['notes']='Changed bytes'
    assert service(sql,'save_story_game_stage',prefix+','+literal(changed),check=False).returncode
    sql(f"update public.user_story_game set lease_until=clock_timestamp()-interval '1 second' where id='{game['game_id']}';")
    assert service(sql,'read_story_game_stage',prefix,check=False).returncode
    assert service(sql,'save_story_game_stage',prefix+','+literal(result),check=False).returncode
