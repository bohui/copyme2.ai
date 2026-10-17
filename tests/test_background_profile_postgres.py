"""Scheduled profile lifecycle on disposable native PostgreSQL; no provider calls."""
import json
from uuid import uuid4

import pytest

from test_agent_commit_postgres import database, OWNER, OTHER, OLD, as_user
from test_guest_conversation_transfer import attachment_database
from test_private_rounds_postgres import private_database
from test_lifetime_memory_postgres import event_database, sql
from test_shared_memory_events_postgres import rpc, literal


@pytest.fixture(autouse=True)
def enable_local_rollout(sql):
    sql('update public.lifetime_two_lane_rollout set enabled=true;')
    sql('update public.lifetime_profile_cadence set initial_rounds=array[1,5]::bigint[],interval_rounds=10;')


def service(sql, name, args):
    return json.loads(sql(f"set role service_role; select coalesce(to_jsonb(public.{name}({args})),'null'::jsonb);").stdout.strip())


def source(sql, identity, text='I was born around 1960 in Hobart.', ordinal=None):
    saved = rpc(sql, 'accept_user_narrator_source',
                f"{literal(identity['project_id'])},'{uuid4()}',{literal(text)}")
    if ordinal is not None:
        sql(f"insert into public.user_completed_round(user_id,project_id,turn_id,ordinal) "
            f"values('{OWNER}',{literal(identity['project_id'])},'{saved['client_turn_id']}',{ordinal});")
    return saved


def setup(sql, rounds=1, text='I was born around 1960 in Hobart.'):
    identity = rpc(sql, 'resolve_lifetime_conversation', 'null')
    sources = [source(sql, identity, text, i) for i in range(1, rounds + 1)]
    sql(f"insert into public.user_memoir_lane(user_id,project_id,skill,pending,target_source) "
        f"values('{OWNER}',{literal(identity['project_id'])},'timeline',true,{len(sources)}) on conflict do nothing;")
    lane = sql("select id from public.user_memoir_lane where skill='timeline';").stdout.strip()
    page = service(sql, 'claim_memoir_lane', f"'{lane}',300")
    return identity, sources, lane, page


def read(sql, lane, base):
    return service(sql, 'read_lifetime_profile_page', f"'{lane}','{base['token']}'")


def result(page, field=None, value=None):
    if field is None:
        return {'profile_patch': [], **({'skipped': True} if page['profile_context']['work_mode']=='skip' else {})}
    s = page['source']
    return {'profile_patch': [{'field':field, 'value':value, 'source_refs':[
        {'source_id':s['id'], 'version':s['version'], 'char_start':s['char_start'],
         'char_end':s['char_end'], 'quote':s['text']}]}]}


def commit(sql, lane, page, output=None):
    return service(sql, 'commit_lifetime_profile_page',
        f"'{lane}','{page['token']}','{page['page_digest']}',{literal(result(page) if output is None else output)}")


def manual(sql, patch):
    sql(as_user(f"select public.acquire_user_agent_turn_lease('{OLD}');"))
    saved = rpc(sql, 'set_lifetime_profile_settings', f"{literal(patch)},'{OLD}'")
    sql("update public.user_agent_turn_lease set expires_at=clock_timestamp()-interval '1 second';")
    return saved


def profile(sql):
    return json.loads(sql(as_user('select profile from public.user_profile;')).stdout.strip())


def reclaim(sql, lane):
    sql("update public.user_memoir_lane set lease_until=clock_timestamp()-interval '1 second',pending=true,attempts=0;")
    return service(sql,'claim_memoir_lane',f"'{lane}',300")


def fence(page):
    from apps.api.lifetime_memory_lane_engine import LaneFence
    return LaneFence.model_validate({k:v for k,v in page.items() if k in LaneFence.model_fields}).model_dump(mode='json')


def test_default_cadence_config_and_high_round_coalescing(sql):
    values = json.loads(sql('select jsonb_agg(public.lifetime_profile_due_round(i) order by i) from generate_series(0,30) i;').stdout)
    assert values==[0,1,1,1,1,5,5,5,5,5]+[10]*10+[20]*10+[30]
    identity, sources, lane, base = setup(sql, 30)
    p = read(sql,lane,base)
    assert p['profile_context']['target_round']==30 and p['source']['id']==sources[0]['id']
    assert sql('select count(*) from public.user_lifetime_profile_progress;').stdout.strip()=='1'
    sql('update public.lifetime_profile_cadence set initial_rounds=array[2]::bigint[],interval_rounds=7;')
    assert sql('select public.lifetime_profile_due_round(30);').stdout.strip()=='28'


