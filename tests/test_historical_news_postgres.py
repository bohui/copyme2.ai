"""Atomic locale provenance on real, disposable PostgreSQL (never Supabase).

Run with initdb, pg_ctl and psql on PATH. The fixture owns a fresh /tmp cluster,
listens only on loopback, uses no live credentials and always stops its server.
No single-user fallback: these tests must exercise real RLS and row contention.
"""
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import select
import shutil
import socket
import subprocess
import tempfile
import time
from uuid import uuid4

import pytest


ROOT = Path(__file__).resolve().parents[1]
OWNER = '11111111-1111-4111-8111-111111111111'
OTHER = '22222222-2222-4222-8222-222222222222'
GUEST = '33333333-3333-4333-8333-333333333333'


def literal(value):
    return 'null' if value is None else "'" + str(value).replace("'", "''") + "'"


def as_user(query, owner=OWNER, role='authenticated'):
    assert role in ('authenticated', 'anon')
    return (f"set role {role}; set request.jwt.claim.sub={literal(owner or '')}; "
            + query)


@pytest.fixture(scope='module')
def database():
    tools = {name: shutil.which(name) for name in ('initdb', 'pg_ctl', 'psql')}
    if os.geteuid() == 0 or not all(tools.values()):
        pytest.skip('real locale concurrency tests require local PostgreSQL tools and a non-root user')
    # Ignore inherited connection targets and settings; this fixture can never
    # redirect itself to a developer or remote database through PG* variables.
    env = {key: value for key, value in os.environ.items() if not key.startswith('PG')}
    with tempfile.TemporaryDirectory(prefix='memoir-news-', dir='/tmp') as directory:
        data = str(Path(directory) / 'data')
        log = str(Path(directory) / 'postgres.log')
        with socket.socket() as listener:
            listener.bind(('127.0.0.1', 0))
            port = listener.getsockname()[1]
        subprocess.run([tools['initdb'], '-D', data, '-U', 'locale_fixture', '-A', 'trust',
                        '--no-locale', '--encoding=UTF8'], env=env, check=True,
                       capture_output=True, text=True, timeout=30)
        command = [tools['psql'], '-X', '-qAt', '-v', 'ON_ERROR_STOP=1', '-h', '127.0.0.1',
                   '-p', str(port), '-U', 'locale_fixture', '-d', 'postgres']

        def sql(query, *, check=True):
            result = subprocess.run(command, input="set statement_timeout='12s';\n" + query,
                                    env=env, capture_output=True, text=True, timeout=15)
            if check:
                assert result.returncode == 0, result.stderr
            return result

        sql.command = command
        sql.env = env
        started = False
        try:
            start = subprocess.run([tools['pg_ctl'], '-D', data, '-l', log, '-t', '10', '-w',
                '-o', f"-h 127.0.0.1 -p {port} -k '' -c shared_buffers=16MB -c max_connections=12 "
                      '-c work_mem=1MB -c maintenance_work_mem=16MB -c max_wal_size=64MB '
                      '-c max_parallel_workers=0 -c jit=off', 'start'],
                env=env, capture_output=True, text=True, timeout=15)
            assert start.returncode == 0, start.stderr + Path(log).read_text()
            started = True
            sql("""create role anon; create role authenticated; create schema auth;
                create table auth.users(id uuid primary key);
                create function auth.uid() returns uuid language sql stable as
                $$select nullif(current_setting('request.jwt.claim.sub',true),'')::uuid$$;
                grant usage on schema auth to authenticated;
                create schema storage;
                create table storage.buckets(id text primary key,name text,public boolean,file_size_limit bigint);
                create table storage.objects(bucket_id text,name text);
                create function storage.foldername(text) returns text[] language sql as $$select string_to_array($1,'/')$$;
                create function storage.allow_any_operation(text[]) returns boolean language sql as $$select true$$;
            """)
            root=ROOT/'supabase/legacy-migrations'
            for name in ('202609230001_user_agent_storage.sql','202609230002_agent_sessions.sql',
                         '202609250002_agent_turn_leases.sql','202609250004_fenced_agent_turn_commit.sql'):
                sql((root/name).read_text())
            sql(f"insert into auth.users values ('{OWNER}'),('{OTHER}');")
            yield sql
        finally:
            if started or (Path(data) / 'postmaster.pid').exists():
                stop = subprocess.run([tools['pg_ctl'], '-D', data, '-m', 'immediate',
                                       '-t', '10', '-w', 'stop'], env=env,
                                      capture_output=True, text=True, timeout=15)
                assert stop.returncode == 0, stop.stderr

