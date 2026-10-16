"""Login preserves stage progress through the real guest-transfer RPCs."""
import json
import os
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from apps.api.main import create_app
from apps.api.stage_readiness import readiness
from apps.api.store import MemoryStore
from memoir_postgres_workflow import PostgresRest
from stage_progress_fixture import save_stage_source, link_stage
from test_agent_commit_postgres import OWNER, OTHER, OLD, as_user, database
from test_guest_conversation_transfer import attachment_database, TOKEN
from test_private_rounds_postgres import private_database
from test_shared_memory_events_postgres import sql, event_database, literal, rpc
from test_lifetime_memory_postgres import resolve


def transferred_project(sql, *, existing_account=False, legacy_stages=False):
    if existing_account:
        resolve(sql, owner=OTHER)
    project = resolve(sql)['project_id']
    source = save_stage_source(sql, project, '童' * 145)
    ref = {'source_id': source['id'], 'version': source['version'],
           'quote': source['text'], 'char_start': 0, 'char_end': len(source['text'])}
    proposal = {'kind': 'event', 'title': 'Synthetic childhood', 'life_stage': 'childhood',
                'source_refs': [ref], 'stage_evidence': [{**ref, 'quote': '童童', 'char_end': 2}]}
    rpc(sql, 'apply_user_memory_events', f"{literal(project)},"
        f"{literal([{'id': source['id'], 'version': source['version']}])}::jsonb,{literal([proposal])}::jsonb")
    # Accepted input without a successful reply must stay out after transfer too.
    unsaved = rpc(sql, 'accept_user_narrator_source', f"{literal(project)},'{uuid4()}','晚'")
    link_stage(sql, project, unsaved, 'later_life')
    if legacy_stages:
        sql(f"update public.user_memory set life_stage='childhood' where user_id='{OWNER}';")
        content = 'Storyteller: ' + '初' * 100 + '\nMemory Spark: A saved legacy reply.'
        sql(f"insert into public.user_memory(user_id,project_id,kind,content,life_stage) values "
            f"('{OWNER}',{literal(project)},'agent',{literal(content)},'baby');")
    rpc(sql, 'release_user_agent_turn_lease', f"'{OLD}'")
    sql(f"update auth.users set is_anonymous=true where id='{OWNER}';")
    messages = [{'role': 'user', 'text': source['text']}, {'role': 'assistant', 'text': 'A synthetic reply.'}]
    rpc(sql, 'prepare_guest_conversation_transfer', f"'{TOKEN}',{literal(project)},{literal(messages)}::jsonb")
    receipt = rpc(sql, 'attach_guest_conversation', f"'{TOKEN}'", owner=OTHER)
    assert receipt['attached'] is True
    return project, source


@pytest.mark.parametrize('existing_account', [False, True])
def test_login_and_cold_read_preserve_stage_progress_without_mapping(sql, existing_account):
    project, _ = transferred_project(sql, existing_account=existing_account)
    mappings = sql('select row_to_json(c) from public.user_lifetime_conversation c order by user_id;').stdout
    with TestClient(create_app(MemoryStore(), story_storage_factory=lambda _: PostgresRest(sql, OTHER).storage())) as client:
        for _ in range(2):
            response = client.get('/v1/story/readiness', params={'project_id': project})
            assert response.status_code == 200, response.text
            stages = response.json()['stages']
            assert stages['childhood'] == readiness(145)
            assert all(value == readiness(0) for stage, value in stages.items() if stage != 'childhood')
            assert response.json()['pending'] is False
    assert sql('select row_to_json(c) from public.user_lifetime_conversation c order by user_id;').stdout == mappings
    assert sql(as_user(f"select count(*) from public.user_lifetime_conversation where project_id={literal(project)};", OTHER)).stdout.strip() == '0'


def test_transferred_legacy_rows_remain_counted_without_doubling_direct_evidence(sql):
    project, _ = transferred_project(sql, legacy_stages=True)
    stages = rpc(sql, 'read_lifetime_stage_readiness', literal(project), owner=OTHER)['stages']
    assert stages['baby'] == readiness(100)
    assert stages['childhood'] == readiness(145)


def test_transferred_progress_rejects_other_owners_and_obeys_edits_and_withdrawal(sql):
    from test_guest_conversation_transfer import THIRD
    project, source = transferred_project(sql)
    assert rpc(sql, 'read_lifetime_stage_readiness', literal(project), owner=THIRD, check=False).returncode
    assert rpc(sql, 'read_lifetime_stage_readiness', literal(project), owner=OTHER)['stages']['childhood'] == readiness(145)
    rpc(sql, 'change_user_narrator_source', f"{literal(project)},'{source['id']}',1,'edit','更正童年'", owner=OTHER)
    assert rpc(sql, 'read_lifetime_stage_readiness', literal(project), owner=OTHER)['stages']['childhood'] == readiness(0)
    rpc(sql, 'change_user_narrator_source', f"{literal(project)},'{source['id']}',2,'withdraw',null", owner=OTHER)
    assert all(value == readiness(0) for value in rpc(sql, 'read_lifetime_stage_readiness', literal(project), owner=OTHER)['stages'].values())


