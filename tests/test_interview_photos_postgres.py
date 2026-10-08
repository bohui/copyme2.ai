"""Issue 41 real PostgreSQL policies, immutable acceptance and evidence fencing."""
import json
import os
from uuid import uuid4

import pytest
from test_agent_commit_postgres import database as native_database, as_user, OWNER, OTHER, OLD
from test_guest_conversation_transfer import attachment_database, THIRD
from test_private_rounds_postgres import private_database
from test_shared_memory_events_postgres import event_database, sql, rpc, literal, extract, TURN


@pytest.fixture(scope='module')
def database():
    if os.environ.get('MEMOIR_TEST_POSTGRES_BACKEND') == 'single-user':
        from interview_postgres_single import single_database
        setup = single_database()
    else:
        setup = native_database.__wrapped__()
    sql = next(setup)
    # Supabase supplies these schema grants/RLS outside application migrations.
    sql('grant usage on schema storage to authenticated; '
        'grant select,insert,update,delete on storage.objects to authenticated; '
        'alter table storage.objects enable row level security;')
    # Controlled Storage-operation boundary. The application policy invokes
    # the documented upstream helper; native tests exercise real RLS with each
    # operation. Actual Storage HTTP remains a separate acceptance check.
    sql(r"""create function storage.allow_any_operation(allowed text[]) returns boolean
      language sql stable as $$select coalesce(regexp_replace(current_setting('storage.operation',true),
        '^storage\.','')=any(allowed),false)$$;""")
    try:
        yield sql
    finally:
        try: next(setup)
        except StopIteration: pass


def upload(sql, owner=OWNER):
    record = rpc(sql,'begin_user_interview_photo', "'project','{\"content_type\":\"image/png\",\"byte_size\":8,\"width\":2,\"height\":2}'",owner=owner)
    sql(as_user(f"set storage.operation='storage.object.upload'; insert into storage.objects(bucket_id,name) values ('memoir-private-photos',{literal(record['object_path'])});",owner))
    return rpc(sql,'finish_user_interview_photo',f"'project','{record['id']}'",owner=owner)


def accept(sql, text='I visited this gate.', *, turn=TURN, photos=(), selection=None, owner=OWNER):
    return rpc(sql,'accept_user_interview_turn',f"'project','{turn}',{literal(text)},'narrator_chat','en-AU',{literal(list(photos))}::jsonb,{literal(selection) if selection is not None else 'null'}::jsonb",owner=owner)


def save(sql, turn, plan=None, associations=()):
    plan = plan or {'candidates':[{'id':'next','question':'Who came with you?', 'context':{},'order':1}], 'chosen_id':'next','active_event_id':None}
    sql(as_user(f"select public.acquire_user_agent_turn_lease('{OLD}');"))
    return rpc(sql,'save_user_interview_plan',f"'project','{turn['client_turn_id']}',{literal(plan)}::jsonb,{literal(list(associations))}::jsonb,'{OLD}'")


def association(turn, photo, **extra):
    return {'photo_id':'upload:'+photo['id'], 'source_id':turn['source']['id'],'source_version':1,
            'quote':'I visited this gate.', 'description':'The storyteller recalls visiting this gate.',
            'provenance':'narrator', **extra}


def test_private_storage_and_metadata_are_owner_only_even_for_same_project(sql):
    if os.environ.get('MEMOIR_TEST_POSTGRES_BACKEND') == 'single-user':
        pytest.skip('PostgreSQL single-user mode bypasses RLS; native transport is required')
    photo = upload(sql)
    accept(sql,'Separate owner project.', owner=OTHER)
    for user in (OTHER, THIRD):
        assert rpc(sql,'read_user_interview_photo',f"'project','{photo['id']}'",owner=user) is None
        assert sql(as_user(f"set storage.operation='storage.object.get_authenticated'; select count(*) from storage.objects where name={literal(photo['object_path'])};",user)).stdout.splitlines()[-1]=='0'
        assert sql(as_user(f"set storage.operation='storage.object.upload'; insert into storage.objects(bucket_id,name) values ('memoir-private-photos',{literal(photo['object_path'])});",user),check=False).returncode != 0
    assert sql('set role anon; select * from public.user_interview_photo;',check=False).returncode != 0
    assert sql('set role anon; select * from storage.objects;',check=False).returncode != 0


