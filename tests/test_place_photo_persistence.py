import json
import asyncio
import time
from copy import deepcopy
from pathlib import Path
from threading import Event
from urllib.error import URLError

import httpx
import pytest

from apps.api import place_photo_pages as pages
from apps.api import place_photos as photos
from apps.api import place_photo_transport as transport
from apps.api.place_photo_repository import PhotoRepository, search_key
from test_agent_commit_postgres import database, as_user, OWNER
from test_llm_place_photos import search_world
from test_place_workspace import google_result


def test_failed_resumed_research_keeps_seeded_photos_and_retries_after_restart(search_world):
    _, world = search_world
    world['response'] = URLError(TimeoutError('Synthetic provider timeout'))
    rows = {}

    def server(request):
        if request.method == 'POST':
            record = json.loads(request.content)
            rows[record['search_key']] = record
            return httpx.Response(201)
        key = request.url.params['search_key'].removeprefix('eq.')
        return httpx.Response(200, json=[{'result': rows[key]['result']}] if key in rows else [])

    repository = PhotoRepository('https://example.supabase.co', 'server-secret',
                                 transport=httpx.MockTransport(server))
    repository.save('Chengde', '1980s', {'complete': False, 'items': [{
        'asset_id': 'seeded', 'date_expression': '1983',
        'image_url': 'https://images.example/seeded.jpg',
        'source_url': 'https://archive.example/seeded'}]})
    for owner in ('after-first-restart', 'after-second-restart'):
        worker = pages.PhotoPages(repository=repository)
        try:
            result = worker.page(owner, 'Chengde', '1980s', None)
        finally:
            worker.close()
        assert result['items'][0]['asset_id'] == 'seeded'
        assert result['status'] == 'PARTIAL'
        assert result['failures']
        assert not result['searching']
    assert len(world['calls']) == 2


@pytest.mark.parametrize('blocked_operation', ['load', 'save'])
def test_slow_persistence_keeps_async_streams_and_other_searches_responsive(
        monkeypatch, search_world, blocked_operation):
    monkeypatch.delenv('MEMORY_SPARK_PHOTO_WORKER_URL', raising=False)
    entered, release = Event(), Event()
    rows = {}
    cold_key = search_key('Chengde', '1983年')
    blocking = False

    def server(request):
        if request.method == 'POST':
            record = json.loads(request.content)
            if blocking and blocked_operation == 'save' and record['search_key'] == cold_key:
                entered.set()
                release.wait(2)
            rows[record['search_key']] = record
            return httpx.Response(201)
        key = request.url.params['search_key'].removeprefix('eq.')
        if blocking and blocked_operation == 'load' and key == cold_key:
            entered.set()
            release.wait(2)
        return httpx.Response(200, json=[{'result': rows[key]['result']}] if key in rows else [])

    repository = PhotoRepository('https://example.supabase.co', 'server-secret',
                                 transport=httpx.MockTransport(server))
    cached = {'complete': True, 'items': [{'asset_id': 'cached', 'date_expression': '1983',
              'image_url': 'https://images.example/street.jpg',
              'source_url': 'https://archive.example/photo'}]}
    repository.save('Chengde', '1980s', cached)
    if blocked_operation == 'load':
        repository.save('Chengde', '1983年', cached)
    worker = pages.PhotoPages(repository=repository)
    worker.page('hot-user', 'Chengde', '1980s', None)
    blocking = True

    async def check():
        cold = None
        try:
            start = time.monotonic()
            cold = await transport.photo_response(worker, 'cold-user', 'Chengde', '1983年', None,
                                                  stream=True)
            assert await asyncio.to_thread(entered.wait, 1)
            hot = await transport.photo_response(worker, 'hot-user', 'Chengde', '1980s', None,
                                                 stream=True)
            frames = [json.loads(frame) async for frame in hot.body_iterator]
            await asyncio.sleep(0.01)
            assert time.monotonic() - start < 0.5, 'persistence blocked unrelated async work'
            assert not release.is_set()
            assert frames[-1]['items'][0]['asset_id'] == 'cached'
        finally:
            release.set()
            if cold is not None:
                frames = [json.loads(frame) async for frame in cold.body_iterator]
                assert frames[-1]['items'][0]['image_url'] == 'https://images.example/street.jpg'

    try:
        asyncio.run(check())
    finally:
        release.set()
        worker.close()