def test_success_receipt_reference_and_own_snapshot_refresh(sql):
    identity, sources, lane, base = setup(sql)
    p = read(sql,lane,base)
    output = result(p,'birth_year',1960)
    assert commit(sql,lane,p,output)['status']=='page_saved'
    state=json.loads(sql('select jsonb_build_object(\'snapshot\',s,\'identity\',c,\'lane\',l) from public.user_lifetime_lane_snapshot s join public.user_lifetime_conversation c using(user_id,project_id) join public.user_memoir_lane l on l.id=s.lane_id;').stdout)
    assert state['snapshot']['preference_revision']==state['identity']['preference_revision'],state
    assert state['snapshot']['state']=='pending',state
    assert commit(sql,lane,p,output)=={'status':'page_saved','replayed':True}
    with pytest.raises(AssertionError): commit(sql,lane,p,result(p,'birth_year',1961))
    assert profile(sql)['birth_year']==1960
    refreshed = service(sql,'read_lifetime_memoir_lane_page',f"'{lane}','{base['token']}'")
    assert refreshed['preference_revision']>base['preference_revision']
    assert read(sql,lane,base) is None
    assert sql('select covered_round||\':\'||covered_frontier from public.user_lifetime_profile_progress;').stdout.strip()=='1:1'
    assert sql('select count(*) from public.user_lifetime_profile_dependency;').stdout.strip()=='1'
    assert sql('select count(*) from public.user_memory_event;').stdout.strip()=='0'
    for n in range(2,6): source(sql,identity,'Another memory.',n)
    base = reclaim(sql,lane)
    p = read(sql,lane,base)
    assert p['profile_context']['reference']['birth_year']=={'value':1960,'authority':'automatic'}
    assert p['source']['id']!=sources[0]['id']


def test_frozen_interval_orphans_newest_target_and_restart(sql):
    identity, sources, lane, base = setup(sql)
    p = read(sql,lane,base)
    orphan = source(sql,identity,'An accepted answer without a saved reply.')
    for n in range(2,11): source(sql,identity,f'Memory {n}.',n)
    assert read(sql,lane,base)['page_digest']==p['page_digest'], 'Active source frontier must stay frozen'
    commit(sql,lane,p)
    p = read(sql,lane,base)
    assert p['profile_context']['target_round']==10
    assert p['source']['id']==orphan['id']
    commit(sql,lane,p)
    base = reclaim(sql,lane)
    p = read(sql,lane,base)
    assert p['profile_context']['target_round']==10 and p['source']['text']=='Memory 2.'
    assert sql('select covered_round from public.user_lifetime_profile_progress;').stdout.strip()=='1'


def test_unicode_windows_resume_without_claiming_partial_success(sql):
    identity, sources, lane, base = setup(sql,text='我在承德长大。'*700)
    windows=[]
    while (p:=read(sql,lane,base)) is not None:
        s=p['source'];core=p['profile_context']['cursor']['char_start']
        windows.append(s['text'][core-s['char_start']:])
        assert len(s['text'])<=2304 and s['char_end']-s['char_start']==len(s['text'])
        commit(sql,lane,p)
        if s['char_end']<s['original_length']:
            assert sql('select covered_round from public.user_lifetime_profile_progress;').stdout.strip()=='0'
            base = reclaim(sql,lane)
    assert ''.join(windows)==sources[0]['text'] and len(windows)>1
    assert sql('select covered_round from public.user_lifetime_profile_progress;').stdout.strip()=='1'


