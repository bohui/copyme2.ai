"""Real disposable PostgreSQL, native roles; no single-user/RLS bypass evidence."""
import json
from uuid import uuid4

import pytest
from test_agent_commit_postgres import database as native_database
from test_guest_conversation_transfer import attachment_database
from test_private_rounds_postgres import private_database
from test_shared_memory_events_postgres import event_database, sql, rpc, literal, OWNER, as_user
from test_agent_commit_postgres import OTHER


@pytest.fixture(scope='module')
def database():
    yield from native_database.__wrapped__(publication_tcp=True, postgres_image='postgres:17.6')


def server(sql, operation, recording_id=None, data=None, owner=OWNER, check=True):
    result = sql(f"select public.recording_server_operation('{owner}',{literal(operation)},"
        f"{literal(recording_id) if recording_id else 'null'}::uuid,{literal(data or {})}::jsonb);", check=check)
    return json.loads(result.stdout.splitlines()[-1]) if check else result


def info(**extra):
    return {'content_type':'audio/webm','codec':'opus','byte_size':10,'duration_seconds':0.2,
        'content_sha256':'a'*64, 'upload_key':str(uuid4()), **extra}


@pytest.fixture
def approved(sql):
    sql('truncate public.user_original_recording,public.user_original_recording_cancel cascade;')
    # Only this disposable fixture installs synthetic consent authority.
    sql("update public.original_recording_rollout set enabled=true; create or replace function "
        "public.original_recording_authorized(p_owner uuid,p_project_id text) returns boolean "
        "language sql stable security definer set search_path='' as $$select exists(select 1 from auth.users "
        "where id=p_owner and not is_anonymous)$$;")
    yield sql
    sql("update public.original_recording_rollout set enabled=false; create or replace function "
        "public.original_recording_authorized(p_owner uuid,p_project_id text) returns boolean "
        "language sql stable security definer set search_path='' as $$select false$$;")


def ready(sql, **extra):
    data=info(**extra); record=server(sql,'reserve',data=data)
    return server(sql,'finalize',record['id'],data)


def accept(sql, recordings, turn=None, owner=OWNER, two_lane=False):
    return rpc(sql,'accept_two_lane_interview_turn' if two_lane else 'accept_user_interview_turn',
        f"'project','{turn or uuid4()}','Edited words and typed clarification','narrator_transcript','en-AU','[]',null,{literal(recordings)}::jsonb",owner=owner)


def test_default_database_gate_denies_even_a_permanent_authenticated_owner(sql):
    assert server(sql,'reserve',data=info(),check=False).returncode != 0


def test_native_roles_cannot_forge_ready_metadata_or_access_another_owner(approved):
    sql=approved; record=ready(sql)
    assert sql(as_user(f"select public.recording_server_operation('{OWNER}','finalize','{record['id']}','{{}}');"),check=False).returncode != 0
    assert sql(as_user('select * from public.user_original_recording;'),check=False).returncode != 0
    assert rpc(sql,'read_user_original_recording',literal(record['id']),owner=OTHER) is None
    sql(f"update auth.users set is_anonymous=true where id='{OWNER}';")
    assert rpc(sql,'read_user_original_recording',literal(record['id'])) is None
    assert server(sql,'reserve',data=info(),check=False).returncode != 0


def test_upload_key_retries_keep_identity_and_never_infer_ready_from_object_existence(approved):
    sql=approved; data=info(); first=server(sql,'reserve',data=data)
    assert first['storage_status']=='pending'
    sql(f"insert into storage.objects(bucket_id,name) values('memoir-original-recordings',{literal(first['object_path'])});")
    replay=server(sql,'reserve',data=data)
    assert replay['id']==first['id'] and replay['storage_status']=='pending'
    assert server(sql,'reserve',data={**data,'content_sha256':'b'*64},check=False).returncode != 0
    assert ready(sql)['id'] != first['id']


