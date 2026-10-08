"""Repeated canonical revocation must preserve private photo dependency fences."""
import pytest
import json
from uuid import uuid4
from test_interview_photos_postgres import database, attachment_database, private_database, event_database, sql, upload, accept, save, association, rpc, literal, OWNER, OLD, as_user
from test_shared_memory_events_postgres import extract
from apps.api.canonical_composer import composer_request,fingerprint

@pytest.mark.parametrize('photo_action',['unlink','delete'])
@pytest.mark.parametrize('revocation',['source','event'])
def test_photo_removal_then_unrelated_revocation_preserves_dependency(sql,photo_action,revocation):
    photo=upload(sql); first=accept(sql,photos=[photo['id']]);source=first['source']
    save(sql,first,associations=[association(first,photo,provenance='narrator_metadata')])
    ref={'source_id':source['id'],'version':1,'quote':source['text']}
    event=extract(sql,[source],[{'kind':'event','title':'Visit','source_refs':[ref]}])['events'][0]
    second=accept(sql,'I later learned to swim.',turn=str(uuid4())); other=second['source']
    other_ref={'source_id':other['id'],'version':1,'quote':other['text']}
    view=extract(sql,[other],[{'kind':'event','title':'Swimming','source_refs':[other_ref]}])
    events=view['events']; other_event=next(e for e in events if e['id']!=event['id'])
    packet={'user_id':OWNER,'project_id':'project','sources':view['sources'],'events':events,'locale':'en-AU',
       'source_manifest':[{'id':s['id'],'version':s['version']} for s in view['sources']],
       'event_manifest':[{'id':e['id'],'revision':e['revision']} for e in events],
       'base_revision':0,'policy_epoch':1,'coverage_round':5,'previous':None}
    projected=composer_request(packet)
    refs={e['id']:e['source_refs'] for e in projected['events']}
    sections=[{'id':e['id']+'section','chapter_id':e['id'],'event_ids':[e['id']],'source_refs':refs[e['id']],
        'block':{'id':e['id']+'block','text':'Old photo significance' if e['id']==event['id'] else 'Swimming','source_refs':refs[e['id']]}} for e in events]
    bundle={'content_config':fingerprint({'locale':'en-AU','skill':'shared-composer-4','model':'gpt-5.6-luna-pooled','policy':projected['policy']}),
        'manuscript':{'kind':'sample_chapter','chapters':[]},'draft':{'input_fingerprint':'original'},
        'photo_association_manifest':projected['context']['photo_association_manifest'],
        'event_manifest':packet['event_manifest'],'sections':sections}
    sql(f"insert into public.user_memoir_manuscript(user_id,project_id,locale,revision,bundle) values('{OWNER}','project','en-AU',1,{literal(bundle)}::jsonb);")
    link=rpc(sql,'read_user_interview_context',"'project'")['photo_associations'][0]
    if photo_action=='unlink':rpc(sql,'unlink_user_interview_photo',f"'project','{link['id']}'")
    else:rpc(sql,'delete_user_interview_photo',f"'project','{photo['id']}'")
    if revocation=='source':rpc(sql,'change_user_narrator_source',f"'project','{other['id']}',1,'withdraw'")
    else:rpc(sql,'unlink_user_memory_event_source',f"'project','{other_event['id']}',{other_event['revision']},'{other['id']}','Remove this source from this event.'")
    previous=json.loads(sql('select coalesce(bundle,reuse) from public.user_memoir_manuscript;').stdout)
    assert len(previous['sections'])==1 and previous['sections'][0]['block']['text']=='Old photo significance'
    # Running restricted reuse again must retain the dependency as well.
    previous=json.loads(sql(f"select public.safe_memoir_reuse({literal(previous)}::jsonb,array[]::text[]);").stdout)
    view=rpc(sql,'read_user_memory_events',"'project'")
    packet.update(sources=[s for s in view['sources'] if s['status']=='active'],events=[e for e in view['events'] if e['status']!='withdrawn'],base_revision=1,policy_epoch=3,previous=previous)
    packet['event_manifest']=[{'id':e['id'],'revision':e['revision']} for e in packet['events']]
    result=composer_request(packet)
    assert event['id'] in result['context']['photo_dirty_event_ids'],result['context']