def test_photo_only_acceptance_never_fabricates_narrator_source_or_round(sql):
    photo=upload(sql)
    turn=accept(sql,'',photos=[photo['id']])
    assert turn['source'] is None and turn['photo_context'][0]['photo_id']=='upload:'+photo['id']
    assert rpc(sql,'read_user_memory_events',"'project'")['sources']==[]
    assert sql('select count(*) from public.user_completed_round;').stdout.strip()=='0'


def test_source_photo_snapshot_retry_is_immutable_and_new_selection_survives(sql):
    first=upload(sql); second=upload(sql)
    original=accept(sql,photos=[first['id']])
    replay=accept(sql,photos=[second['id']])
    assert replay==original
    assert len(rpc(sql,'read_user_memory_events',"'project'")['sources'])==1


def test_reference_cue_consumption_is_atomic_and_reselection_is_fenced(sql):
    photo={'key':'https://example.org/a.jpg','image_url':'https://example.org/a.jpg','title':'Gate'}
    profile={'photo_memories':{'project':{'favorites':[photo],'selected':photo['key'],'selection_revision':'old'}}}
    sql(f"insert into public.user_profile(user_id,profile) values ('{OWNER}',{literal(profile)}::jsonb);")
    selected={'key':photo['key'],'revision':'old'}
    turn=accept(sql,selection=selected)
    assert turn['consumed_photo_key']==photo['key'] and turn['consumed_photo_revision']=='old'
    state=json.loads(sql('select profile from public.user_profile;').stdout)['photo_memories']['project']
    assert state['selected'] is None and state['favorites']==[photo]
    profile['photo_memories']['project']['selection_revision']='new'
    sql(f"update public.user_profile set profile={literal(profile)}::jsonb;")
    assert accept(sql,selection=selected)==turn
    assert json.loads(sql('select profile from public.user_profile;').stdout)['photo_memories']['project']['selected']==photo['key']
    with pytest.raises(AssertionError,match='photo selection changed'):
        accept(sql,turn=str(uuid4()),selection=selected)


def test_pending_association_binds_only_to_unique_matching_canonical_evidence(sql):
    photo=upload(sql); turn=accept(sql,photos=[photo['id']])
    save(sql,turn,associations=[association(turn,photo)])
    context=rpc(sql,'read_user_interview_context',"'project'")
    assert context['photo_associations'][0]['event_id'] is None
    source=turn['source']; ref={'source_id':source['id'],'version':1,'quote':source['text']}
    event=extract(sql,[source],[{'kind':'event','title':'Visit','source_refs':[ref]}])['events'][0]
    context=rpc(sql,'read_user_interview_context',"'project'")
    assert context['photo_associations'][0]['event_id']==event['id']
    assert rpc(sql,'read_user_memory_events',"'project'")['events'][0]['photo_associations'][0]['quote']==source['text']


def test_newer_turn_and_source_edit_reject_stale_plan_and_photo_links(sql):
    photo=upload(sql); first=accept(sql,photos=[photo['id']])
    newer=accept(sql,'Another memory.',turn=str(uuid4()))
    with pytest.raises(AssertionError,match='stale interview turn'):
        save(sql,first,associations=[association(first,photo)])
    rpc(sql,'change_user_narrator_source',f"'project','{newer['source']['id']}',1,'edit','Corrected memory.'")
    with pytest.raises(AssertionError,match='stale interview turn'):
        save(sql,newer)


def test_forged_photo_or_evidence_cannot_be_committed(sql):
    photo=upload(sql); other=upload(sql,OTHER)
    with pytest.raises(AssertionError,match='photo unavailable'):
        accept(sql,photos=[other['id']])
    turn=accept(sql,photos=[photo['id']])
    with pytest.raises(AssertionError,match='quote'):
        save(sql,turn,associations=[association(turn,photo,quote='Fabricated words')])
    with pytest.raises(AssertionError,match='photo unavailable'):
        save(sql,turn,associations=[association(turn,other)])


def test_plan_bounds_and_lifecycle_removes_derived_photo_context(sql):
    photo=upload(sql); turn=accept(sql,photos=[photo['id']])
    invalid={'candidates':[{'id':str(i),'question':'Question?', 'context':{},'order':i} for i in range(6)],'chosen_id':'0'}
    with pytest.raises(AssertionError,match='invalid interview plan'):
        save(sql,turn,plan=invalid)
    save(sql,turn,associations=[association(turn,photo)])
    before=int(sql("select policy_epoch from public.user_memoir_project;").stdout)
    rpc(sql,'delete_user_interview_photo',f"'project','{photo['id']}'")
    context=rpc(sql,'read_user_interview_context',"'project'")
    assert context['photo_associations']==[] and context['plan'] is None
    assert rpc(sql,'read_user_interview_turn',f"'project','{TURN}'")['photo_context']==[]
    assert int(sql('select policy_epoch from public.user_memoir_project;').stdout)>before
    if os.environ.get('MEMOIR_TEST_POSTGRES_BACKEND') != 'single-user':
        assert sql(as_user(f"set storage.operation='storage.object.get_authenticated'; select count(*) from storage.objects where name={literal(photo['object_path'])};")).stdout.splitlines()[-1]=='0'