def test_ordered_recordings_are_atomic_immutable_and_reloadable(approved):
    sql=approved; first,second=ready(sql),ready(sql); turn=str(uuid4())
    result=accept(sql,[second['id'],first['id']],turn)
    assert [r['id'] for r in result['recordings']]==[second['id'],first['id']]
    assert result['source']['text']=='Edited words and typed clarification'
    assert accept(sql,[second['id'],first['id']],turn)==result
    with pytest.raises(AssertionError,match='revision conflict'):
        accept(sql,[first['id'],second['id']],turn)
    with pytest.raises(AssertionError,match='unavailable'):
        accept(sql,[first['id']])
    assert sql('select count(*) from public.user_narrator_source;').stdout.strip()=='1'
    assert sql('select count(*) from public.user_completed_round;').stdout.strip()=='0'


def test_invalid_reference_rolls_back_all_source_acceptance(approved):
    sql=approved; good=ready(sql); pending=server(sql,'reserve',data=info())
    for ids in ([good['id'],good['id']], [good['id'],pending['id']], [good['id'],str(uuid4())]):
        with pytest.raises(AssertionError): accept(sql,ids)
    assert sql('select count(*) from public.user_narrator_source;').stdout.strip()=='0'
    assert sql("select lifecycle from public.user_original_recording where storage_status='ready';").stdout.strip()=='draft'


def test_audio_delete_keeps_text_and_tombstone_until_exact_cleanup_completes(approved):
    sql=approved; recording=ready(sql); result=accept(sql,[recording['id']])
    tombstone=server(sql,'delete',recording['id'])
    assert tombstone['cleanup_status']=='pending'
    assert rpc(sql,'read_user_original_recording',literal(recording['id'])) is None
    assert rpc(sql,'read_user_interview_turn',f"'project','{result['client_turn_id']}'")['recordings']==[]
    assert sql('select text from public.user_narrator_source;').stdout.strip()==result['source']['text']
    assert server(sql,'delete',recording['id'])['cleanup_status']=='pending'
    assert server(sql,'cleanup_complete',recording['id'],{'write_revision':tombstone['write_revision']})['cleanup_status']=='complete'


def test_source_correction_preserves_provenance_withdrawal_fences_it(approved):
    sql=approved; recording=ready(sql); result=accept(sql,[recording['id']]); source=result['source']
    rpc(sql,'change_user_narrator_source',f"'project','{source['id']}',1,'edit','Corrected name'")
    assert rpc(sql,'read_user_original_recording',literal(recording['id']))['id']==recording['id']
    rpc(sql,'change_user_narrator_source',f"'project','{source['id']}',2,'withdraw'")
    assert rpc(sql,'read_user_original_recording',literal(recording['id'])) is None


def test_project_deletion_fences_original_and_retains_cleanup_tombstone(approved):
    sql=approved; recording=ready(sql);accept(sql,[recording['id']])
    sql("delete from public.user_memoir_project where project_id='project';")
    assert rpc(sql,'read_user_original_recording',literal(recording['id'])) is None
    state=json.loads(sql(f"select to_jsonb(r) from public.user_original_recording r where id='{recording['id']}';").stdout.strip())
    assert state['lifecycle']=='deleted' and state['cleanup_status']=='pending'


def test_supported_guest_transfer_moves_recording_ownership_in_existing_transaction(approved):
    sql=approved;recording=ready(sql);accepted=accept(sql,[recording['id']]);source=accepted['source']
    sql(f"update auth.users set is_anonymous=true where id='{OWNER}';")
    token='ab'*32
    rpc(sql,'prepare_guest_conversation_transfer',f"'{token}','project','[]'::jsonb")
    result=rpc(sql,'attach_guest_conversation',f"'{token}',false",owner=OTHER)
    assert result['guest_user_id']==OWNER
    assert rpc(sql,'read_user_original_recording',literal(recording['id'])) is None
    transferred=rpc(sql,'read_user_original_recording',literal(recording['id']),owner=OTHER)
    assert transferred['id']==recording['id']
    assert rpc(sql,'read_user_source_recordings',f"'project','{source['id']}'",owner=OTHER)[0]['id']==recording['id']
    assert rpc(sql,'attach_guest_conversation',f"'{token}',false",owner=OTHER)==result
    assert sql('select count(*) from public.user_original_recording;').stdout.strip()=='1'