@pytest.mark.parametrize('located', [False, True])
@pytest.mark.parametrize('exact_identity', ['image', 'flickr'])
def test_restarted_research_keeps_verified_location_enrichment_for_the_same_image(
        monkeypatch, search_world, located, exact_identity):
    monkeypatch.setenv('MEMORY_SPARK_PHOTO_WEB_SEARCH', '0')
    monkeypatch.setenv('GOOGLE_CSE_API_KEY', 'fixture-key')
    monkeypatch.setenv('GOOGLE_CSE_ID', 'fixture-engine')
    candidate = google_result(1)
    candidate['link'] = 'https://images.example/shared.jpg'
    cached_image = candidate['link']
    cached_source = 'https://archive.example/earlier'
    if exact_identity == 'flickr':
        cached_image = 'https://live.staticflickr.com/12/456_thumbnailsecret_z.jpg'
        cached_source = 'https://www.flickr.com/photos/123@N01/456/'
        candidate['link'] = 'https://live.staticflickr.com/12/456_originalsecret_o.jpg'
        candidate['image']['contextLink'] = 'https://www.flickr.com/photos/author/456/'
    if not located:
        candidate['pagemap']['imageobject'] = []
    discovered, release = Event(), Event()

    def catalog(request_url, **kwargs):
        if 'customsearch.googleapis.com' in request_url:
            discovered.set()
            assert release.wait(2)
        value = {'items': [candidate]} if 'customsearch.googleapis.com' in request_url else {}
        return httpx.Response(200, json=value, request=httpx.Request('GET', request_url))

    monkeypatch.setattr(httpx, 'get', catalog)
    rows = {}

    def server(request):
        if request.method == 'POST':
            record = json.loads(request.content)
            rows[record['search_key']] = record
            return httpx.Response(201)
        key = request.url.params['search_key'].removeprefix('eq.')
        return httpx.Response(200, json=[{'result': rows[key]['result']}] if key in rows else [])

    repository = PhotoRepository('https://example.supabase.co', 'server-secret',
                                 transport=httpx.MockTransport(server))
    repository.save('Chengde', '1980s', {'complete': False, 'items': [{
        'asset_id': 'location-unknown', 'date_expression': '1983',
        'image_url': cached_image, 'source_url': cached_source}]})
    center = {'latitude': 40.98, 'longitude': 117.94}
    for owner in ('first-user', 'after-another-restart'):
        worker = pages.PhotoPages(repository=repository)
        async def streamed_result():
            stream = worker.stream(owner, 'Chengde', '1980s', None, **center)
            try:
                first = json.loads(await anext(stream))
                if owner == 'first-user':
                    assert await asyncio.to_thread(discovered.wait, 1)
                    seeded = json.loads(await asyncio.wait_for(anext(stream), 1))
                    assert seeded['searching'] and seeded['count'] == 0
                    release.set()
                frames = [json.loads(frame) async for frame in stream]
                return frames[-1] if frames else first
            finally:
                release.set()
                await stream.aclose()
        try:
            result = asyncio.run(streamed_result())
        finally:
            release.set()
            worker.close()
        assert result['count'] == 1
        assert result['items'][0]['search_fallback'] == ('none' if located else 'gps')
        if located:
            assert result['items'][0]['latitude'] == 40.98
            assert result['items'][0]['longitude'] == 117.94
            assert result['items'][0]['source_url'] == candidate['image']['contextLink']


def test_restarted_worker_resumes_incomplete_research_without_losing_cached_photos(search_world):
    _, world = search_world
    rows = {}

    def server(request):
        if request.method == 'POST':
            record = json.loads(request.content)
            rows[record['search_key']] = record
            return httpx.Response(201)
        key = request.url.params['search_key'].removeprefix('eq.')
        return httpx.Response(200, json=[{'result': rows[key]['result']}] if key in rows else [])

    def repository():
        return PhotoRepository('https://example.supabase.co', 'server-secret',
                               transport=httpx.MockTransport(server))

    cached_photo = {'asset_id': 'before-restart', 'date_expression': '1983',
                    'image_url': 'https://images.example/cached.jpg',
                    'source_url': 'https://archive.example/cached'}
    repository().save('Chengde', '1980s', {'items': [cached_photo], 'complete': False})
    worker = pages.PhotoPages(repository=repository())
    try:
        result = worker.page('new-user', 'Chengde', '1980s', None)
    finally:
        worker.close()

    assert result['count'] == 2
    assert result['items'][0]['asset_id'] == 'before-restart'
    assert result['items'][1]['image_url'] == 'https://images.example/street.jpg'
    assert not result['searching']
    assert len(world['calls']) == 1
    assert rows[search_key('Chengde', '1980s')]['result']['complete']


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
    assert len(calls) == 2
    assert [call[1] for call in calls] == (['1980s', '1980s'] if fails else ['1980s', photos.ANY_PHOTO_DATE])


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