def test_saved_reply_replays_identical_question_and_cards_after_lost_delivery(sql):
    photo=upload(sql); turn=accept(sql,photos=[photo['id']])
    sql(as_user(f"select public.acquire_user_agent_turn_lease('{OLD}');"))
    plan={'candidates':[{'id':'next','question':'Who came with you?','context':{'photo_id':'upload:'+photo['id']},'order':1}],
          'chosen_id':'next','active_event_id':None}
    reply='You remember visiting this gate. Who came with you?'
    result=rpc(sql,'save_user_interview_plan',f"'project','{TURN}',{literal(plan)}::jsonb,'[]'::jsonb,'{OLD}',{literal(reply)},"
               f"{literal(['upload:'+photo['id']])}::jsonb,'thread-1'")
    recovered=accept(sql,photos=[])
    assert recovered['reply']==reply and recovered['plan']==plan and recovered['thread_id']=='thread-1'
    assert recovered['response_photos']==result['response_photos'] and len(recovered['response_photos'])==1
    assert sql('select count(*) from public.user_narrator_source;').stdout.strip()=='1'
    assert sql('select count(*) from public.user_completed_round;').stdout.strip()=='0'


def test_upload_retry_identity_preserves_photo_and_checks_original_content(sql):
    key=str(uuid4())
    info={'content_type':'image/png','byte_size':8,'width':2,'height':2,'content_sha256':'a'*64}
    args=f"'project',{literal(info)}::jsonb,'{key}'"
    first=rpc(sql,'begin_user_interview_photo',args)
    sql(as_user(f"set storage.operation='storage.object.upload'; insert into storage.objects(bucket_id,name) values ('memoir-private-photos',{literal(first['object_path'])});"))
    # The request lost its response after bytes but before metadata completion.
    second=rpc(sql,'begin_user_interview_photo',args)
    assert second['id']==first['id'] and second['status']=='ready'
    assert rpc(sql,'begin_user_interview_photo',args)==second
    info['content_sha256']='b'*64
    with pytest.raises(AssertionError,match='upload retry identity conflict'):
        rpc(sql,'begin_user_interview_photo',f"'project',{literal(info)}::jsonb,'{key}'")


def test_ambiguous_event_evidence_never_attaches_photo_to_first_match(sql):
    photo=upload(sql); turn=accept(sql,photos=[photo['id']])
    save(sql,turn,associations=[association(turn,photo)])
    source=turn['source']; ref={'source_id':source['id'],'version':1,'quote':source['text']}
    extract(sql,[source],[{'kind':'event','title':title,'source_refs':[ref]} for title in ('Visit one','Visit two')])
    links=rpc(sql,'read_user_interview_context',"'project'")['photo_associations']
    assert len(links)==1 and links[0]['event_id'] is None and links[0]['status']=='pending'


def test_source_withdrawal_invalidates_links_plan_and_cached_replay(sql):
    photo=upload(sql); turn=accept(sql,photos=[photo['id']])
    save(sql,turn,associations=[association(turn,photo)])
    rpc(sql,'change_user_narrator_source',f"'project','{turn['source']['id']}',1,'withdraw'")
    context=rpc(sql,'read_user_interview_context',"'project'")
    assert context['photo_associations']==[] and context['plan'] is None and context['photos']==[]