from test_guest_conversation_transfer import attachment_database
from test_private_rounds_postgres import private_database
from test_shared_memory_events_postgres import event_database, sql, rpc, literal, TURN
from test_interview_photos_postgres import accept
from test_interview_work_plan_postgres import save, plan
from test_historical_news import ready_context
from uuid import uuid4


def begin(sql):
    accept(sql, 'I was born in Boston in 1960.')
    h=ready_context()['historical_news']['clues'][0]['relevance']
    snapshot=rpc(sql,'read_user_historical_news_basis',"'project'")['news_snapshot']
    return rpc(sql,'begin_user_historical_news',f"'project',{literal(h)}::jsonb,{literal(snapshot)}::jsonb")


def finish(sql,job):
    clue=ready_context()['historical_news']['clues'][0]
    return rpc(sql,'finish_user_historical_news',f"'project','{job['id']}',{literal({'status':'ready','clues':[clue]})}::jsonb")


def test_fenced_job_dedup_and_ready_projection(sql):
    job=begin(sql)
    assert job and finish(sql,job) is True
    state=rpc(sql,'read_user_historical_news',"'project'")
    assert len(state['clues'])==1
    assert state['clues'][0]['context_revision']==state['context_revision']
    assert rpc(sql,'read_user_memory_events',"'project'")['events']==[]
    assert begin(sql) is None


def test_native_rls_cross_project_and_direct_write_denial(sql):
    job=begin(sql);finish(sql,job)
    for table in ('state','job','clue'):
        assert sql(as_user(f'select count(*) from public.user_historical_news_{table};',OTHER)).stdout.splitlines()[-1]=='0'
    assert rpc(sql,'read_user_historical_news',"'project'",owner=OTHER)['clues']==[]
    assert rpc(sql,'finish_user_historical_news',f"'project','{job['id']}','{{}}'",owner=OTHER) is False
    assert sql(as_user("delete from public.user_historical_news_clue;"),check=False).returncode!=0


def test_preference_fences_inflight_and_rejection_survives_reenable(sql):
    job=begin(sql)
    rpc(sql,'set_user_historical_news',"'project',false")
    assert finish(sql,job) is False
    rpc(sql,'set_user_historical_news',"'project',true")
    job=begin(sql);assert finish(sql,job)
    clue=ready_context()['historical_news']['clues'][0]
    rpc(sql,'set_user_historical_news',f"'project',true,'{clue['id']}'")
    job=begin(sql);assert finish(sql,job)
    assert rpc(sql,'read_user_historical_news',"'project'")['clues']==[]


def test_next_source_and_project_deletion_fence_work(sql):
    job=begin(sql)
    accept(sql,'A new memory.',turn=str(uuid4()))
    assert finish(sql,job) is False
    hypothesis=ready_context()['historical_news']['clues'][0]['relevance']
    snapshot=rpc(sql,'read_user_historical_news_basis',"'project'")['news_snapshot']
    replacement=rpc(sql,'begin_user_historical_news',f"'project',{literal(hypothesis)}::jsonb,{literal(snapshot)}::jsonb")
    assert replacement and replacement['id'] != job['id']
    assert finish(sql,replacement) is True
    sql('delete from public.user_memoir_project;')
    assert sql('select count(*) from public.user_historical_news_job;').stdout.strip()=='0'


def test_source_only_changes_hide_ready_clues_until_current_basis_is_revalidated(sql):
    job=begin(sql);assert finish(sql,job)
    before=rpc(sql,'read_user_historical_news',"'project'")
    accept(sql,'I moved to Sydney, Australia in 1965.',turn=str(uuid4()))
    state=rpc(sql,'read_user_historical_news',"'project'")
    assert state['context_revision'] != before['context_revision']
    assert state['clues'] == []


