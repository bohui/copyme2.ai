import json
from copy import deepcopy
from pathlib import Path

import httpx
import pytest

from apps.api import place_photo_pages as pages
from apps.api.place_photo_repository import PhotoRepository, search_key
from test_agent_commit_postgres import database, as_user, OWNER


def test_global_results_survive_worker_restart_and_paginate_for_another_user(monkeypatch):
    rows, writes, calls = {}, [], []
    def server(request):
        if request.method == 'POST':
            record = json.loads(request.content)
            rows[record['search_key']] = record
            writes.append(record)
            return httpx.Response(201)
        key = request.url.params['search_key'].removeprefix('eq.')
        return httpx.Response(200, json=[{'result': rows[key]['result']}] if key in rows else [])
    def repository():
        return PhotoRepository('https://example.supabase.co', 'server-secret', transport=httpx.MockTransport(server))
    def search(place, period, **kwargs):
        calls.append((place, period))
        items = [{'asset_id': str(i), 'image_url': f'https://images.example/{i}.jpg',
                  'source_url': f'https://archive.example/{i}',
                  'date_expression': '1983'} for i in range(25)]
        kwargs['on_items'](items[:2])
        return items
    monkeypatch.setattr(pages, 'search_place_photos', search)
    first_worker = pages.PhotoPages(repository=repository())
    try:
        first = first_worker.page('alice-project', 'Chengde', '1980s', None)
        assert len(first['items']) == 10
    finally:
        first_worker.close()
    second_worker = pages.PhotoPages(repository=repository())
    try:
        second = second_worker.page('bob-project', 'chengde', '1980s', None)
        last = second_worker.page('bob-project', 'chengde', '1980s', second['next_cursor'])
        assert len(calls) == 1
        assert second['count'] == 25 and last['items'][0]['asset_id'] == '10'
        with pytest.raises(Exception) as error:
            second_worker.page('alice-project', 'chengde', '1980s', second['next_cursor'])
        assert error.value.status_code == 422
        second_worker.page('bob-project', 'chengde', '1980s', None, refresh=True)
        assert len(calls) == 2
    finally:
        second_worker.close()
    assert any(not row['result']['complete'] for row in writes)
    assert writes[-1]['result']['complete']
    assert all('owner' not in row and 'project_id' not in row for row in writes)


def test_cache_key_normalizes_public_place_and_period_without_combining_periods():
    assert search_key(' Chengde  ', '1980s') == search_key('chengde', ' 1980S ')
    assert search_key('承德', '1980s') != search_key('承德', '1990s')


def test_saved_containing_decade_references_are_reused_for_a_narrow_period(monkeypatch):
    class Repository:
        def load(self, place, period):
            return {'complete': True, 'items': [{'asset_id': 'wider-reference',
                'date_expression': '1984', 'period_match': 'decade'}]}
    monkeypatch.setattr(pages, 'search_place_photos', lambda *args, **kwargs: pytest.fail('cached research repeated'))
    worker = pages.PhotoPages(repository=Repository())
    try:
        assert worker.page('new-user', '承德', '1983年', None)['items'][0]['asset_id'] == 'wider-reference'
    finally:
        worker.close()


@pytest.mark.parametrize('fails', [False, True])
def test_empty_matches_are_reusable_but_provider_errors_are_not_persisted(monkeypatch, fails):
    rows, calls = {}, []
    class Repository:
        def load(self, place, period): return deepcopy(rows.get((place, period)))
        def save(self, place, period, result): rows[(place, period)] = deepcopy(result)
    def search(*args, **kwargs):
        calls.append(args)
        if fails: raise pages.PhotoResearchUnavailable('google', 'verification_required')
        return []
    monkeypatch.setattr(pages, 'search_place_photos', search)
    for owner in ('alice', 'bob'):
        worker = pages.PhotoPages(repository=Repository())
        try: worker.page(owner, '承德', '1980s', None)
        finally: worker.close()
    assert len(calls) == (2 if fails else 1)


def test_global_database_is_server_writable_and_contains_no_user_story_data(database):
    database("do $$begin if not exists(select from pg_roles where rolname='service_role') then create role service_role bypassrls; end if; end$$;")
    migration = Path(__file__).resolve().parents[1] / 'supabase/migrations/202610020003_place_photo_searches.sql'
    database(migration.read_text())
    record = json.dumps({'items': [{'asset_id': 'public-photo'}], 'complete': True})
    database("set role service_role; insert into public.place_photo_searches(search_key,place,period,result) values('" + 'a'*64 + "','承德','1983年','" + record + "');")
    assert 'public-photo' in database('set role service_role; select result from public.place_photo_searches;').stdout
    assert database(as_user('select * from public.place_photo_searches;'),check=False).returncode != 0
    assert database(as_user("insert into public.place_photo_searches(search_key,place,period,result) values('" + 'b'*64 + "','x','1980s','{}');"),check=False).returncode != 0
    assert database('set role anon; select * from public.place_photo_searches;',check=False).returncode != 0
