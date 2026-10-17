"""Formal authority through public RPCs on a task-owned disposable PostgreSQL."""
import json
import asyncio
import select
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
import pytest
from uuid import uuid4

from test_lifetime_memory_postgres import sql, event_database, private_database, attachment_database, database, resolve
from test_shared_memory_events_postgres import rpc, literal
from test_agent_commit_postgres import OWNER, OTHER, as_user


def seed(sql, count=2, texts=None):
    identity = resolve(sql)
    project = identity['project_id']
    sources = []
    for text in (texts or ['I planted a garden.', 'I repaired a stool.'])[:count]:
        source = rpc(sql, 'accept_user_narrator_source', f"{literal(project)},'{uuid4()}',{literal(text)}")
        ref = dict(source_id=source['id'], version=1, quote=text, char_start=0, char_end=len(text))
        rpc(sql, 'apply_user_memory_events', f"{literal(project)},{literal([{'id':source['id'],'version':1}])},{literal([dict(kind='event',title='Memory',source_refs=[ref])])}")
        sources.append(source)
    phase = {'revision':0}  # Compatibility metadata; no user-selected mode.
    return project, sources, phase


def begin(sql, project, phase, request=None, revision=0, **kwargs):
    return rpc(sql, 'begin_formal_memoir', f"{literal(project)},{phase['revision']},{revision},'{request or uuid4()}'", **kwargs)


def service(sql, name, arguments, check=True):
    result = sql(f"set role service_role;select coalesce(to_jsonb(public.{name}({arguments})),'null'::jsonb);", check=check)
    return json.loads(result.stdout.splitlines()[-1]) if check else result


def staged(sql, claim, ordinal):
    page = service(sql, 'read_formal_memoir_chapter', f"'{claim['run_id']}','{claim['token']}',{ordinal}")
    chapter = dict(schema_version=1, chapter_id=page['chapter_id'], title=page['title'], blocks=[
        {**{k:v for k,v in ref.items() if k!='quote'},'text':ref['quote']} for ref in page['evidence']])
    validation = dict(schema_version=1,validator='formal-extractive-v1',chapter_plan_digest=page['chapter_plan_digest'],
        provenance='deterministic-extractive',blocking_count=0)
    result = service(sql, 'stage_formal_memoir_chapter',
        f"'{claim['run_id']}','{claim['token']}',{ordinal},{literal(chapter)},{literal(validation)}")
    return result, chapter, validation


def completed(sql, project, phase, revision=0):
    run = begin(sql,project,phase,revision=revision)
    claim = service(sql,'claim_formal_memoir',f"'{run['run_id']}'")
    for ordinal in range(1,run['chapter_count']+1): staged(sql,claim,ordinal)
    return service(sql,'complete_formal_memoir',f"'{run['run_id']}','{claim['token']}'")


def consent(sql, project, edition, revision, action='grant', **kwargs):
    return rpc(sql,'set_story_game_consent',f"{literal(project)},'{edition['edition_id']}',{literal(edition['manuscript_digest'])},{revision},'{action}'",**kwargs)


def test_authenticated_initiation_is_durable_idempotent_and_owner_scoped(sql):
    project, sources, phase = seed(sql)
    request = str(uuid4())
    started = begin(sql, project, phase, request)
    assert started['status'] == 'pending' and started['chapter_count'] == 2
    assert begin(sql, project, phase, request) == started
    status = rpc(sql, 'read_formal_memoir_status', literal(project))
    assert status['run']['run_id'] == started['run_id'] and status['edition'] is None
    assert begin(sql, project, phase, owner=OTHER, check=False).returncode != 0
    assert begin(sql, project, {'revision':phase['revision']-1}, check=False).returncode != 0


