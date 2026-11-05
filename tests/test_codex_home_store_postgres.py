"""Real Storage RLS: owner reads, server writes, no client history replacement."""
import os

import pytest

from test_agent_commit_postgres import database, as_user, OWNER, OTHER


def test_codex_home_bucket_is_private_and_clients_cannot_replace_history(database):
    if os.getenv('MEMOIR_TEST_POSTGRES_BACKEND') == 'single-user':
        pytest.skip('Single-user PostgreSQL bypasses RLS')
    sql = database
    bucket = 'memory-spark'
    path = OWNER + '/sandbox/11111111-1111-4111-8111-111111111111/' + 'a' * 64 + '/checkpoint.zip'
    sql('grant usage on schema storage to authenticated; '
        'grant select,insert,update,delete on storage.objects to authenticated; '
        'alter table storage.objects enable row level security;')
    assert sql("select public from storage.buckets where id='" + bucket + "';").stdout.strip() == 'f'
    sql("insert into storage.objects(bucket_id,name) values ('" + bucket + "','" + path + "');")
    query = "select count(*) from storage.objects where bucket_id='" + bucket + "' and name='" + path + "';"
    assert sql(as_user(query, OWNER)).stdout.strip() == '1'
    assert sql(as_user(query, OTHER)).stdout.strip() == '0'
    for owner in (OWNER, OTHER):
        insert = "insert into storage.objects(bucket_id,name) values ('" + bucket + "','" + owner + "/sandbox/replacement.zip');"
        assert sql(as_user(insert, owner), check=False).returncode != 0
        sql(as_user("update storage.objects set name='" + owner + "/attachment/replaced' where name='" + path + "';", owner))
        sql(as_user("delete from storage.objects where name='" + path + "';", owner))
    assert sql("select name from storage.objects where name='" + path + "';").stdout.strip() == path
    # Existing attachment uploads retain their owner-writable policy.
    sql(as_user("insert into storage.objects(bucket_id,name) values ('memory-spark','" + OWNER + "/attachment/allowed.txt');"))
    assert sql('set role anon; ' + query, check=False).returncode != 0
