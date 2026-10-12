"""A lifetime-sized event still produces a bounded interview context."""
from test_lifetime_memory_postgres import sql, event_database, private_database, attachment_database, database, resolve
from test_shared_memory_events_postgres import rpc, literal
from test_agent_commit_postgres import OWNER

def seed_large_event(sql):
    from controlled_collector import extraction_proposal
    plan = extraction_proposal()['plan']
    plan['candidates'][0]['context']['event_id'] = 'large-event'
    plan['active_event_id'] = 'large-event'
    project = resolve(sql)['project_id']
    data = {'title':'School', 'uncertainty':'Possible name; year disputed', 'assertion':'inferred',
      'temporal':{'expression':'uncertain','precision':'unknown'}, 'timing_conflict':True,
      'temporal_accounts':[{'temporal':{'expression':str(n),'precision':'year','basis':[{'quote':'private '*2000}]}} for n in range(1100)]}
    sql(f"insert into public.user_memory_event(user_id,project_id,id,kind,life_stage,status,data,change_sequence) values('{OWNER}',{literal(project)},'large-event','event','childhood','active',{literal(data)}::jsonb,1);")
    sql(f"""insert into public.user_narrator_source(user_id,project_id,id,client_turn_id,sequence,text,kind,language,processing_status)
      select '{OWNER}',{literal(project)},md5('source'||n)::uuid,md5('turn'||n)::uuid,n,'Original source '||n,'narrator_chat','en-AU','succeeded' from generate_series(1,1100) n;
      insert into public.user_narrator_source_version(user_id,project_id,source_id,version,text,language)
      select user_id,project_id,id,version,text,language from public.user_narrator_source;
      insert into public.user_memory_event_source(user_id,project_id,event_id,source_id,source_version,evidence_hash,evidence)
      select user_id,project_id,'large-event',id,1,md5(id::text),jsonb_build_object('source_id',id,'version',1,'quote',text,'char_start',0,'char_end',length(text)) from public.user_narrator_source;
      insert into public.user_interview_turn(user_id,project_id,client_turn_id,sequence,source_sequence,input_hash,kind,policy_epoch) values('{OWNER}',{literal(project)},'00000000-0000-4000-8000-000000001101',1,1100,'fixture','text',1);
      insert into public.user_interview_plan(user_id,project_id,client_turn_id,sequence,revision,plan) values('{OWNER}',{literal(project)},'00000000-0000-4000-8000-000000001101',1,1,
        {literal(plan)}::jsonb);
      update public.user_memoir_project set source_sequence=1100,event_sequence=1,extraction_cursor=1100,interview_sequence=1 where user_id='{OWNER}' and project_id={literal(project)};""")
    identity = resolve(sql)
    context = rpc(sql, 'read_lifetime_interview_context', f"'{identity['conversation_id']}'")
    return identity, context


def test_pg_single_lifetime_event_cannot_expand_interview_context(sql):
    import json
    identity, context = seed_large_event(sql)
    event = context['events'][0]
    assert len(json.dumps(event).encode()) < 8000
    assert len(event['source_refs']) == 8 and event['reference_identity_complete'] is False
    assert event['evidence_complete'] is False and event['details_complete'] is False
    assert event['uncertainty'] == 'Possible name; year disputed' and event['assertion'] == 'inferred'
    assert 'private' not in json.dumps(context)