def test_manual_blank_locks_stop_latch_release_and_honest_skip(sql):
    identity, sources, lane, base = setup(sql)
    saved = manual(sql,{'birth_year':None})
    assert saved['profile_automation']['field_locks']=={'birth_year':'manual'}
    assert not saved['profile_automation']['stopped']
    base = reclaim(sql,lane)
    p = read(sql,lane,base)
    assert 'birth_year' not in p['profile_context']['targets']
    with pytest.raises(AssertionError):commit(sql,lane,p,result(p,'birth_year',1960))
    for key in ['name','birth_date_expression','birth_place','childhood_place','avatar_style']:
        saved=manual(sql,{key:None})
    assert saved['profile_automation']['stopped'] and saved['profile_automation']['manual_complete']
    manual(sql,{'profile_release_fields':['birth_year']})
    base=reclaim(sql,lane);p=read(sql,lane,base)
    assert p['profile_context']['work_mode']=='skip'
    commit(sql,lane,p)
    assert read(sql,lane,base) is None
    assert sql('select covered_round||\':\'||skipped_round from public.user_lifetime_profile_progress;').stdout.strip()=='0:1'
    assert sql('select count(*) from public.user_lifetime_profile_coverage;').stdout.strip()=='0'
    manual(sql,{'profile_auto_enabled':True})
    base=reclaim(sql,lane);p=read(sql,lane,base)
    assert p['profile_context']['targets']==['birth_year'] and p['profile_context']['work_mode']=='extract'
    commit(sql,lane,p,result(p,'birth_year',1960))
    assert profile(sql)['birth_year']==1960


def test_existing_populated_values_are_conservatively_locked_without_manual_completion(sql):
    sql(f"insert into public.user_profile(user_id,profile) values('{OWNER}',{literal({'birth_year':1960,'avatar_style':'female'})}) "
        "on conflict(user_id) do update set profile=excluded.profile;")
    identity,sources,lane,base=setup(sql)
    p=read(sql,lane,base)
    assert 'birth_year' not in p['profile_context']['targets'] and 'avatar_style' not in p['profile_context']['targets']
    assert p['profile_context']['reference']['birth_year']=={'value':1960,'authority':'preserved'}
    assert not rpc(sql,'read_lifetime_profile_automation','')['manual_complete']


@pytest.mark.parametrize('change',['manual','confirm_all','token','source','policy','generation','phase','rollout'])
def test_commit_and_real_publication_guard_reject_stale_authority(sql,change):
    identity,sources,lane,base=setup(sql)
    p=read(sql,lane,base);f=fence(p)
    assert rpc(sql,'lock_lifetime_memoir_lane_publication',literal(f))>0
    if change=='manual':manual(sql,{'birth_year':1970})
    elif change=='confirm_all':manual(sql,{'profile_confirm_all':True})
    elif change=='token':sql('update public.user_memoir_lane set token=gen_random_uuid();')
    elif change=='source':rpc(sql,'change_user_narrator_source',f"{literal(identity['project_id'])},'{sources[0]['id']}',1,'withdraw',null")
    elif change=='policy':sql('update public.user_memoir_project set policy_epoch=policy_epoch+1;')
    elif change=='generation':sql('update public.user_lifetime_conversation set execution_generation=execution_generation+1;')
    elif change=='phase':rpc(sql,'change_user_conversation_phase',f"{literal(identity['project_id'])},'shape',0")
    else:sql('update public.lifetime_two_lane_rollout set enabled=false;')
    assert rpc(sql,'lock_lifetime_memoir_lane_publication',literal(f),check=False).returncode!=0
    with pytest.raises(AssertionError):commit(sql,lane,p,result(p,'birth_year',1960))
    assert profile(sql).get('birth_year')!=1960
    assert sql('select count(*) from public.user_lifetime_profile_receipt;').stdout.strip()=='0'


def test_interactive_lease_defers_profile_without_invalidating_reply(sql):
    identity,sources,lane,base=setup(sql)
    p=read(sql,lane,base)
    before=sql('select preference_revision from public.user_lifetime_conversation;').stdout
    sql(as_user(f"select public.acquire_user_agent_turn_lease('{OLD}');"))
    assert read(sql,lane,base) is None
    assert rpc(sql,'lock_lifetime_memoir_lane_publication',literal(fence(p)),check=False).returncode!=0
    with pytest.raises(AssertionError):commit(sql,lane,p,result(p,'birth_year',1960))
    assert sql('select preference_revision from public.user_lifetime_conversation;').stdout==before
    sql("update public.user_agent_turn_lease set expires_at=clock_timestamp()-interval '1 second';")
    assert read(sql,lane,base)['page_digest']==p['page_digest']