def test_migration_repairs_an_existing_transfer_without_rewriting_memories(sql):
    project, _ = transferred_project(sql)
    root = Path(__file__).resolve().parents[1] / 'supabase/migrations'
    old = (root / '202610150003_canonical_stage_readiness.sql').read_text()
    definition = old.split('create or replace function public.read_lifetime_stage_readiness', 1)[1].split('end $$;', 1)[0]
    sql('create or replace function public.read_lifetime_stage_readiness' + definition + 'end $$;')
    assert rpc(sql, 'read_lifetime_stage_readiness', literal(project), owner=OTHER, check=False).returncode
    tables = ('user_memory', 'user_narrator_source', 'user_memory_event', 'user_memory_event_source', 'user_lifetime_conversation')
    before = [sql(f'select to_jsonb(t) from public.{table} t order by to_jsonb(t)::text;').stdout for table in tables]
    migration = (root / '202610160004_transferred_stage_readiness.sql').read_text()
    for _ in range(2):
        sql(migration)
        assert rpc(sql, 'read_lifetime_stage_readiness', literal(project), owner=OTHER)['stages']['childhood'] == readiness(145)
    assert [sql(f'select to_jsonb(t) from public.{table} t order by to_jsonb(t)::text;').stdout for table in tables] == before


@pytest.mark.skipif(not os.getenv('MEMOIR_BROWSER_URL'), reason='Requires source frontend')
@pytest.mark.parametrize('locale', ['en-AU', 'zh-CN'])
def test_transferred_stage_ring_survives_browser_reload(sql, locale):
    from playwright.sync_api import expect, sync_playwright
    from browser_story_history_fixture import StoryHistoryFixture
    from browser_supabase_fixture import install_supabase_fixture

    project, _ = transferred_project(sql)
    history = StoryHistoryFixture(OTHER, project, 'fixture-only')
    place = {'place': 'Synthetic Garden', 'hierarchy': ['Earth', 'Australia', 'Synthetic Garden'],
             'granularity': 'city', 'life_stage': 'childhood', 'latitude': -33.8, 'longitude': 151.2}
    profile = {'preferred_language': locale, 'memory_places': [place]}
    with TestClient(create_app(MemoryStore(), story_storage_factory=lambda _: PostgresRest(sql, OTHER).storage())) as client:
        def api(route):
            if history.serve(route):
                return
            path = route.request.url.split('/api/v1/memoir')[-1].split('?')[0]
            data = {}
            if path == '/agent/config':
                data = {'supabase_url': 'https://auth.test', 'supabase_publishable_key': 'public', 'auth_mode': 'supabase'}
            elif path in ('/agent/profile', '/user/profile'):
                data = profile
            elif path == '/projects/' + project:
                data = {'id': project, 'revision': 1, 'mode': 'self', 'profile': profile}
            elif path.endswith('/journey'):
                data = {'active_session': None}
            elif path == '/story/state':
                data = {'recall_status': {'rounds_completed': 1, 'free_rounds': 20, 'payment_required': False}}
            elif path == '/story/readiness':
                response = client.get('/v1/story/readiness', params={'project_id': project})
                assert response.status_code == 200, response.text
                data = response.json()
            elif path == '/agent/place-journey':
                data = {'place_journey': place}
            route.fulfill(content_type='application/json', body=json.dumps(data))

        with sync_playwright() as pw:
            browser = pw.chromium.launch(executable_path=os.getenv('MEMOIR_BROWSER_EXECUTABLE'))
            page = browser.new_page(viewport={'width': 1440, 'height': 1000})
            base = os.environ['MEMOIR_BROWSER_URL']
            page.route('**/*', lambda route: route.continue_() if route.request.url.startswith(base + '/') else route.abort())
            user = {'id': OTHER, 'is_anonymous': False, 'user_metadata': {'ui_locale': locale}}
            install_supabase_fixture(page, "window.supabase={createClient:()=>({auth:{getSession:async()=>({data:{session:"
                + json.dumps({'access_token': 'fixture-only', 'user': user})
                + "}}),getUser:async()=>({data:{user:" + json.dumps(user)
                + "}}),onAuthStateChange:()=>({})}})};")
            page.route('**/api/v1/memoir/**', api)
            page.goto(base + '/memoir/interview/' + project)
            ring = page.locator('[data-life-stage-tab="childhood"] .life-stage-readiness')
            expect(ring).to_have_attribute('style', '--readiness:14.5%')
            page.reload()
            expect(ring).to_have_attribute('style', '--readiness:14.5%')
            expect(ring).to_have_class('life-stage-readiness readiness-red')
            expect(page.locator('[data-life-stage-tab="later_life"] .life-stage-readiness')).to_have_attribute('style', '--readiness:0%')
            page.wait_for_load_state('networkidle')
            output = Path(__file__).resolve().parents[1] / f'output/preview-debug/stage-rings-transfer-{locale}.png'
            output.parent.mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(output), clip=page.locator('.life-stage-navigator').bounding_box())
            browser.close()
