"""Exercise ordered fallbacks through the public photo endpoint and its cache."""
import asyncio
from copy import deepcopy
import json
from threading import Event

from fastapi.testclient import TestClient
import pytest

from apps.api import place_photo_pages as pages
from apps.api import place_photos as photos
from apps.api.main import create_app
from apps.api.store import MemoryStore
from test_llm_place_photos import search_world


CENTER = {'latitude': 40.98, 'longitude': 117.94}


def picture(identifier, **fields):
    return {'asset_id': identifier, 'title': 'Chengde street', 'location': 'Chengde',
            'date_expression': '1983', 'image_url': f'https://images.example/{identifier}.jpg',
            'source_url': f'https://archive.example/{identifier}',
            'allowed_actions': {'embed': True, 'download': False, 'print': False}, **fields}


@pytest.mark.parametrize('stream', [False, True])
@pytest.mark.parametrize('tier', ['strict', 'gps', 'gps_time'])
def test_public_endpoint_relaxes_only_after_the_previous_tier_is_empty(monkeypatch, stream, tier):
    calls = []
    def search(place, period, **kwargs):
        calls.append(period)
        if period == '1983年':
            return ([picture('strict', **CENTER), picture('no-gps')] if tier == 'strict'
                    else [picture('no-gps')] if tier == 'gps' else [])
        return [picture('different-time', date_expression='2020'), picture('undated', date_expression='')]
    monkeypatch.setattr(pages, 'search_place_photos', search)
    monkeypatch.delenv('MEMORY_SPARK_PHOTO_WORKER_URL', raising=False)
    with TestClient(create_app(MemoryStore())) as client:
        headers = {'X-Account-Id': 'photo-owner',
                   'Accept': 'application/x-ndjson' if stream else 'application/json'}
        project = client.post('/v1/projects', headers=headers, json={'mode': 'self'}).json()
        response = client.get(f"/v1/projects/{project['id']}/place-photos", headers=headers,
                              params={'place': 'Chengde', 'period': '1983年', **CENTER})
    assert response.status_code == 200
    result = json.loads(response.text.splitlines()[-1]) if stream else response.json()
    expected = ['strict'] if tier == 'strict' else ['no-gps'] if tier == 'gps' else ['different-time', 'undated']
    assert [item['asset_id'] for item in result['items']] == expected
    assert {item['search_fallback'] for item in result['items']} == {'none' if tier == 'strict' else tier}
    assert all(item['requested_period'] == '1983年' and item['search_place'] == 'Chengde' for item in result['items'])
    assert calls == (['1983年', photos.ANY_PHOTO_DATE] if tier == 'gps_time' else ['1983年'])


def test_fallback_waits_for_strict_search_to_finish(monkeypatch):
    release = Event()
    def search(place, period, *, on_items, **kwargs):
        on_items([picture('no-gps')])
        assert release.wait(2)
        return [picture('strict', **CENTER)]
    monkeypatch.setattr(pages, 'search_place_photos', search)
    cache = pages.PhotoPages()
    async def check():
        reader = cache.stream('owner', 'Chengde', '1983年', None, **CENTER)
        assert json.loads(await anext(reader))['searching']
        progress = json.loads(await anext(reader))
        assert progress['items'] == []
        release.set()
        results = [json.loads(line) async for line in reader]
        assert [item['asset_id'] for item in results[-1]['items']] == ['strict']
    try:
        asyncio.run(check())
    finally:
        release.set()
        cache.close()


def test_time_fallback_survives_worker_restart_and_keeps_cursor_scope(monkeypatch):
    rows, calls = {}, []
    class Repository:
        def load(self, place, period): return deepcopy(rows.get((place, period)))
        def save(self, place, period, result): rows[(place, period)] = deepcopy(result)
    def search(place, period, **kwargs):
        calls.append(period)
        return [] if period == '1983年' else [picture(str(index), date_expression='2020') for index in range(12)]
    monkeypatch.setattr(pages, 'search_place_photos', search)
    for owner in ['first', 'second']:
        cache = pages.PhotoPages(repository=Repository())
        try:
            first = cache.page(owner, 'Chengde', '1983年', None, **CENTER)
            assert len(first['items']) == 10 and first['count'] == 12
            last = cache.page(owner, 'Chengde', '1983年', first['next_cursor'], **CENTER)
            assert len(last['items']) == 2 and last['next_cursor'] is None
            with pytest.raises(Exception) as error:
                cache.page('other-owner', 'Chengde', '1983年', first['next_cursor'], **CENTER)
            assert error.value.status_code == 422
        finally:
            cache.close()
    assert len(calls) == 2