@pytest.mark.parametrize('bad',['unsupported','language','null','avatar','quote','span','foreign_source','duplicate'])
def test_database_rejects_malformed_or_ungrounded_patch_atomically(sql,bad):
    identity,sources,lane,base=setup(sql)
    p=read(sql,lane,base);out=result(p,'birth_year',1960);item=out['profile_patch'][0]
    if bad=='unsupported':item['field']='entitlements'
    elif bad=='language':item['field']='preferred_language';item['value']='zh-CN'
    elif bad=='null':item['value']=None
    elif bad=='avatar':item['field']='avatar_style';item['value']='unknown'
    elif bad=='quote':item['source_refs'][0]['quote']='fabricated'
    elif bad=='span':item['source_refs'][0]['char_end']+=1
    elif bad=='foreign_source':item['source_refs'][0]['source_id']=str(uuid4())
    else:out['profile_patch'].append(item)
    with pytest.raises(AssertionError):commit(sql,lane,p,out)
    assert 'birth_year' not in profile(sql)
    assert sql('select count(*) from public.user_lifetime_profile_receipt;').stdout.strip()=='0'


@pytest.mark.parametrize('change',['edit','withdraw','policy'])
def test_immediate_invalidation_preserves_manual_fields_and_later_version_catchup(sql,change):
    identity,sources,lane,base=setup(sql)
    manual(sql,{'childhood_place':'Sydney'})
    base=reclaim(sql,lane);p=read(sql,lane,base)
    commit(sql,lane,p,result(p,'birth_year',1960))
    if change=='policy':sql('update public.user_memoir_project set policy_epoch=policy_epoch+1;')
    else:rpc(sql,'change_user_narrator_source',f"{literal(identity['project_id'])},'{sources[0]['id']}',1,'{change}',"
        +(literal('Correction: I was born in 1961.') if change=='edit' else 'null'))
    assert 'birth_year' not in profile(sql) and profile(sql)['childhood_place']=='Sydney'
    assert sql('select count(*) from public.user_lifetime_profile_dependency;').stdout.strip()=='0'
    for n in range(2,6):source(sql,identity,f'Memory {n}.',n)
    base=reclaim(sql,lane);p=read(sql,lane,base)
    assert p['profile_context']['target_round']==5
    if change=='edit':
        assert p['source']['id']==sources[0]['id'] and p['source']['version']==2


def test_owner_scope_rollout_disable_and_name_authority_reuse(sql):
    identity,sources,lane,base=setup(sql,text='My name is Joan.')
    p=read(sql,lane,base)
    assert rpc(sql,'read_lifetime_profile_page',f"'{lane}','{base['token']}'",check=False).returncode!=0
    assert rpc(sql,'lock_lifetime_memoir_lane_publication',literal(fence(p)),owner=OTHER,check=False).returncode!=0
    commit(sql,lane,p,result(p,'name','Joan'))
    assert profile(sql)['name']=='Joan'
    assert sql('select authority from public.user_lifetime_chosen_name;').stdout.strip()=='generated'
    rpc(sql,'change_user_narrator_source',f"{literal(identity['project_id'])},'{sources[0]['id']}',1,'withdraw',null")
    assert 'name' not in profile(sql)
    sql('update public.lifetime_two_lane_rollout set enabled=false;')
    assert service(sql,'read_lifetime_profile_page',f"'{lane}','{base['token']}'") is None


def test_profile_metadata_cascades_with_project_fixture_reset(sql):
    identity,sources,lane,base=setup(sql)
    manual(sql,{'profile_confirm_all':True})
    sql('truncate public.user_memoir_project cascade;')
    assert sql('select count(*) from public.user_lifetime_profile_authority;').stdout.strip()=='0'
    identity,sources,lane,base=setup(sql)
    assert read(sql,lane,base)['profile_context']['work_mode']=='extract'