@pytest.mark.parametrize('change', ['same_basis', 'move', 'stale_snapshot', 'preference', 'other_owner'])
def test_ready_evidence_revalidation_requires_current_owned_unchanged_hypothesis(sql, change):
    job=begin(sql);assert finish(sql,job)
    old_snapshot=rpc(sql,'read_user_historical_news_basis',"'project'")['news_snapshot']
    accept(sql,'Another ordinary memory.',turn=str(uuid4()))
    hypothesis=ready_context()['historical_news']['clues'][0]['relevance']
    snapshot=rpc(sql,'read_user_historical_news_basis',"'project'")['news_snapshot']
    if change == 'move':
        hypothesis={**hypothesis,'place':'Sydney, Australia','country':'Australia'}
    elif change == 'stale_snapshot':
        snapshot=old_snapshot
    elif change == 'preference':
        rpc(sql,'set_user_historical_news',"'project',false")
        rpc(sql,'set_user_historical_news',"'project',true")
        snapshot=rpc(sql,'read_user_historical_news_basis',"'project'")['news_snapshot']
    state=rpc(sql,'revalidate_user_historical_news',f"'project',{literal(hypothesis)}::jsonb,{literal(snapshot)}::jsonb",
        owner=OTHER if change == 'other_owner' else OWNER)
    if change in {'stale_snapshot','other_owner'}:
        assert state is None
    elif change == 'same_basis':
        assert len(state['clues']) == 1
        assert state['clues'][0]['context_revision'] == snapshot['context_revision']
    else:
        assert state['clues'] == []


@pytest.mark.parametrize('same_basis', [False, True])
def test_legacy_ready_clue_upgrade_requires_revalidation_without_rediscovery(sql, same_basis):
    job=begin(sql);assert finish(sql,job)
    sql("update public.user_historical_news_clue set context_revision=regexp_replace(context_revision,':[^:]+$','');")
    sql((ROOT/'supabase/migrations/202610150002_historical_news_legacy_fences.sql').read_text())
    state=rpc(sql,'read_user_historical_news',"'project'")
    assert state['clues'] == [] and state['needs_revalidation'] is True
    hypothesis=ready_context()['historical_news']['clues'][0]['relevance']
    if not same_basis:
        hypothesis={**hypothesis,'place':'Sydney, Australia','country':'Australia'}
    snapshot=rpc(sql,'read_user_historical_news_basis',"'project'")['news_snapshot']
    state=rpc(sql,'revalidate_user_historical_news',f"'project',{literal(hypothesis)}::jsonb,{literal(snapshot)}::jsonb")
    assert bool(state['clues']) is same_basis
    assert sql('select count(*) from public.user_historical_news_job;').stdout.strip() == '1'


def test_durable_plan_rejects_forged_and_accepts_ready_reference(sql):
    job=begin(sql)
    p=plan('extract',None);c=p['candidates'][0]['context']
    c['historical_clue_id']='news-ffffffffffffffffffffffff'
    assert save(sql,p,check=False).returncode!=0
    assert finish(sql,job)
    c['historical_clue_id']=ready_context()['historical_news']['clues'][0]['id']
    saved=save(sql,p)
    assert saved['plan']==p


def test_public_year_never_becomes_biographical_year(sql):
    job=begin(sql);finish(sql,job)
    p=plan('extract',None);p['candidates'][0]['context'].update(
        historical_clue_id=ready_context()['historical_news']['clues'][0]['id'],year=1970)
    assert save(sql,p,check=False).returncode!=0


def test_saved_citation_is_replayable_and_shown_clue_is_not_reselected(sql):
    job=begin(sql);finish(sql,job)
    p=plan('extract',None);p['candidates'][0]['context']['historical_clue_id']=ready_context()['historical_news']['clues'][0]['id']
    result=save(sql,p)
    replay=rpc(sql,'read_user_interview_turn',f"'project','{TURN}'")
    assert replay['historical_context']['source_url']=='https://archive.example/fair'
    assert replay['historical_context']==result['historical_context']
    assert 'receipt' not in replay['historical_context'] and 'relevance' not in replay['historical_context']
    assert rpc(sql,'read_user_historical_news',"'project'")['clues']==[]
    assert save(sql,p)['reply']==replay['reply']


def show_clue(sql):
    job=begin(sql);finish(sql,job)
    p=plan('extract',None);p['candidates'][0]['context']['historical_clue_id']=ready_context()['historical_news']['clues'][0]['id']
    save(sql,p)


def test_later_exact_testimony_retains_cue_assisted_provenance(sql):
    show_clue(sql)
    later=accept(sql,'I remember hearing about it, but I was not there.',turn=str(uuid4()))
    source=later['source']
    assert source['text']=='I remember hearing about it, but I was not there.'
    assert source['cue_context']['kind']=='historical_context_presented'
    assert source['cue_context']['clue_id']==ready_context()['historical_news']['clues'][0]['id']
    assert source['version']==1
    assert rpc(sql,'read_user_memory_events',"'project'")['events']==[]


