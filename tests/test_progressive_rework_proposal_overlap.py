"""Unresolved native proposal-overlap regression, with controlled phase evidence.

Only disposable SQL and schema-validated synthetic drafts are used. The pending
contract decision is whether later roots inherit proposals or wait for decisions;
starting another rewrite must not silently recompose an existing proposal.
"""
from uuid import uuid4
from test_lifetime_memory_postgres import sql,event_database,private_database,attachment_database,database
from test_shared_memory_events_postgres import rpc,literal
from test_lifetime_composer_capacity import seeded_composer,service,section_result
from test_progressive_photo_invalidation import validated_result,block,refresh_event
from test_workspace_memory_actions import rework_args


def test_rework_does_not_revisit_a_completed_proposal_on_another_section(sql):
    identity,source_a,lane,initial=seeded_composer(sql)
    project=identity['project_id']
    result=validated_result(initial,[block('a',source_a)])
    service(sql,'commit_lifetime_memoir_lane_page',f"'{lane}','{initial['token']}',{initial['page_number']},{literal(result)}")
    service(sql,'complete_lifetime_memoir_lane',f"'{lane}','{initial['token']}'")
    source_b=rpc(sql,'accept_user_narrator_source',f"{literal(project)},'{uuid4()}','Later I moved to Sydney.'")
    ref=dict(source_id=source_b['id'],version=1,quote=source_b['text'],char_start=0,char_end=len(source_b['text']))
    rpc(sql,'apply_user_memory_events',f"{literal(project)},{literal([{'id':source_b['id'],'version':1}])},{literal([dict(kind='event',title='Sydney',source_refs=[ref])])}")
    sql(f"update public.user_memoir_lane set pending=true where id='{lane}';")
    page=service(sql,'claim_memoir_lane',f"'{lane}',900")
    result=validated_result(page,[block('b',source_b)])
    service(sql,'commit_lifetime_memoir_lane_page',f"'{lane}','{page['token']}',{page['page_number']},{literal(result)}")
    service(sql,'complete_lifetime_memoir_lane',f"'{lane}','{page['token']}'")
    sql("update public.user_lifetime_memoir_section set approved=true where partition_key like '%__a';")
    changed=refresh_event(sql,identity,source_a,lane,initial)
    replacement=block('a',source_a)
    replacement['text']='Chengde was my childhood home.'
    result=validated_result(changed,[replacement])
    service(sql,'commit_lifetime_memoir_lane_page',f"'{lane}','{changed['token']}',{changed['page_number']},{literal(result)}")
    assert service(sql,'complete_lifetime_memoir_lane',f"'{lane}','{changed['token']}'")['status']=='proposed'
    head=rpc(sql,'read_lifetime_private_draft_head',literal(project))
    records=rpc(sql,'read_lifetime_private_draft_page',f"{literal(project)},'{head['snapshot_id']}'")['records']
    chosen=next(item for item in records if item['id'].endswith('__b'))
    rpc(sql,'request_workspace_section_rework',rework_args({**head,'first_record':chosen},str(uuid4())))
    before=sql("select row_to_json(s)::text from public.user_lifetime_memoir_section s where partition_key like '%__a' order by snapshot_id;").stdout
    editorial=service(sql,'claim_memoir_lane',f"'{lane}',900")
    assert editorial['partition_key']==chosen['id']
    output=section_result(editorial,'Sydney was my later home.')
    service(sql,'commit_lifetime_memoir_lane_page',f"'{lane}','{editorial['token']}',{editorial['page_number']},{literal(output)}")
    after=service(sql,'read_lifetime_memoir_lane_page',f"'{lane}','{editorial['token']}'")
    assert sql("select row_to_json(s)::text from public.user_lifetime_memoir_section s where partition_key like '%__a' order by snapshot_id;").stdout==before
    assert any(event['id']==initial['partition']['id'] for event in after['batch']['events'])
    assert after['complete'], 'A completely processed proposed root must not be recomposed for unrelated editorial work'