def test_full_commit_requires_every_planned_chapter_and_atomically_exposes_receipt(sql):
    project, sources, phase = seed(sql)
    run = begin(sql, project, phase)
    claim = service(sql, 'claim_formal_memoir', f"'{run['run_id']}'")
    assert claim['next_ordinal'] == 1
    first, chapter, validation = staged(sql, claim, 1)
    arguments = f"'{run['run_id']}','{claim['token']}'"
    assert service(sql, 'complete_formal_memoir', arguments, check=False).returncode != 0
    assert rpc(sql, 'read_formal_memoir_status', literal(project))['edition'] is None
    second, _, _ = staged(sql, claim, 2)
    saved = service(sql, 'complete_formal_memoir', arguments)
    assert saved['status'] == 'completed' and saved['revision'] == 1
    receipt = saved['receipt']
    assert receipt['pending_count'] == 0 and receipt['blocking_count'] == 0
    assert [x['digest'] for x in receipt['chapter_coverage']] == [first['digest'], second['digest']]
    assert receipt['plan_digest'] == run['plan_digest'] and receipt['run_id'] == run['run_id']
    assert service(sql, 'complete_formal_memoir', arguments) == saved
    status = rpc(sql, 'read_formal_memoir_status', literal(project))
    assert status['edition'] == saved
    read = service(sql, 'read_formal_memoir_edition_chapter', f"{literal(project)},'{saved['edition_id']}',1")
    assert read['chapter'] == chapter


def test_bounded_python_worker_resumes_and_replays_the_real_persisted_edition(sql):
    from apps.api.formal_memoir import advance_formal_memoir
    project, sources, phase = seed(sql)
    run = begin(sql, project, phase)
    class Broker:
        async def rpc(self, name, **parameters):
            return service(sql, name, ','.join(key+' => '+(str(value) if type(value) is int else literal(value))
                for key,value in parameters.items()))
    first = asyncio.run(advance_formal_memoir(Broker(),run['run_id'],quantum=1))
    assert first == dict(status='pending',run_id=run['run_id'],next_ordinal=2)
    saved = asyncio.run(advance_formal_memoir(Broker(),run['run_id'],quantum=1))
    assert saved['status'] == 'completed'
    assert asyncio.run(advance_formal_memoir(Broker(),run['run_id'],quantum=1)) == saved
    assert saved['receipt']['assembly'] == 'extractive-v1' and saved['receipt']['publication_approved'] is False


def test_exact_edition_consent_requires_owner_cas_and_can_be_revoked_outside_shape(sql):
    project, sources, phase = seed(sql)
    edition = completed(sql,project,phase)
    initial = rpc(sql,'read_story_game_eligibility',literal(project))
    assert initial['authority_eligible'] is False and initial['available'] is False
    grant = consent(sql,project,edition,initial['consent_revision'])
    assert grant['status'] == 'active'
    eligible = rpc(sql,'read_story_game_eligibility',literal(project))
    assert eligible['authority_eligible'] is True and eligible['available'] is False
    assert eligible['reasons'] == ['runtime_unavailable']
    assert consent(sql,project,edition,initial['consent_revision'],check=False).returncode != 0
    assert consent(sql,project,edition,grant['revision'],owner=OTHER,check=False).returncode != 0
    revoked = consent(sql,project,edition,grant['revision'],'revoke')
    assert revoked['status'] == 'revoked'
    denied = rpc(sql,'read_story_game_eligibility',literal(project))
    assert denied['authority_eligible'] is False


def test_source_correction_invalidates_completed_authority_and_purges_access(sql):
    project, sources, phase = seed(sql)
    edition = completed(sql,project,phase)
    initial = rpc(sql,'read_story_game_eligibility',literal(project))
    grant = consent(sql,project,edition,initial['consent_revision'])
    rpc(sql,'change_user_narrator_source',f"{literal(project)},'{sources[0]['id']}',1,'edit','I planted a different garden.'")
    status = rpc(sql,'read_formal_memoir_status',literal(project))
    assert status['run']['status'] == 'stale' and status['edition'] is None
    assert service(sql,'read_formal_memoir_edition_chapter',f"{literal(project)},'{edition['edition_id']}',1",check=False).returncode != 0
    assert service(sql,'claim_formal_memoir',f"'{edition['receipt']['run_id']}'",check=False).returncode != 0
    assert rpc(sql,'read_story_game_eligibility',literal(project))['authority_eligible'] is False
    assert consent(sql,project,edition,grant['revision'],check=False).returncode != 0