def test_guest_transfer_carries_optout_and_retired_clues_and_fences_old_jobs(sql):
    from test_guest_conversation_transfer import prepare, attach
    sql(f"update auth.users set is_anonymous=true where id='{OWNER}';")
    job=begin(sql);finish(sql,job)
    clue=ready_context()['historical_news']['clues'][0]['id']
    rpc(sql,'set_user_historical_news',f"'project',false,'{clue}'")
    sql(f"insert into public.user_memory(user_id,kind,content) values ('{OWNER}','agent','Storyteller: Test\\nMemory Spark: Test');")
    sql(as_user(prepare().replace("project-guest","project")))
    sql(as_user(attach(),OTHER))
    state=rpc(sql,'read_user_historical_news',"'project'",owner=OTHER)
    assert state['enabled'] is False and state['clues']==[]
    assert sql(as_user("select count(*) from public.user_historical_news_clue where status='rejected';",OTHER)).stdout.splitlines()[-1]=='1'
    assert rpc(sql,'read_user_historical_news',"'project'")['clues']==[]
    assert finish(sql,job) is False


@pytest.mark.parametrize('text',["I don't remember.",'Skip this clue.','我想不起来了。','先暂停。',"Please stop historical clues.","I don't want to discuss sport."])
def test_narrator_controls_retire_context_before_next_selection(sql,text):
    show_clue(sql)
    accept(sql,text,turn=str(uuid4()))
    state=rpc(sql,'read_user_historical_news',"'project'")
    assert state['clues']==[]
    if 'stop' in text or "don't want" in text or '暂停' in text:assert state['enabled'] is False


def test_explicit_return_to_last_clue_can_reopen_it(sql):
    show_clue(sql)
    accept(sql,"Let's return to that historical clue.",turn=str(uuid4()))
    state=rpc(sql,'read_user_historical_news',"'project'")
    assert len(state['clues'])==1


@pytest.mark.parametrize('missing',['title','category','precision','event_start','event_end','place','retrieved_at','locator','receipt.urls','receipt.provider'])
def test_missing_evidence_fields_fail_closed_at_database(sql,missing):
    job=begin(sql);clue=ready_context()['historical_news']['clues'][0]
    if '.' in missing:clue['receipt'].pop(missing.split('.')[1])
    else:clue.pop(missing)
    result=rpc(sql,'finish_user_historical_news',f"'project','{job['id']}',{literal({'status':'ready','clues':[clue]})}::jsonb",check=False)
    assert result.returncode!=0
    assert rpc(sql,'read_user_historical_news',"'project'")['clues']==[]


def test_private_source_url_is_not_eligible_even_with_forged_receipt(sql):
    job=begin(sql);clue=ready_context()['historical_news']['clues'][0]
    clue['source_url']='http://127.0.0.1/private';clue['receipt']['urls']=[clue['source_url']]
    assert rpc(sql,'finish_user_historical_news',f"'project','{job['id']}',{literal({'status':'ready','clues':[clue]})}::jsonb",check=False).returncode!=0


def test_correction_between_basis_read_and_claim_fails_closed(sql):
    first=accept(sql,'I was born in Boston in 1960.')
    basis=rpc(sql,'read_user_historical_news_basis',"'project'")
    rpc(sql,'change_user_narrator_source',f"'project','{first['source']['id']}',1,'edit','I was born elsewhere.'")
    h=ready_context()['historical_news']['clues'][0]['relevance']
    assert rpc(sql,'begin_user_historical_news',f"'project',{literal(h)}::jsonb,{literal(basis['news_snapshot'])}::jsonb") is None


def test_skipping_old_clue_preserves_optout_and_ordinary_pool(sql):
    job=begin(sql);finish(sql,job)
    p=plan('extract',None)
    p['candidates'].append({'id':'news','question':'Any memory?','order':1,'context':{'historical_clue_id':ready_context()['historical_news']['clues'][0]['id']}})
    save(sql,p)
    rpc(sql,'set_user_historical_news',"'project',false")
    state=rpc(sql,'set_user_historical_news',f"'project',null,'{ready_context()['historical_news']['clues'][0]['id']}'")
    assert state['enabled'] is False
    kept=rpc(sql,'read_user_interview_context',"'project'")['plan']
    assert kept['candidates']==p['candidates'][:1] and kept['chosen_id']==p['chosen_id']