def test_discard_of_uncertain_draft_cannot_delete_an_already_accepted_original(approved):
    sql=approved;recording=ready(sql);accept(sql,[recording['id']])
    failed=server(sql,'delete',recording['id'],{'draft_only':True},check=False)
    assert failed.returncode != 0
    assert rpc(sql,'read_user_original_recording',literal(recording['id']))['backend_saved'] is True


def test_account_deletion_retains_inaccessible_cleanup_tombstone(approved):
    sql=approved;owner=str(uuid4())
    sql(f"insert into auth.users(id) values('{owner}');")
    record=server(sql,'reserve',owner=owner,data=info())
    sql(f"delete from auth.users where id='{owner}';")
    state=json.loads(sql(f"select to_jsonb(r) from public.user_original_recording r where id='{record['id']}';").stdout.strip())
    assert state['user_id'] is None and state['lifecycle']=='deleted' and state['cleanup_status']=='pending'


def test_upload_key_uniqueness_is_per_owner_and_attachment_does_not_change_upload_identity(approved):
    sql=approved;data=info();first=server(sql,'reserve',data=data)
    second=server(sql,'reserve',owner=OTHER,data=data)
    assert first['id']!=second['id']
    server(sql,'finalize',first['id'],data);accept(sql,[first['id']])
    assert server(sql,'reserve',data=data)['id']==first['id']


def test_interrupted_association_rolls_back_source_and_same_turn_recovers(approved):
    sql=approved;recording=ready(sql);turn=str(uuid4())
    sql("create function public.fixture_fail_association() returns trigger language plpgsql as $$begin raise exception 'synthetic association failure';end$$; create trigger fixture_fail_association before insert on public.user_source_recording for each row execute function public.fixture_fail_association();")
    try:
        with pytest.raises(AssertionError,match='synthetic association failure'):accept(sql,[recording['id']],turn)
    finally:sql('drop trigger fixture_fail_association on public.user_source_recording; drop function public.fixture_fail_association();')
    assert sql('select count(*) from public.user_narrator_source;').stdout.strip()=='0'
    assert rpc(sql,'read_user_original_recording',literal(recording['id']))['lifecycle']=='draft'
    assert accept(sql,[recording['id']],turn)['recordings'][0]['id']==recording['id']


def test_combined_clips_cannot_exceed_the_five_minute_turn_ceiling(approved):
    sql=approved;first=ready(sql,duration_seconds=200);second=ready(sql,duration_seconds=200)
    with pytest.raises(AssertionError,match='combined recording duration'):accept(sql,[first['id'],second['id']])
    assert sql('select count(*) from public.user_narrator_source;').stdout.strip()=='0'


def wait_for_database_lock_or_completion(dsn, name, future):
    import time
    from psycopg import connect
    until=time.monotonic()+5
    with connect(dsn,autocommit=True) as observer:
        while time.monotonic()<until:
            if future.done():return 'completed'
            if observer.execute("select exists(select 1 from pg_stat_activity where application_name=%s and wait_event_type='Lock')",(name,)).fetchone()[0]:return 'blocked'
            time.sleep(.01)
    raise AssertionError('Controlled database interleaving did not reach its barrier')