def test_provider_failure_is_not_an_empty_search(monkeypatch):
    calls = []
    def search(place, period, **kwargs):
        calls.append(period)
        raise photos.PhotoResearchUnavailable('google', 'verification_required')
    monkeypatch.setattr(pages, 'search_place_photos', search)
    cache = pages.PhotoPages()
    try:
        assert cache.page('owner', 'Chengde', '1983年', None, **CENTER)['status'] == 'UNAVAILABLE'
        assert calls == ['1983年']
    finally:
        cache.close()


def test_missing_search_center_marks_source_described_photos_as_gps_fallback(monkeypatch):
    monkeypatch.setattr(pages, 'search_place_photos', lambda *args, **kwargs: [picture('no-gps')])
    cache = pages.PhotoPages()
    try:
        result = cache.page('owner', 'Chengde', '1983年', None)
        assert result['items'][0]['search_fallback'] == 'gps'
        assert result['search_center'] is None
    finally:
        cache.close()


def test_gps_fallback_rechecks_cached_place_evidence_for_a_named_subject(monkeypatch):
    class Repository:
        def load(self, place, period):
            return {'complete': True, 'items': [
                picture('city', title='承德市街景', location_evidence='河北承德市街景'),
                picture('ship', title='升級中的承德號巡防艦', location_evidence='升級中的承德號巡防艦'),
            ]}
    cache = pages.PhotoPages(repository=Repository())
    try:
        result = cache.page('owner', '承德市', '1983年', None, **CENTER)
        assert [item['asset_id'] for item in result['items']] == ['city']
    finally:
        cache.close()


def test_broader_discovery_keeps_place_rights_and_future_date_checks(monkeypatch):
    monkeypatch.delenv('GOOGLE_CSE_API_KEY', raising=False)
    monkeypatch.delenv('GOOGLE_CSE_ID', raising=False)
    monkeypatch.delenv('GOOGLE_CSE_URL', raising=False)
    monkeypatch.delenv('FLICKR_API_KEY', raising=False)
    monkeypatch.delenv('MEMORY_SPARK_PHOTO_WEB_SEARCH', raising=False)
    monkeypatch.setattr(photos, '_commons', lambda *args: [
        picture('old', date_expression='1900'), picture('undated', date_expression=''),
        picture('future', date_expression='2099'), picture('wrong-place', title='Chengdu street'),
    ])
    monkeypatch.setattr(photos, '_loc', lambda *args: [])
    monkeypatch.setattr(photos, '_flickr_browser', lambda *args: [])
    monkeypatch.setattr('apps.api.place_photo_fingerprints.image_fingerprint', lambda url: {})
    found = photos.search_place_photos('Chengde', photos.ANY_PHOTO_DATE)
    assert [item['asset_id'] for item in found] == ['old', 'undated']
    assert all(item['allowed_actions']['print'] is False for item in found)


@pytest.mark.parametrize('date_expression', ['1900-10-01', ''])
def test_llm_time_fallback_inspects_real_source_metadata(search_world, date_expression):
    _, world = search_world
    world['pages']['https://archive.example/photo'] = (
        '<title>Chengde photographs</title><script type="application/ld+json">' + json.dumps({
            '@type': 'Photograph', 'name': 'Chengde street', 'dateCreated': date_expression,
            'contentUrl': 'https://images.example/street.jpg'}) + '</script>')
    item, = photos.search_place_photos('Chengde', photos.ANY_PHOTO_DATE)
    assert item['date_expression'] == date_expression
    assert item['allowed_actions']['publish'] is False
    assert 'any capture period' in world['calls'][0]['input']


@pytest.mark.parametrize('date_expression', ['1900-10-01', '', '2099-10-01'])
def test_browser_time_fallback_keeps_original_dates_or_marks_them_unknown(date_expression):
    from apps.api.place_photo_browser import _source_items
    page = '<title>Chengde photographs</title><script type="application/ld+json">' + json.dumps({
        '@type': 'Photograph', 'name': 'Chengde street', 'dateTaken': date_expression,
        'contentUrl': 'https://images.example/street.jpg'}) + '</script>'
    found = _source_items(page, 'https://archive.example/photo', 'Chengde', photos.ANY_PHOTO_DATE)
    if date_expression.startswith('2099'):
        assert found == []
    else:
        assert found and {item['date_expression'] for item in found} == {date_expression}