def test_authorized_guest_transfer_rebinds_private_bytes_and_revokes_old_principal(sql):
    sql(f"update auth.users set is_anonymous=(id='{OWNER}');")
    photo=upload(sql); turn=accept(sql,photos=[photo['id']])
    save(sql,turn,associations=[association(turn,photo)])
    sql(as_user(f"select public.release_user_agent_turn_lease('{OLD}');"))
    token='ab'*32
    rpc(sql,'prepare_guest_conversation_transfer',f"'{token}','project','[]'::jsonb")
    transfer=rpc(sql,'attach_guest_conversation',f"'{token}'",owner=OTHER)
    assert rpc(sql,'attach_guest_conversation',f"'{token}'",owner=OTHER)==transfer
    assert rpc(sql,'read_user_interview_photo',f"'project','{photo['id']}'",owner=OWNER) is None
    assert rpc(sql,'read_user_interview_photo',f"'project','{photo['id']}'",owner=OTHER)['object_path']==photo['object_path']
    assert rpc(sql,'read_user_interview_turn',f"'project','{TURN}'",owner=OWNER) is None
    assert rpc(sql,'read_user_interview_turn',f"'project','{TURN}'",owner=OTHER)['photo_context'][0]['id']==photo['id']
    assert rpc(sql,'read_user_interview_context',"'project'",owner=OWNER)['photo_associations']==[]
    assert len(rpc(sql,'read_user_interview_context',"'project'",owner=OTHER)['photo_associations'])==1
    assert rpc(sql,'attach_guest_conversation',f"'{token}'",owner=THIRD,check=False).returncode != 0
    if os.environ.get('MEMOIR_TEST_POSTGRES_BACKEND') != 'single-user':
        for principal,count in ((OWNER,'0'),(THIRD,'0'),(OTHER,'1')):
            assert sql(as_user(f"set storage.operation='storage.object.get_authenticated'; select count(*) from storage.objects where name={literal(photo['object_path'])};",principal)).stdout.splitlines()[-1]==count


def test_favourite_removal_leaves_confirmed_source_association(sql):
    photo=upload(sql); turn=accept(sql,photos=[photo['id']])
    save(sql,turn,associations=[association(turn,photo)])
    source=turn['source']; ref={'source_id':source['id'],'version':1,'quote':source['text']}
    extract(sql,[source],[{'kind':'event','title':'Visit','source_refs':[ref]}])
    sql(f"insert into public.user_profile(user_id,profile) values ('{OWNER}','{{}}') on conflict(user_id) do update set profile='{{}}';")
    context=rpc(sql,'read_user_interview_context',"'project'")
    assert context['photo_associations'][0]['status']=='confirmed' and context['plan'] is not None


@pytest.mark.parametrize('invalidate',['source','photo','newer_turn'])
def test_final_conversation_commit_rejects_invalidated_saved_collector(sql,invalidate):
    photo=upload(sql); turn=accept(sql,photos=[photo['id']])
    sql(as_user(f"select public.acquire_user_agent_turn_lease('{OLD}');"))
    plan={'candidates':[],'chosen_id':None,'active_event_id':None}
    reply='We can pause here.'
    rpc(sql,'save_user_interview_plan',f"'project','{TURN}',{literal(plan)}::jsonb,'[]'::jsonb,'{OLD}',{literal(reply)},'[]','thread'")
    if invalidate=='source':
        rpc(sql,'change_user_narrator_source',f"'project','{turn['source']['id']}',1,'withdraw'")
    elif invalidate=='photo':
        rpc(sql,'delete_user_interview_photo',f"'project','{photo['id']}'")
    else:
        accept(sql,'Newer.',turn=str(uuid4()))
    with pytest.raises(AssertionError,match='stale interview publication'):
        rpc(sql,'commit_user_agent_turn',f"'{OLD}','thread',{literal('Storyteller: I visited this gate.'+chr(10)+'Memory Spark: '+reply)},'{{}}',null,'project','{TURN}',true")
    assert sql('select count(*) from public.user_completed_round;').stdout.strip()=='0'


def test_storage_operation_helper_fails_closed_for_missing_and_unknown_context(sql):
    for op in ('', 'object.sign', 'object.sign_many', 'object.get_public', 'object.list', 'object'):
        assert sql(as_user(f"set storage.operation={literal(op)}; select public.interview_storage_operation_allowed(array['object.get_authenticated']);")).stdout.splitlines()[-1]=='f'
    assert sql(as_user("set storage.operation='storage.object.get_authenticated'; select public.interview_storage_operation_allowed(array['object.get_authenticated']);")).stdout.splitlines()[-1]=='t'