def test_explicit_name_release_uses_canonical_authority_and_exact_invalidation(sql):
    identity,sources,lane,base=setup(sql,text='My name is Joan.')
    manual(sql,{'name':'Mary'})
    manual(sql,{'profile_release_fields':['name']})
    base=reclaim(sql,lane);p=read(sql,lane,base)
    assert 'name' in p['profile_context']['targets']
    commit(sql,lane,p,result(p,'name','Joan'))
    assert profile(sql)['name']=='Joan'
    assert sql('select authority||\':\'||source_id from public.user_lifetime_chosen_name;').stdout.strip()==f"generated:{sources[0]['id']}"
    rpc(sql,'change_user_narrator_source',f"{literal(identity['project_id'])},'{sources[0]['id']}',1,'withdraw',null")
    assert 'name' not in profile(sql)
    sql(as_user("update public.user_profile set profile=profile||'{\"name\":\"Joan\"}';"))
    assert 'name' not in profile(sql)
    assert manual(sql,{'name':'Explicit Joan'})['name']=='Explicit Joan'


def test_old_uncovered_name_cannot_overwrite_newer_literal_name(sql):
    identity,sources,lane,base=setup(sql,rounds=0)
    first=source(sql,identity,'My name is Joan.',1)
    source(sql,identity,'A memory.',2)
    newer=source(sql,identity,'My name is Mary.',3)
    assert sql(as_user(f"select public.persist_lifetime_chosen_name('{identity['conversation_id']}','{newer['id']}',1,'Mary');"),check=False).returncode!=0
    # The writer is private: emulate its existing fenced A caller as owner.
    sql(f"set request.jwt.claim.sub='{OWNER}'; select public.persist_lifetime_chosen_name('{identity['conversation_id']}','{newer['id']}',1,'Mary');")
    for n in range(4,6):source(sql,identity,'Another memory.',n)
    base=reclaim(sql,lane);p=read(sql,lane,base)
    assert p['source']['id']==first['id'] and p['profile_context']['reference']['name']['value']=='Mary'
    with pytest.raises(AssertionError):commit(sql,lane,p,result(p,'name','Joan'))
    assert profile(sql)['name']=='Mary'
    assert sql('select source_id from public.user_lifetime_chosen_name;').stdout.strip()==newer['id']


@pytest.mark.parametrize('action', ['edit', 'withdraw'])
@pytest.mark.parametrize('name', ['Mary', 'Joan'])
def test_newer_lane_a_name_replaces_background_dependencies(sql, action, name):
    from test_interview_work_plan_postgres import plan

    identity, sources, lane, base = setup(sql, text='My name is Joan.')
    page = read(sql, lane, base)
    commit(sql, lane, page, result(page, 'name', 'Joan'))
    turn = str(uuid4())
    accepted = rpc(sql, 'accept_user_interview_turn',
        f"{literal(identity['project_id'])},'{turn}',{literal('My name is ' + name)},'narrator_chat','en-AU'")
    sql(as_user(f"select public.acquire_user_agent_turn_lease('{OLD}');"))
    captured = rpc(sql, 'capture_lifetime_fence', f"'{identity['conversation_id']}','{OLD}'")
    rpc(sql, 'commit_lifetime_turn',
        f"{literal(captured)},'{turn}',{literal(plan(name=name))},'[]','Hello.','[]','new-name-thread','v1','fixture'")
    assert profile(sql)['name'] == name
    rpc(sql, 'change_user_narrator_source',
        f"{literal(identity['project_id'])},'{sources[0]['id']}',1,'{action}',"
        + (literal('An unrelated correction.') if action == 'edit' else 'null'))
    assert profile(sql)['name'] == name
    assert sql('select source_id from public.user_lifetime_chosen_name;').stdout.strip() == accepted['source']['id']
    assert sql("select count(*) from public.user_lifetime_profile_dependency where field='name';").stdout.strip() == '0'
    rpc(sql, 'change_user_narrator_source',
        f"{literal(identity['project_id'])},'{accepted['source']['id']}',1,'withdraw',null")
    assert 'name' not in profile(sql)