@pytest.mark.parametrize('change',['withdraw','edit','new_source','privacy'])
def test_inflight_authority_change_fences_read_stage_complete_and_allows_safe_status(sql,change):
    project,sources,phase=seed(sql)
    run=begin(sql,project,phase)
    claim=service(sql,'claim_formal_memoir',f"'{run['run_id']}'")
    _,chapter,validation=staged(sql,claim,1)
    if change in ('withdraw','edit'):
        replacement=literal('I corrected the garden memory.') if change=='edit' else 'null'
        rpc(sql,'change_user_narrator_source',f"{literal(project)},'{sources[0]['id']}',1,'{change}',{replacement}")
    elif change=='new_source':
        rpc(sql,'accept_user_narrator_source',f"{literal(project)},'{uuid4()}','I added a new memory.'")
    else:
        sql(as_user("update public.user_profile set profile=profile||'{\"memory_preferences\":{\"excluded_topics\":[\"garden\"]}}'::jsonb;"))
    args=f"'{run['run_id']}','{claim['token']}'"
    assert service(sql,'read_formal_memoir_chapter',args+',1',check=False).returncode!=0
    assert service(sql,'stage_formal_memoir_chapter',args+f",1,{literal(chapter)},{literal(validation)}",check=False).returncode!=0
    assert service(sql,'complete_formal_memoir',args,check=False).returncode!=0
    status=rpc(sql,'read_formal_memoir_status',literal(project))
    assert status['run']['status']=='stale' and status['edition'] is None


def test_concurrent_claims_issue_one_lease_and_released_worker_cannot_commit(sql):
    project,sources,phase=seed(sql)
    run=begin(sql,project,phase)
    with ThreadPoolExecutor(max_workers=2) as pool:
        claims=list(pool.map(lambda _:service(sql,'claim_formal_memoir',f"'{run['run_id']}'"),range(2)))
    assert sorted(claim['status'] for claim in claims)==['busy','running']
    first=next(claim for claim in claims if claim['status']=='running')
    staged(sql,first,1)
    service(sql,'release_formal_memoir',f"'{run['run_id']}','{first['token']}'")
    second=service(sql,'claim_formal_memoir',f"'{run['run_id']}'")
    assert second['next_ordinal']==2 and second['fence']>first['fence'] and second['token']!=first['token']
    staged(sql,second,2)
    assert service(sql,'complete_formal_memoir',f"'{run['run_id']}','{first['token']}'",check=False).returncode!=0
    assert service(sql,'complete_formal_memoir',f"'{run['run_id']}','{second['token']}'")['revision']==1


def test_transaction_rollback_exposes_neither_edition_nor_completion_receipt(sql):
    project,sources,phase=seed(sql)
    run=begin(sql,project,phase)
    claim=service(sql,'claim_formal_memoir',f"'{run['run_id']}'")
    for ordinal in (1,2): staged(sql,claim,ordinal)
    args=f"'{run['run_id']}','{claim['token']}'"
    sql(f"begin;set local role service_role;select public.complete_formal_memoir({args});rollback;")
    status=rpc(sql,'read_formal_memoir_status',literal(project))
    assert status['edition'] is None and status['run']['status']=='running'
    assert rpc(sql,'read_story_game_eligibility',literal(project))['authority_eligible'] is False
    saved=service(sql,'complete_formal_memoir',args)
    assert saved['revision']==1 and saved['receipt']['manuscript_kind']=='formal_memoir'


@pytest.mark.parametrize('mutation',['invented_text','missing_block','source_version','extra_field','validation_digest','validation_null','chapter_null'])
def test_worker_cannot_stage_fabricated_text_incomplete_evidence_or_forged_validation(sql,mutation):
    project,sources,phase=seed(sql)
    run=begin(sql,project,phase)
    claim=service(sql,'claim_formal_memoir',f"'{run['run_id']}'")
    page=service(sql,'read_formal_memoir_chapter',f"'{run['run_id']}','{claim['token']}',1")
    chapter=dict(schema_version=1,chapter_id=page['chapter_id'],title=page['title'],blocks=[
        {**{k:v for k,v in ref.items() if k!='quote'},'text':ref['quote']} for ref in page['evidence']])
    validation=dict(schema_version=1,validator='formal-extractive-v1',chapter_plan_digest=page['chapter_plan_digest'],
        provenance='deterministic-extractive',blocking_count=0)
    if mutation=='invented_text':chapter['blocks'][0]['text']='I became mayor.'
    elif mutation=='missing_block':chapter['blocks']=[]
    elif mutation=='source_version':chapter['blocks'][0]['version']=99
    elif mutation=='extra_field':chapter['publication_approved']=True
    elif mutation=='validation_digest':validation['chapter_plan_digest']='0'*64
    elif mutation=='validation_null':validation=None
    elif mutation=='chapter_null':chapter=None
    args=f"'{run['run_id']}','{claim['token']}',1,{literal(chapter)},{literal(validation)}"
    assert service(sql,'stage_formal_memoir_chapter',args,check=False).returncode!=0
    assert service(sql,'complete_formal_memoir',f"'{run['run_id']}','{claim['token']}'",check=False).returncode!=0
    staged(sql,claim,1)
    staged(sql,claim,2)
    assert service(sql,'complete_formal_memoir',f"'{run['run_id']}','{claim['token']}'")['status']=='completed'


