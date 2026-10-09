"""A tail failure must roll back the complete feature migration on real PostgreSQL.

Uses the established disposable database transport only. The explicit standalone
fallback proves PostgreSQL transactional DDL; it is not an RLS/HTTP acceptance run.
"""
from contextlib import suppress
import json
from pathlib import Path

import pytest

from test_interview_photos_postgres import database
from test_guest_conversation_transfer import attachment_database
from test_private_rounds_postgres import private_database


ROOT = Path(__file__).resolve().parents[1]
FEATURE = ROOT / 'supabase/migrations/202610090001_interview_photos_plan.sql'
TAIL_REVOKE = ('revoke all on function public.safe_memoir_reuse(jsonb,text[],uuid) '
               'from public,anon,authenticated;')
FAILURE = 'controlled issue41 failure after final helper replacement'


@pytest.fixture
def prefeature_sql():
    # A fresh cluster per case is deliberate: the red regression commits DDL
    # that would otherwise contaminate the next parametrized baseline.
    setup = database.__wrapped__()
    sql = next(setup)
    try:
        attachment_database.__wrapped__(sql)
        private_database.__wrapped__(sql)
        for path in sorted((ROOT / 'supabase/migrations').glob('*.sql')):
            if '202610040001_shared_memory_events.sql' <= path.name < FEATURE.name:
                sql(path.read_text())
        yield sql
    finally:
        with suppress(StopIteration):
            next(setup)


def catalog(sql):
    """Capture real definitions/ACLs, not merely migration text ordering."""
    result = sql("""
      select jsonb_build_object(
        'relations', (select jsonb_agg(jsonb_build_object('schema',n.nspname,
          'name',c.relname,'kind',c.relkind,'rls',c.relrowsecurity,'acl',c.relacl)
          order by n.nspname,c.relname)
          from pg_class c join pg_namespace n on n.oid=c.relnamespace
          where n.nspname in ('public','storage') and c.relkind in ('r','p','i','S','v','m')),
        'project_columns', (select jsonb_agg(jsonb_build_object('name',a.attname,
          'type',format_type(a.atttypid,a.atttypmod),'not_null',a.attnotnull,
          'default',pg_get_expr(d.adbin,d.adrelid)) order by a.attnum)
          from pg_attribute a left join pg_attrdef d on d.adrelid=a.attrelid and d.adnum=a.attnum
          where a.attrelid='public.user_memoir_project'::regclass and a.attnum>0 and not a.attisdropped),
        'policies', (select jsonb_agg(jsonb_build_object('schema',n.nspname,'table',c.relname,
          'name',p.polname,'command',p.polcmd,'roles',p.polroles,'permissive',p.polpermissive,
          'using',pg_get_expr(p.polqual,p.polrelid),'check',pg_get_expr(p.polwithcheck,p.polrelid))
          order by n.nspname,c.relname,p.polname)
          from pg_policy p join pg_class c on c.oid=p.polrelid join pg_namespace n on n.oid=c.relnamespace
          where n.nspname in ('public','storage')),
        'functions', (select jsonb_agg(jsonb_build_object('name',p.proname,
          'arguments',pg_get_function_identity_arguments(p.oid),'definition',pg_get_functiondef(p.oid),
          'owner',p.proowner,'acl',p.proacl) order by p.proname,p.oid)
          from pg_proc p join pg_namespace n on n.oid=p.pronamespace where n.nspname='public' and p.prokind='f'),
        'triggers', (select jsonb_agg(pg_get_triggerdef(t.oid) order by t.tgrelid,t.tgname)
          from pg_trigger t join pg_class c on c.oid=t.tgrelid join pg_namespace n on n.oid=c.relnamespace
          where n.nspname='public' and not t.tgisinternal),
        'buckets', (select jsonb_agg(to_jsonb(b) order by b.id) from storage.buckets b)
      );
    """)
    return json.loads(result.stdout.strip())


@pytest.mark.parametrize('existing_bucket', [False, True])
def test_late_failure_rolls_back_entire_photo_migration(prefeature_sql, existing_bucket):
    sql = prefeature_sql
    if existing_bucket:
        sql("insert into storage.buckets(id,name,public,file_size_limit) "
            "values('memoir-private-photos','preexisting-control',true,52428800);")
    before = catalog(sql)
    migration = FEATURE.read_text()
    assert migration.count(TAIL_REVOKE) == 1
    failing = migration.replace(TAIL_REVOKE,
        f"do $late_failure$ begin raise exception '{FAILURE}'; end $late_failure$;\n{TAIL_REVOKE}")
    failure = sql(failing, check=False)
    assert failure.returncode != 0 and FAILURE in failure.stderr
    after = catalog(sql)
    for category in ('relations','project_columns','policies','functions','triggers','buckets'):
        assert after[category] == before[category], f'Late failure committed feature {category}'

    # A normal retry after rollback must apply cleanly, including the tail.
    sql(migration)
    assert sql("select to_regclass('public.user_interview_photo') is not null;").stdout.strip() == 't'
    assert sql("select count(*) from pg_attribute where attrelid='public.user_memoir_project'::regclass "
               "and attname='interview_sequence' and not attisdropped;").stdout.strip() == '1'
    assert sql("select public=false and file_size_limit=10485760 from storage.buckets "
               "where id='memoir-private-photos';").stdout.strip() == 't'
    assert sql("select has_function_privilege('authenticated', 'public.safe_memoir_reuse(jsonb,text[],uuid)', 'EXECUTE') "
               "or has_function_privilege('anon', 'public.safe_memoir_reuse(jsonb,text[],uuid)', 'EXECUTE');").stdout.strip() == 'f'
    bundle = {'sections':[{'id':'keep-section','event_ids':['keep'],'source_refs':[]},
                          {'id':'drop-section','event_ids':['drop'],'source_refs':[]}],
              'event_manifest':[{'id':'keep'},{'id':'drop'}],
              'photo_association_manifest':{'keep':'keep-digest','drop':'drop-digest'}}
    value = json.dumps(bundle).replace("'", "''")
    reused = json.loads(sql(f"select public.safe_memoir_reuse('{value}'::jsonb,array['drop']);").stdout)
    assert reused['photo_association_manifest'] == {'keep':'keep-digest'}
    assert [s['id'] for s in reused['sections']] == ['keep-section']