def test_reply_only_coverage_is_success_and_not_manual_skip(sql):
    identity=rpc(sql,'resolve_lifetime_conversation','null')
    accepted=rpc(sql,'accept_two_lane_interview_turn',f"{literal(identity['project_id'])},'{uuid4()}','My name is Joan.'")
    sql("update public.user_interview_turn set collector='{\"plan\":{\"work\":{\"mode\":\"reply_only\"}}}';")
    sql(f"insert into public.user_completed_round(user_id,project_id,turn_id,ordinal) values('{OWNER}',{literal(identity['project_id'])},'{accepted['source']['client_turn_id']}',1);")
    lane=sql("select id from public.user_memoir_lane where skill='timeline';").stdout.strip()
    base=service(sql,'claim_memoir_lane',f"'{lane}',300");p=read(sql,lane,base)
    assert p['profile_context']['work_mode']=='reply_only'
    commit(sql,lane,p)
    assert rpc(sql,'read_lifetime_profile_automation','')['progress']['status']=='covered'
    assert sql('select skipped from public.user_lifetime_profile_receipt;').stdout.strip()=='f'


def test_empty_targets_skip_does_not_fabricate_manual_confirmation(sql):
    values={'name':'Joan','birth_year':1960,'birth_date_expression':'around 1960',
        'birth_place':'Hobart','childhood_place':'Sydney','avatar_style':'female'}
    sql(f"insert into public.user_profile(user_id,profile) values('{OWNER}',{literal(values)}) on conflict(user_id) do update set profile=excluded.profile;")
    identity,sources,lane,base=setup(sql);p=read(sql,lane,base)
    assert p['profile_context']['targets']==[] and p['profile_context']['work_mode']=='skip'
    commit(sql,lane,p)
    saved=rpc(sql,'read_lifetime_profile_automation','')
    assert not saved['stopped'] and not saved['manual_complete']
    assert saved['progress']['covered_round']==0 and saved['progress']['status']=='skipped'


def test_authenticated_progress_is_read_only_and_reports_pending_versions(sql):
    identity,sources,lane,base=setup(sql);p=read(sql,lane,base)
    commit(sql,lane,p,result(p,'birth_year',1960))
    before=sql('select profile::text||preference_revision from public.user_profile join public.user_lifetime_conversation using(user_id);').stdout
    saved=rpc(sql,'read_lifetime_profile_automation','')
    assert saved['progress']['status']=='covered' and not saved['progress']['pending_source_changes']
    assert rpc(sql,'read_lifetime_profile_automation','',owner=OTHER,check=False).returncode!=0
    assert sql('select profile::text||preference_revision from public.user_profile join public.user_lifetime_conversation using(user_id);').stdout==before
    rpc(sql,'change_user_narrator_source',f"{literal(identity['project_id'])},'{sources[0]['id']}',1,'edit','I was born in 1961.'")
    saved=rpc(sql,'read_lifetime_profile_automation','')
    assert saved['progress']['covered_round']==1 and saved['progress']['pending_source_changes']
    assert saved['progress']['status']=='awaiting_checkpoint'
    base=reclaim(sql,lane)
    assert read(sql,lane,base) is None
    for table in ['authority','progress','coverage','receipt','dependency']:
        assert sql(as_user(f'select * from public.user_lifetime_profile_{table};'),check=False).returncode!=0


@pytest.mark.parametrize('action',['edit','withdraw'])
def test_source_invalidation_preserves_independently_supported_fields(sql,action):
    identity,sources,lane,base=setup(sql,rounds=5)
    p=read(sql,lane,base);commit(sql,lane,p,result(p,'birth_year',1960))
    p=read(sql,lane,base);commit(sql,lane,p,result(p,'childhood_place','Hobart'))
    rpc(sql,'change_user_narrator_source',f"{literal(identity['project_id'])},'{sources[0]['id']}',1,'{action}',"
        +(literal('My corrected memory.') if action=='edit' else 'null'))
    assert 'birth_year' not in profile(sql) and profile(sql)['childhood_place']=='Hobart'
    sql(as_user("update public.user_profile set profile=profile||'{\"birth_year\":1960}';"))
    assert 'birth_year' not in profile(sql)


@pytest.mark.parametrize('route',['profile','narrator'])
def test_privacy_changes_invalidate_profile_immediately_without_another_model_run(sql,route):
    identity,sources,lane,base=setup(sql);p=read(sql,lane,base)
    commit(sql,lane,p,result(p,'birth_year',1960))
    if route=='profile':
        sql(as_user("update public.user_profile set profile=profile||'{\"memory_preferences\":{\"excluded_topics\":[\"birth\"]}}';"))
    else:
        source(sql,identity,'Please do not discuss my birth.')
    assert 'birth_year' not in profile(sql)
    assert sql('select count(*) from public.user_lifetime_profile_receipt;').stdout.strip()=='1'
    assert sql('select count(*) from public.user_lifetime_profile_dependency;').stdout.strip()=='0'