def test_replacing_formal_edition_requires_new_consent_and_rejects_old_completion_replay(sql):
    project,sources,phase=seed(sql)
    first=completed(sql,project,phase)
    state=rpc(sql,'read_story_game_eligibility',literal(project))
    consent(sql,project,first,state['consent_revision'])
    second=completed(sql,project,phase,revision=1)
    assert second['revision']==2 and second['edition_id']!=first['edition_id']
    state=rpc(sql,'read_story_game_eligibility',literal(project))
    assert state['authority_eligible'] is False
    assert consent(sql,project,first,state['consent_revision'],check=False).returncode!=0
    assert service(sql,'claim_formal_memoir',f"'{first['receipt']['run_id']}'",check=False).returncode!=0
    consent(sql,project,second,state['consent_revision'])
    assert rpc(sql,'read_story_game_eligibility',literal(project))['authority_eligible'] is True


def test_competing_authenticated_begin_requests_cannot_create_two_active_runs(sql):
    project,sources,phase=seed(sql)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(lambda _:begin(sql,project,phase,check=False),range(2)))
    assert sum(result.returncode==0 for result in results)==1
    winner=json.loads(next(result for result in results if result.returncode==0).stdout.splitlines()[-1])
    assert rpc(sql,'read_formal_memoir_status',literal(project))['run']['run_id']==winner['run_id']


def test_competing_consent_writes_require_the_current_revision(sql):
    project,sources,phase=seed(sql)
    edition=completed(sql,project,phase)
    state=rpc(sql,'read_story_game_eligibility',literal(project))
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(lambda _:consent(sql,project,edition,state['consent_revision'],check=False),range(2)))
    assert sum(result.returncode==0 for result in results)==1
    current=rpc(sql,'read_story_game_eligibility',literal(project))
    assert current['authority_eligible'] is True and current['consent_revision']==state['consent_revision']+1


def test_browser_roles_cannot_write_receipts_or_call_worker_or_prose_interfaces(sql):
    project,sources,phase=seed(sql)
    run=begin(sql,project,phase)
    assert rpc(sql,'claim_formal_memoir',f"'{run['run_id']}'",check=False).returncode!=0
    claim=service(sql,'claim_formal_memoir',f"'{run['run_id']}'")
    _,chapter,validation=staged(sql,claim,1)
    args=f"'{run['run_id']}','{claim['token']}'"
    for name,tail in [('read_formal_memoir_chapter',',1'),('stage_formal_memoir_chapter',f",1,{literal(chapter)},{literal(validation)}"),
                      ('complete_formal_memoir',''),('release_formal_memoir','')]:
        assert rpc(sql,name,args+tail,check=False).returncode!=0
    for table in ('user_formal_memoir_run','user_formal_memoir_plan','user_formal_memoir_chapter','user_formal_memoir_edition','user_story_game_consent'):
        assert sql(as_user(f'select * from public.{table};'),check=False).returncode!=0
        assert sql(f'set role service_role;delete from public.{table};',check=False).returncode!=0
    staged(sql,claim,2)
    edition=service(sql,'complete_formal_memoir',args)
    assert rpc(sql,'read_formal_memoir_edition_chapter',f"{literal(project)},'{edition['edition_id']}',1",check=False).returncode!=0
    assert rpc(sql,'read_formal_memoir_status',literal(project),owner=OTHER,check=False).returncode!=0
    assert rpc(sql,'read_story_game_eligibility',literal(project),owner=OTHER,check=False).returncode!=0