def test_reservation_cannot_escape_a_concurrent_project_deletion(approved):
    from concurrent.futures import ThreadPoolExecutor
    from psycopg import connect
    from psycopg.types.json import Jsonb
    sql=approved;dsn=sql.publication_dsn;data=info(project_id='project')
    sql(f"insert into public.user_memoir_project(user_id,project_id) values('{OWNER}','project');")
    sql("create function public.fixture_hold_reservation() returns trigger language plpgsql as $$begin perform pg_advisory_xact_lock(730400);return new;end$$; create trigger fixture_hold_reservation before insert on public.user_original_recording for each row execute function public.fixture_hold_reservation();")
    def reserve():
        with connect(dsn,application_name='issue73-reserve-race') as connection:
            return connection.execute('select public.recording_server_operation(%s,%s,null,%s)',(OWNER,'reserve',Jsonb(data))).fetchone()[0]
    def delete():
        with connect(dsn,application_name='issue73-delete-project-race') as connection:
            connection.execute('delete from public.user_memoir_project where user_id=%s and project_id=%s',(OWNER,'project'))
    blocker=connect(dsn,autocommit=True);blocker.execute('select pg_advisory_lock(730400)')
    try:
        with ThreadPoolExecutor(2) as pool:
            pending=pool.submit(reserve)
            try:
                assert wait_for_database_lock_or_completion(dsn,'issue73-reserve-race',pending)=='blocked'
                deletion=pool.submit(delete)
                wait_for_database_lock_or_completion(dsn,'issue73-delete-project-race',deletion)
            finally:blocker.execute('select pg_advisory_unlock(730400)')
            record=pending.result(10);deletion.result(10)
        state=json.loads(sql(f"select to_jsonb(r) from public.user_original_recording r where id='{record['id']}';").stdout.strip())
        assert state['lifecycle']=='deleted' and state['cleanup_status']=='pending'
    finally:
        blocker.close()
        sql('drop trigger fixture_hold_reservation on public.user_original_recording;drop function public.fixture_hold_reservation();')


def test_inflight_read_guard_orders_rollout_disablement_before_new_access(approved):
    from concurrent.futures import ThreadPoolExecutor
    from psycopg import connect
    from psycopg.types.json import Jsonb
    sql=approved;record=ready(sql);dsn=sql.publication_dsn
    guarded=connect(dsn)
    guarded.execute('select public.recording_server_operation(%s,%s,%s,%s)',(OWNER,'read',record['id'],Jsonb({})))
    def disable():
        with connect(dsn,application_name='issue73-disable-race') as connection:
            connection.execute('update public.original_recording_rollout set enabled=false')
    with ThreadPoolExecutor(1) as pool:
        pending=pool.submit(disable)
        try:
            observed=wait_for_database_lock_or_completion(dsn,'issue73-disable-race',pending)
        finally:guarded.close()
        pending.result(10)
    assert observed=='blocked', 'Disable committed while the publication/provider guard still held its read transaction'
    assert rpc(sql,'read_user_original_recording',literal(record['id'])) is None


@pytest.mark.parametrize('proof',['missing','stale'])
def test_cleanup_completion_requires_a_receipt_for_the_current_write_revision(approved,proof):
    sql=approved;record=ready(sql)
    writer=server(sql,'begin_upload',record['id'])
    before=server(sql,'delete',record['id'])
    after=server(sql,'finish_upload',record['id'],{'attempt_id':writer['upload_attempt_id']})
    data={} if proof=='missing' else {'write_revision':before.get('write_revision',0)}
    assert server(sql,'cleanup_complete',record['id'],data)['cleanup_status']=='pending'
    assert server(sql,'cleanup_complete',record['id'],{'write_revision':after['write_revision']})['cleanup_status']=='complete'
    replay=server(sql,'finish_upload',record['id'],{'attempt_id':writer['upload_attempt_id']})
    assert replay['write_revision']==after['write_revision'] and replay['cleanup_status']=='complete'


def test_accepted_recording_ids_keep_order_when_only_some_audio_is_readable(approved):
    sql=approved;first,second=ready(sql),ready(sql)
    accepted=accept(sql,[second['id'],first['id']]);server(sql,'delete',second['id'])
    restored=rpc(sql,'read_user_interview_turn',f"'project','{accepted['client_turn_id']}'")
    assert restored['recording_ids']==[second['id'],first['id']]
    assert [record['id'] for record in restored['recordings']]==[first['id']]
    assert rpc(sql,'read_user_interview_turn',f"'project','{accepted['client_turn_id']}'",owner=OTHER) is None
    assert restored['source']['text']==accepted['source']['text']