def test_native_policies_block_signing_and_allow_only_deleted_object_cleanup(sql):
    if os.environ.get('MEMOIR_TEST_POSTGRES_BACKEND') == 'single-user':
        pytest.skip('PostgreSQL single-user mode bypasses RLS; native transport is required')
    assert sql(as_user("select row_security_active('storage.objects');")).stdout.splitlines()[-1]=='t'
    photo=upload(sql)
    for op in ('', 'storage.object.sign', 'storage.object.sign_many', 'storage.object.get_public', 'storage.object.list'):
        assert sql(as_user(f"set storage.operation={literal(op)}; select count(*) from storage.objects where name={literal(photo['object_path'])};")).stdout.splitlines()[-1]=='0'
    rpc(sql,'delete_user_interview_photo',f"'project','{photo['id']}'")
    assert sql(as_user(f"set storage.operation='object.get_authenticated'; select count(*) from storage.objects where name={literal(photo['object_path'])};")).stdout.splitlines()[-1]=='0'
    sql(as_user(f"set storage.operation='object.delete_many'; delete from storage.objects where name={literal(photo['object_path'])};"))
    assert sql(f"select count(*) from storage.objects where name={literal(photo['object_path'])};").stdout.strip()=='0'


def test_canonical_history_does_not_fossilize_current_private_photo_links(sql):
    photo=upload(sql); first=accept(sql,photos=[photo['id']]); source=first['source']
    save(sql,first,associations=[association(first,photo)])
    ref={'source_id':source['id'],'version':1,'quote':source['text']}
    event=extract(sql,[source],[{'kind':'event','title':'Visit','source_refs':[ref]}])['events'][0]
    later=accept(sql,'My parents came with me.',turn=str(uuid4()))['source']
    extract(sql,[later],[{'existing_id':event['id'],'expected_revision':event['revision'],'kind':'event','title':'Visit',
                         'source_refs':[{'source_id':later['id'],'version':1,'quote':later['text']}]}])
    assert sql("select count(*) from public.user_memory_event_revision where record ? 'photo_associations';").stdout.strip()=='0'
    assert len(rpc(sql,'read_user_memory_events',"'project'")['events'][0]['photo_associations'])==1


def test_duplicate_quote_occurrences_remain_unresolved(sql):
    photo=upload(sql); turn=accept(sql,'I visited this gate. Later I visited this gate.',photos=[photo['id']])
    save(sql,turn,associations=[association(turn,photo)])
    source=turn['source']; ref={'source_id':source['id'],'version':1,'quote':source['text']}
    extract(sql,[source],[{'kind':'event','title':'Visit','source_refs':[ref]}])
    assert rpc(sql,'read_user_interview_context',"'project'")['photo_associations'][0]['event_id'] is None


@pytest.mark.parametrize('original_text', ['I used to catch insects.', ''])
def test_deferred_photo_gains_first_link_only_when_later_narrator_discusses_it(sql, original_text):
    photo=upload(sql)
    first=accept(sql, original_text, photos=[photo['id']])
    save(sql, first)
    later=accept(sql, 'I visited this gate.', turn=str(uuid4()))
    assert later['photo_context']==[]
    context=rpc(sql, 'read_user_interview_context', "'project'")
    assert context['photo_associations']==[]
    assert any(p['photo_id']=='upload:'+photo['id'] for p in context['photos'])
    save(sql, later, associations=[association(later, photo)])
    pending=rpc(sql, 'read_user_interview_context', "'project'")['photo_associations']
    assert len(pending)==1 and pending[0]['source_id']==later['source']['id']
    assert pending[0]['source_version']==later['source']['version']
    assert pending[0]['quote']==later['source']['text'] and pending[0]['event_id'] is None
    source=later['source']; ref={'source_id':source['id'],'version':source['version'],'quote':source['text']}
    event=extract(sql,[source],[{'kind':'event','title':'Visit','source_refs':[ref]}])['events'][0]
    assert event['photo_associations'][0]['source_id']==source['id']
    assert event['photo_associations'][0]['photo_id']=='upload:'+photo['id']
    assert first['source'] is None or event['source_refs']==[ref]


@pytest.mark.parametrize('invalid_cue', ['never_accepted', 'withdrawn', 'edited', 'deleted', 'foreign_owner'])
def test_later_narration_cannot_associate_unavailable_prior_photo(sql, invalid_cue):
    photo=upload(sql, OTHER if invalid_cue=='foreign_owner' else OWNER)
    if invalid_cue not in {'never_accepted', 'foreign_owner'}:
        first=accept(sql, 'I used to catch insects.', photos=[photo['id']])
        if invalid_cue=='deleted':
            rpc(sql,'delete_user_interview_photo',f"'project','{photo['id']}'")
        else:
            action='withdraw' if invalid_cue=='withdrawn' else 'edit'
            rpc(sql,'change_user_narrator_source',f"'project','{first['source']['id']}',1,'{action}','Corrected childhood memory.'")
    later=accept(sql,'I visited this gate.',turn=str(uuid4()))
    with pytest.raises(AssertionError,match='photo unavailable'):
        save(sql,later,associations=[association(later,photo)])
    assert rpc(sql,'read_user_interview_context',"'project'")['photo_associations']==[]