def test_confirm_all_converts_generated_name_to_independent_explicit_authority(sql):
    identity,sources,lane,base=setup(sql,text='My name is Joan.')
    p=read(sql,lane,base);commit(sql,lane,p,result(p,'name','Joan'))
    manual(sql,{'profile_confirm_all':True})
    rpc(sql,'change_user_narrator_source',f"{literal(identity['project_id'])},'{sources[0]['id']}',1,'withdraw',null")
    assert profile(sql)['name']=='Joan' and rpc(sql,'read_lifetime_profile_automation','')['stopped']
    assert sql('select authority from public.user_lifetime_chosen_name;').stdout.strip()=='explicit'


def test_source_deletion_invalidates_before_dependency_cascade(sql):
    identity,sources,lane,base=setup(sql);p=read(sql,lane,base)
    commit(sql,lane,p,result(p,'birth_year',1960))
    sql(f"delete from public.user_narrator_source where id='{sources[0]['id']}';")
    assert 'birth_year' not in profile(sql)


@pytest.mark.parametrize('writer',['manual','background'])
def test_birth_date_expression_length_limit_matches_application_contract(sql,writer):
    identity,sources,lane,base=setup(sql);p=read(sql,lane,base)
    if writer=='manual':
        with pytest.raises(AssertionError):manual(sql,{'birth_date_expression':'a'*121})
    else:
        with pytest.raises(AssertionError):commit(sql,lane,p,result(p,'birth_date_expression','a'*121))
    assert 'birth_date_expression' not in profile(sql)


def test_overlap_keeps_cross_boundary_fact_and_exact_absolute_evidence(sql):
    quote='I was born in 1960.'
    text='前'*2039+quote+'後'*100
    identity,sources,lane,base=setup(sql,text=text)
    p=read(sql,lane,base)
    assert quote not in p['source']['text'] and p['source']['char_end']==2048
    commit(sql,lane,p)
    assert rpc(sql,'read_lifetime_profile_automation','')['progress']['covered_round']==0
    p=read(sql,lane,base)
    assert p['source']['char_start']==1792 and p['profile_context']['cursor']['char_start']==2048
    assert quote in p['source']['text']
    out=result(p,'birth_year',1960)
    out['profile_patch'][0]['source_refs'][0].update(quote=quote,char_start=2039,char_end=2039+len(quote))
    commit(sql,lane,p,out)
    assert profile(sql)['birth_year']==1960
    assert sql("select char_start||':'||char_end from public.user_lifetime_profile_dependency;").stdout.strip()==f'2039:{2039+len(quote)}'
    assert rpc(sql,'read_lifetime_profile_automation','')['progress']['covered_round']==1


def test_existing_explicit_blank_name_is_protected_by_recorded_authority(sql):
    identity,sources,lane,base=setup(sql)
    manual(sql,{'name':None})
    # Simulate the pre-migration authority evidence, which already records clears.
    sql('delete from public.user_lifetime_profile_authority;')
    base=reclaim(sql,lane);p=read(sql,lane,base)
    assert 'name' not in p['profile_context']['targets']
    assert p['profile_context']['reference']['name']=={'value':None,'authority':'manual'}


@pytest.mark.parametrize('name',['Joan',None])
def test_confirm_all_without_values_blocks_later_a_literal_name(sql,name):
    identity,sources,lane,base=setup(sql,text='My name is Joan. My name is Mary.')
    if name:
        p=read(sql,lane,base);commit(sql,lane,p,result(p,'name',name))
    manual(sql,{'profile_confirm_all':True})
    sql(f"set request.jwt.claim.sub='{OWNER}'; select public.persist_lifetime_chosen_name("
        f"'{identity['conversation_id']}','{sources[0]['id']}',1,'Mary');")
    saved=profile(sql)
    assert saved.get('name')==name and saved['profile_automation']['field_locks']['name']=='manual'
    assert saved['profile_automation']['stopped']
    assert sql('select authority from public.user_lifetime_chosen_name;').stdout.strip()=='explicit'