def test_source_correction_racing_final_commit_cannot_leave_a_current_edition(sql):
    project,sources,phase=seed(sql)
    run=begin(sql,project,phase)
    claim=service(sql,'claim_formal_memoir',f"'{run['run_id']}'")
    for ordinal in (1,2): staged(sql,claim,ordinal)
    with ThreadPoolExecutor(max_workers=2) as pool:
        completion=pool.submit(service,sql,'complete_formal_memoir',f"'{run['run_id']}','{claim['token']}'",False)
        correction=pool.submit(rpc,sql,'change_user_narrator_source',
            f"{literal(project)},'{sources[0]['id']}',1,'withdraw',null")
        correction.result()
        completion.result()  # Either serialize before withdrawal or reject stale.
    status=rpc(sql,'read_formal_memoir_status',literal(project))
    assert status['edition'] is None and status['run']['status']=='stale'
    assert rpc(sql,'read_story_game_eligibility',literal(project))['authority_eligible'] is False


@pytest.mark.parametrize('case',['null_ambiguous','missing_ambiguous','oversized_end'])
def test_inexact_legacy_evidence_blocks_without_leaving_a_partial_formal_run(sql,case):
    project=resolve(sql)['project_id']
    text='a'*2000 if case=='oversized_end' else 'I garden. I garden.'
    source=rpc(sql,'accept_user_narrator_source',f"{literal(project)},'{uuid4()}',{literal(text)}")
    ref=dict(source_id=source['id'],version=1,quote=text if case=='oversized_end' else 'I garden.')
    if case=='oversized_end':ref.update(char_start=0,char_end=2001)
    elif case=='null_ambiguous':ref.update(char_start=None,char_end=None)
    rpc(sql,'apply_user_memory_events',f"{literal(project)},{literal([{'id':source['id'],'version':1}])},{literal([dict(kind='event',title='Memory',source_refs=[ref])])}")
    phase={'revision':0}
    result=begin(sql,project,phase,check=False)
    assert result.returncode!=0 and 'FORMAL_EXACT_EVIDENCE_REQUIRED' in result.stderr
    assert rpc(sql,'read_formal_memoir_status',literal(project))=={'schema_version':1,'run':None,'edition':None}


def test_expired_worker_lease_rejects_read_and_commit_and_can_be_reclaimed(sql):
    project,sources,phase=seed(sql)
    run=begin(sql,project,phase)
    first=service(sql,'claim_formal_memoir',f"'{run['run_id']}',1")
    time.sleep(1.1)
    args=f"'{run['run_id']}','{first['token']}'"
    assert service(sql,'read_formal_memoir_chapter',args+',1',check=False).returncode!=0
    assert service(sql,'complete_formal_memoir',args,check=False).returncode!=0
    second=service(sql,'claim_formal_memoir',f"'{run['run_id']}'")
    assert second['token']!=first['token'] and second['fence']>first['fence'] and second['next_ordinal']==1
    for ordinal in (1,2):staged(sql,second,ordinal)
    assert service(sql,'complete_formal_memoir',f"'{run['run_id']}','{second['token']}'")['status']=='completed'


def test_revoking_old_edition_advances_project_fence_and_requires_fresh_current_consent(sql):
    project,sources,phase=seed(sql)
    first=completed(sql,project,phase)
    second=completed(sql,project,phase,revision=1)
    state=rpc(sql,'read_story_game_eligibility',literal(project))
    consent(sql,project,second,state['consent_revision'])
    state=rpc(sql,'read_story_game_eligibility',literal(project))
    assert state['authority_eligible'] is True
    consent(sql,project,first,state['consent_revision'],action='revoke')
    state=rpc(sql,'read_story_game_eligibility',literal(project))
    assert state['authority_eligible'] is False
    consent(sql,project,second,state['consent_revision'])
    assert rpc(sql,'read_story_game_eligibility',literal(project))['authority_eligible'] is True