def test_corrected_cue_answer_preserves_prompt_attribution(sql):
    show_clue(sql)
    answer=accept(sql,'I heard it on the radio.',turn=str(uuid4()))['source']
    updated=rpc(sql,'change_user_narrator_source',f"'project','{answer['id']}',1,'edit','Actually I only read about it.'")
    view=rpc(sql,'read_user_memory_events',"'project'")
    source=next(s for s in view['sources'] if s['id']==answer['id'])
    assert source['version']==2 and source['cue_context']==answer['cue_context']
    assert source['text']=='Actually I only read about it.'


def test_past_tense_pause_is_narration_not_an_optout(sql):
    show_clue(sql)
    accept(sql,'We paused by the park and watched the fair.',turn=str(uuid4()))
    assert rpc(sql,'read_user_historical_news',"'project'")['enabled'] is True


def test_pruning_chosen_news_selects_an_existing_ordinary_candidate(sql):
    job=begin(sql);finish(sql,job)
    p=plan('extract',None)
    p['candidates'].append({'id':'news','question':'Any memory?','order':1,'context':{'historical_clue_id':ready_context()['historical_news']['clues'][0]['id']}})
    p['chosen_id']='news';save(sql,p)
    rpc(sql,'set_user_historical_news',"'project',false")
    kept=rpc(sql,'read_user_interview_context',"'project'")['plan']
    assert len(kept['candidates'])==1 and kept['chosen_id']==kept['candidates'][0]['id']


@pytest.mark.parametrize('hypothesis',[{}, {'start':1970,'end':1971}, {'start':'1970','end':1971,'place':'Boston, USA','country':'USA','tentative':False}])
def test_malformed_hypothesis_does_not_obtain_a_claim(sql,hypothesis):
    accept(sql,'A memory.')
    snapshot=rpc(sql,'read_user_historical_news_basis',"'project'")['news_snapshot']
    assert rpc(sql,'begin_user_historical_news',f"'project',{literal(hypothesis)}::jsonb,{literal(snapshot)}::jsonb",check=False).returncode!=0


def test_concurrent_claims_have_one_owner(sql):
    from concurrent.futures import ThreadPoolExecutor
    accept(sql,'A memory.')
    basis=rpc(sql,'read_user_historical_news_basis',"'project'")['news_snapshot']
    h=ready_context()['historical_news']['clues'][0]['relevance']
    def claim():return rpc(sql,'begin_user_historical_news',f"'project',{literal(h)}::jsonb,{literal(basis)}::jsonb")
    with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(lambda _:claim(),range(2)))
    assert sum(result is not None for result in results)==1


def test_failed_generation_does_not_start_unbounded_discovery_retries(sql):
    job=begin(sql)
    assert rpc(sql,'finish_user_historical_news',f"'project','{job['id']}','{{\"status\":\"unavailable\",\"clues\":[]}}'::jsonb")
    assert begin(sql) is None


def test_bulk_source_copy_does_not_attribute_an_unrelated_live_cue(sql):
    show_clue(sql)
    # Import/copy path supplies its own attribution. Only the live acceptance
    # RPC may attach a newly offered cue to version one.
    source=str(uuid4());turn=str(uuid4())
    sql(f"insert into public.user_narrator_source(user_id,project_id,id,client_turn_id,sequence,text,kind,language) values "
        f"('{OWNER}','project','{source}','{turn}',2,'Imported original.','narrator_chat','en-AU');")
    sql(f"insert into public.user_narrator_source_version(user_id,project_id,source_id,version,text,language) values "
        f"('{OWNER}','project','{source}',1,'Imported original.','en-AU');")
    assert sql(f"select attribution ? 'cue_context' from public.user_narrator_source_version where source_id='{source}';").stdout.strip()=='f'


@pytest.mark.parametrize('field,value',[('title','x'*201),('locator','x'*201),('retrieved_at','x'*41),('retrieved_at','now'),('retrieved_at','2026-99-99T00:00:00Z'),('publication_date','2020-99-99')])
def test_durable_evidence_bounds_match_application_contract(sql,field,value):
    job=begin(sql);clue=ready_context()['historical_news']['clues'][0];clue[field]=value
    assert rpc(sql,'finish_user_historical_news',f"'project','{job['id']}',{literal({'status':'ready','clues':[clue]})}::jsonb",check=False).returncode!=0