@pytest.mark.parametrize('action', ['edit', 'withdraw', 'delete'])
@pytest.mark.parametrize('confirmed', [False, True])
def test_multiple_photo_evidence_spans_cannot_block_revocation(sql, action, confirmed):
    photo=upload(sql)
    text='I visited this gate. I returned here after school.'
    turn=accept(sql,text,photos=[photo['id']])
    proposals=[association(turn,photo,quote=quote) for quote in ('I visited this gate.', 'I returned here after school.')]
    save(sql,turn,associations=proposals)
    if confirmed:
        source=turn['source']
        extract(sql,[source],[{'kind':'event','title':'Visit '+str(index),'source_refs':[
            {'source_id':source['id'],'version':source['version'],'quote':proposal['quote']}]} for index,proposal in enumerate(proposals)])
    assert len(rpc(sql,'read_user_interview_context',"'project'")['photo_associations'])==2
    if action=='delete':
        rpc(sql,'delete_user_interview_photo',f"'project','{photo['id']}'")
    else:
        rpc(sql,'change_user_narrator_source',f"'project','{turn['source']['id']}',1,'{action}','Corrected childhood memory.'")
    context=rpc(sql,'read_user_interview_context',"'project'")
    assert context['photo_associations']==[] and context['photos']==[] and context['plan'] is None
    retired=json.loads(sql("select jsonb_agg(to_jsonb(l)) from public.user_interview_photo_link l;").stdout)
    assert len(retired)==2 and all(l['status']=='invalidated' for l in retired)
    assert all('I visited' not in l['quote'] and 'I returned' not in l['quote'] for l in retired)


def test_explicit_unlink_requires_new_accepted_cue_before_first_link_can_return(sql):
    photo=upload(sql); first=accept(sql,photos=[photo['id']])
    save(sql,first,associations=[association(first,photo)])
    link=rpc(sql,'read_user_interview_context',"'project'")['photo_associations'][0]
    rpc(sql,'unlink_user_interview_photo',f"'project','{link['id']}'")
    later=accept(sql,'I visited this gate.',turn=str(uuid4()))
    with pytest.raises(AssertionError,match='photo is not accepted or supported active event context'):
        save(sql,later,associations=[association(later,photo)])
    assert rpc(sql,'read_user_interview_context',"'project'")['photos']==[]
    reselected=accept(sql,'I visited this gate.',turn=str(uuid4()),photos=[photo['id']])
    save(sql,reselected,associations=[association(reselected,photo)])
    assert len(rpc(sql,'read_user_interview_context',"'project'")['photo_associations'])==1


def test_unlink_is_owner_scoped_and_retry_does_not_revoke_a_new_cue(sql):
    photo=upload(sql); first=accept(sql,photos=[photo['id']])
    save(sql,first,associations=[association(first,photo)])
    link=rpc(sql,'read_user_interview_context',"'project'")['photo_associations'][0]
    result=rpc(sql,'unlink_user_interview_photo',f"'project','{link['id']}'",owner=OTHER,check=False)
    assert result.returncode!=0 and 'photo association unavailable' in result.stderr
    assert len(rpc(sql,'read_user_interview_context',"'project'")['photo_associations'])==1
    rpc(sql,'unlink_user_interview_photo',f"'project','{link['id']}'")
    reselected=accept(sql,'I visited this gate.',turn=str(uuid4()),photos=[photo['id']])
    rpc(sql,'unlink_user_interview_photo',f"'project','{link['id']}'")
    save(sql,reselected,associations=[association(reselected,photo)])
    assert len(rpc(sql,'read_user_interview_context',"'project'")['photo_associations'])==1
    assert rpc(sql,'read_user_interview_photo',f"'project','{photo['id']}'")['status']=='ready'


def test_photo_caption_year_is_not_a_canonical_life_year(sql):
    turn=accept(sql,'This public photograph was taken in 1930, before I was born.')
    plan={'candidates':[{'id':'caption-year','question':'What do you remember from 1930?',
          'context':{'year':1930},'order':0}], 'chosen_id':'caption-year','active_event_id':None}
    with pytest.raises(AssertionError,match='unsupported candidate year'):
        save(sql,turn,plan=plan)