@pytest.mark.parametrize('reader',['eligibility','private_publication'])
def test_profile_update_and_project_reader_do_not_deadlock_without_a_formal_run(sql,reader):
    project,_,_=seed(sql)
    assert rpc(sql,'read_formal_memoir_status',literal(project))['run'] is None
    old=rpc(sql,'capture_lifetime_read_fence',literal(project))
    held=subprocess.Popen(sql.command,env=sql.env,stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
    waiter='formal_preferences_'+uuid4().hex
    try:
        held.stdin.write("\\set VERBOSITY verbose\nset statement_timeout='8s'; set deadlock_timeout='100ms';\n"+
            'begin;\n\\o /dev/null\n'+
                f"select 1 from public.user_memoir_project where user_id='{OWNER}' and project_id={literal(project)} for update;\n"+
                '\\o\nselect pg_backend_pid();\n')
        held.stdin.flush()
        assert select.select([held.stdout],[],[],5)[0], 'reader did not acquire project'
        reader_pid=int(held.stdout.readline())
        with ThreadPoolExecutor(max_workers=1) as pool:
            changed=pool.submit(sql,"\\set VERBOSITY verbose\n"+
                f"set application_name='{waiter}'; set statement_timeout='8s'; set deadlock_timeout='100ms'; "+
                as_user("update public.user_profile set profile=profile||'{\"preferred_language\":\"zh-CN\"}'::jsonb;"),
                check=False)
            # Before the fix, B holds profile/identity and is blocked by A's
            # project lock. After the fix, B can finish without waiting for A.
            until=time.monotonic()+5
            while not changed.done():
                blocked=sql(f"select exists(select 1 from pg_stat_activity where application_name='{waiter}' "
                    f"and {reader_pid}=any(pg_blocking_pids(pid)));").stdout.strip()
                if blocked=='t':break
                assert time.monotonic()<until, 'profile update neither completed nor reached reader'
                time.sleep(.02)
            query=(f'select public.read_story_game_eligibility({literal(project)});' if reader=='eligibility'
                else f'select public.lock_lifetime_read_publication({literal(old)}::jsonb);')
            held.stdin.write(as_user(query)+'\ncommit;\n\\q\n')
            held.stdin.flush()
            output,errors=held.communicate(timeout=10)
            update=changed.result(timeout=10)
        assert update.returncode==0, update.stderr
        assert '40P01' not in errors, errors
        if reader=='eligibility':
            assert held.returncode==0, errors
            assert json.loads(output)['available'] is False
        else:
            assert held.returncode!=0 and 'PT409' in errors and 'stale lifetime read fence' in errors, errors
        assert rpc(sql,'capture_lifetime_read_fence',literal(project))['preference_revision']>old['preference_revision']
    finally:
        if held.poll() is None:
            held.kill()
            held.communicate(timeout=5)


@pytest.mark.parametrize('state',['staged','completed'])
def test_formal_read_waits_before_formal_rows_and_profile_purge_is_atomic(sql,state):
    project,_,phase=seed(sql)
    run=begin(sql,project,phase)
    claim=service(sql,'claim_formal_memoir',f"'{run['run_id']}'")
    _,chapter,validation=staged(sql,claim,1)
    args=f"'{run['run_id']}','{claim['token']}'"
    if state=='completed':
        staged(sql,claim,2)
        edition=service(sql,'complete_formal_memoir',args)
    held=subprocess.Popen(sql.command,env=sql.env,stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
    waiter='formal_phase_'+uuid4().hex
    try:
        held.stdin.write("\\set VERBOSITY verbose\nset statement_timeout='8s'; set deadlock_timeout='100ms';\n"+
            as_user("begin;\n\\o /dev/null\nselect 1 from public.user_profile where user_id=auth.uid() for update;\n"+
                '\\o\nselect pg_backend_pid();\n'))
        held.stdin.flush()
        assert select.select([held.stdout],[],[],5)[0], 'profile row was not locked'
        profile_pid=int(held.stdout.readline())
        with ThreadPoolExecutor(max_workers=1) as pool:
            phase_change=pool.submit(sql,"\\set VERBOSITY verbose\n"+
                f"set application_name='{waiter}'; set statement_timeout='8s'; set deadlock_timeout='100ms'; "+
                as_user(f"begin; select public.read_story_game_eligibility({literal(project)}); commit;"),
                check=False)
            until=time.monotonic()+5
            while True:
                blocked=sql(f"select exists(select 1 from pg_stat_activity where application_name='{waiter}' "
                    f"and {profile_pid}=any(pg_blocking_pids(pid)));").stdout.strip()
                if blocked=='t':break
                assert not phase_change.done(), 'phase change escaped the locked preference authority'
                assert time.monotonic()<until, 'phase change did not reach preference authority'
                time.sleep(.02)
            # A project writer must not own formal rows while waiting for this
            # profile transaction, whose trigger must purge those same rows.
            held.stdin.write("update public.user_profile set profile=profile||'{\"preferred_language\":\"zh-CN\"}'::jsonb;\n"+
                'commit;\n\\q\n')
            held.stdin.flush()
            _,errors=held.communicate(timeout=10)
            changed=phase_change.result(timeout=10)
        assert held.returncode==0,errors
        assert changed.returncode==0,changed.stderr
        status=rpc(sql,'read_formal_memoir_status',literal(project))
        assert status['run']['status']=='stale' and status['edition'] is None
        for name,tail in [('read_formal_memoir_chapter',',1'),
                ('stage_formal_memoir_chapter',f',1,{literal(chapter)},{literal(validation)}'),('complete_formal_memoir','')]:
            assert service(sql,name,args+tail,check=False).returncode!=0
        if state=='completed':
            assert service(sql,'read_formal_memoir_edition_chapter',f"{literal(project)},'{edition['edition_id']}',1",check=False).returncode!=0
        # Purging bytes, lease removal and metadata invalidation must commit
        # together; rejecting future reads alone is not sufficient.
        purged=json.loads(sql(f"select jsonb_build_object('chapters',(select count(*) from public.user_formal_memoir_chapter where run_id='{run['run_id']}'),"+
            f"'evidence',(select bool_and(evidence='[]'::jsonb) from public.user_formal_memoir_plan where run_id='{run['run_id']}'),"+
            f"'lease',(select token is null and lease_until is null from public.user_formal_memoir_run where id='{run['run_id']}'));").stdout)
        assert purged==dict(chapters=0,evidence=True,lease=True)
    finally:
        if held.poll() is None:
            held.kill()
            held.communicate(timeout=5)


@pytest.mark.parametrize('finish',['commit','rollback'])
def test_status_and_content_follow_the_atomic_preference_transaction(sql,finish):
    project,_,phase=seed(sql)
    edition=completed(sql,project,phase)
    held=subprocess.Popen(sql.command,env=sql.env,stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
    waiter='formal_status_'+uuid4().hex
    try:
        held.stdin.write("set statement_timeout='8s';\n"+as_user('begin;\n'+
            "update public.user_profile set profile=profile||'{\"preferred_language\":\"zh-CN\"}'::jsonb;\n"+
            'select pg_backend_pid();\n'))
        held.stdin.flush()
        assert select.select([held.stdout],[],[],5)[0], 'preference change did not finish staging'
        profile_pid=int(held.stdout.readline())
        with ThreadPoolExecutor(max_workers=1) as pool:
            read=pool.submit(sql,f"set application_name='{waiter}'; set statement_timeout='8s'; "+
                as_user(f'select public.read_formal_memoir_status({literal(project)});'),check=False)
            try:
                until=time.monotonic()+5
                while True:
                    blocked=sql(f"select exists(select 1 from pg_stat_activity where application_name='{waiter}' "
                        f"and {profile_pid}=any(pg_blocking_pids(pid)));").stdout.strip()
                    if blocked=='t':break
                    assert not read.done(), 'status bypassed the in-flight preference transaction'
                    assert time.monotonic()<until, 'status did not reach preference authority'
                    time.sleep(.02)
            finally:
                held.stdin.write(finish+';\n\\q\n')
                held.stdin.flush()
                _,errors=held.communicate(timeout=10)
            result=read.result(timeout=10)
        assert held.returncode==0,errors
        assert result.returncode==0,result.stderr
        status=json.loads(result.stdout)
        content=service(sql,'read_formal_memoir_edition_chapter',f"{literal(project)},'{edition['edition_id']}',1",check=False)
        if finish=='commit':
            assert status['run']['status']=='stale' and status['edition'] is None
            assert content.returncode!=0
            assert sql('select count(*) from public.user_formal_memoir_chapter;').stdout.strip()=='0'
        else:
            assert status['run']['status']=='completed' and status['edition']==edition
            assert content.returncode==0
            assert json.loads(content.stdout)['chapter']['blocks'][0]['text']=='I planted a garden.'
    finally:
        if held.poll() is None:
            held.kill()
            held.communicate(timeout=5)
