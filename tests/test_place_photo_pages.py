from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient
import pytest

from apps.api import place_photos as photos
from apps.api import place_photo_pages as pages
from apps.api.main import create_app
from apps.api.store import MemoryStore


@pytest.fixture(autouse=True)
def no_live_image_fetches(monkeypatch):
    monkeypatch.setattr('apps.api.place_photo_fingerprints.image_fingerprint', lambda url: {})


def picture(index, host='archive.example', **fields):
    return {'asset_id': f'{host}-{index}', 'title': 'Chengde street', 'location': 'Chengde',
            'date_expression': '1983', 'image_url': f'https://images.{host}/{index}.jpg',
            'latitude': 40.98, 'longitude': 117.94,
            'source_url': f'https://{host}/{index}', 'allowed_actions': {'embed': True}, **fields}


def test_pool_filters_place_period_and_interleaves_original_sources(monkeypatch):
    monkeypatch.delenv('GOOGLE_CSE_API_KEY', raising=False)
    monkeypatch.setenv('GOOGLE_CSE_ID', 'engine')
    monkeypatch.delenv('FLICKR_API_KEY', raising=False)
    monkeypatch.setattr(photos, '_flickr_browser', lambda *args: [picture(i, 'flickr.com') for i in range(20)])
    monkeypatch.setattr(photos, '_google_browser', lambda *args: [picture(i, 'archive.example') for i in range(20)])
    monkeypatch.setattr(photos, '_commons', lambda *args: [picture(i, 'commons.wikimedia.org') for i in range(20)])
    monkeypatch.setattr(photos, '_loc', lambda *args: [picture(1, 'loc.gov'),
        picture(2, 'loc.gov', title='Chengdu street'), picture(3, 'loc.gov', date_expression='2000'),
        picture(4, 'loc.gov', date_expression='')])
    result = photos.search_place_photos('Chengde', '1980s')
    assert [item['source_url'].split('/')[2] for item in result[:4]] == [
        'flickr.com', 'archive.example', 'commons.wikimedia.org', 'loc.gov']
    assert all(item['title'] == 'Chengde street' and item['date_expression'] == '1983' for item in result)
    assert len(photos.search_place_photos('Chengde', '1980s', limit=None)) == 61


def test_current_window_and_location_boundaries():
    today = datetime.now(ZoneInfo('Australia/Sydney')).date()
    assert photos._date_matches(today.isoformat(), '')
    assert photos._date_matches((today - timedelta(days=100)).isoformat(), '')
    assert not photos._date_matches('1983', '')
    assert not photos._date_matches((today + timedelta(days=1)).isoformat(), '')
    assert not photos._date_matches('', '')
    assert not photos._location_matches('Chengdeburg or Chengdu', 'Chengde')
    assert not photos._location_matches('Hebei, China', 'Chengde, Hebei, China')
    assert photos._location_matches('承德街景', 'Chengde, Hebei, China')


@pytest.mark.parametrize('remote_worker', [False, True])
@pytest.mark.parametrize('stream', [False, True])
def test_endpoint_ranks_by_context_year_then_distance_to_the_selected_place(monkeypatch, remote_worker, stream):
    import json
    import httpx
    from apps.api.photo_worker_service import create_photo_worker
    candidates = [picture('1989', date_expression='1989'),
                  picture('1983-far', date_expression='1983', latitude=41.00),
                  picture('1982', date_expression='1982', latitude=41.01),
                  picture('1980', date_expression='1980'),
                  picture('1984', date_expression='1984'),
                  picture('1983-near', date_expression='1983'),
                  picture('wrong-place', location_evidence='Beijing street')]
    calls = []
    monkeypatch.delenv('MEMORY_SPARK_PHOTO_WORKER_URL', raising=False)
    monkeypatch.setattr(pages, 'search_place_photos',
        lambda *args, **kwargs: calls.append(args) or candidates)
    if remote_worker:
        worker_cache = pages.PhotoPages()
        worker = create_photo_worker(pages=worker_cache)
        original = httpx.AsyncClient
        monkeypatch.setenv('MEMORY_SPARK_PHOTO_WORKER_URL', 'http://worker:8767')
        monkeypatch.setenv('MEMORY_SPARK_PHOTO_WORKER_SECRET', 'fixture-secret')
        monkeypatch.setattr(httpx, 'AsyncClient', lambda **kwargs:
            original(transport=httpx.ASGITransport(app=worker), **kwargs))

    def result(response):
        assert response.status_code == 200, response.text
        return json.loads(response.text.splitlines()[-1]) if stream else response.json()

    with TestClient(create_app(MemoryStore())) as client:
        headers = {'X-Account-Id': 'ranking-owner',
                   'Accept': 'application/x-ndjson' if stream else 'application/json'}
        project = client.post('/v1/projects', headers=headers, json={'mode': 'self'}).json()
        url = f"/v1/projects/{project['id']}/place-photos"
        params = {'place': 'Chengde', 'period': '1980s', 'context_year': 1983,
                  'latitude': 40.98, 'longitude': 117.94}
        ranked = result(client.get(url, params=params, headers=headers))
        assert [item['asset_id'] for item in ranked['items']] == [
            'archive.example-1983-near', 'archive.example-1983-far', 'archive.example-1984',
            'archive.example-1982', 'archive.example-1980', 'archive.example-1989']
        assert ranked['photo_order'] == [item['asset_id'] for item in ranked['items']]
        changed = result(client.get(url, params={**params, 'context_year': 1984}, headers=headers))
        assert changed['items'][0]['asset_id'] == 'archive.example-1984'
        assert len(calls) == 1, 'Ranking another year must reuse the same public discovery pool'
    if remote_worker:
        worker_cache.close()


def test_google_webpage_dates_cannot_date_a_photo():
    result = {'title': 'Chengde street', 'pagemap': {'metatags': [
        {'datePublished': '1983', 'dateModified': '1983', 'uploadDate': '1983'}]}}
    assert photos._google_date(result, '1980s') is None


def test_relevance_ranks_known_capture_dates_and_coordinates_before_unknown_metadata():
    items = [picture('undated', date_expression=''),
             picture('no-gps', latitude=None, longitude=None),
             picture('range', date_expression='1980–1989'),
             picture('far', latitude=41.02), picture('near')]
    ranked = photos.rank_place_photos(items, '1980s', {'latitude':40.98,'longitude':117.94}, 1983)
    assert [item['asset_id'] for item in ranked] == [f'archive.example-{name}' for name in (
        'near','far','no-gps','range','undated')]


def test_cached_pool_is_reranked_per_context_with_stable_year_bound_cursors(monkeypatch):
    candidates = [picture(index, date_expression=str(1980 + index % 10)) for index in range(15)]
    class Repository:
        def load(self, place, period): return {'items':candidates, 'complete':True}
    monkeypatch.setattr(pages, 'search_place_photos', lambda *a, **k: pytest.fail('Reuse public discovery'))
    for year in (1983, 1989):
        cache = pages.PhotoPages(repository=Repository())
        try:
            first = cache.page('owner', 'Chengde', '1980s', None, context_year=year)
            assert first['items'][0]['date_expression'] == str(year)
            with pytest.raises(Exception) as error:
                cache.page('owner', 'Chengde', '1980s', first['next_cursor'], context_year=1984)
            assert error.value.status_code == 422
            last = cache.page('owner', 'Chengde', '1980s', first['next_cursor'], context_year=year)
            found = first['items'] + last['items']
            assert len({item['asset_id'] for item in found}) == 15
            gaps = [abs(int(item['date_expression'])-year) for item in found]
            assert gaps == sorted(gaps)
        finally:
            cache.close()


def test_deduplication_matches_flickr_sizes_commons_thumbnails_and_hashes():
    original = picture(1, image_url='https://live.staticflickr.com/12/123_secret_z.jpg')
    larger = picture(2, 'other.example', image_url='https://farm4.staticflickr.com/12/123_secret_b.jpg?utm_source=google')
    commons = picture(3, image_url='https://upload.wikimedia.org/wikipedia/commons/thumb/a/ab/Street.jpg/640px-Street.jpg')
    commons_original = picture(4, 'other.example', image_url='https://upload.wikimedia.org/wikipedia/commons/a/ab/Street.jpg')
    thumb_host = picture(9, 'other.example', memory_reference_only=True,
        image_url='https://thumb.wikimedia.org/wikipedia/commons/thumb/a/ab/Street.jpg/120px-Street.jpg')
    hashed = picture(5, content_hash='verified-hash')
    rehosted = picture(6, 'rehost.example', content_hash='verified-hash')
    assert photos._deduplicate([original, larger, commons, commons_original, thumb_host, hashed, rehosted]) == [original, commons, hashed]
    flickr_api = picture(7, source_url='https://www.flickr.com/photos/123@N01/456/',
                         image_url='https://live.staticflickr.com/12/456_thumbnailsecret_z.jpg')
    flickr_browser = picture(8, memory_reference_only=True, source_url='https://www.flickr.com/photos/author/456/',
                             image_url='https://live.staticflickr.com/12/456_originalsecret_o.jpg')
    assert photos._deduplicate([flickr_api, flickr_browser]) == [flickr_api]


def test_stable_pages_reuse_one_search_and_reject_other_queries(monkeypatch):
    calls = []
    def search(place, period, **kwargs):
        calls.append((place, period))
        return [picture(i) for i in range(25)]
    monkeypatch.setattr(pages, 'search_place_photos', search)
    cache = pages.PhotoPages()
    first = cache.page('owner', 'Chengde', '1980s', None)
    second = cache.page('owner', 'Chengde', '1980s', first['next_cursor'])
    last = cache.page('owner', 'Chengde', '1980s', second['next_cursor'])
    assert len(first['items']) == len(second['items']) == 10 and len(last['items']) == 5
    assert last['next_cursor'] is None and len(calls) == 1
    assert len({item['asset_id'] for item in first['items'] + second['items'] + last['items']}) == 25
    reused=cache.page('owner', 'Chengde', '1980s', None)
    assert reused=={**first,'cached':True}
    for owner, place, period in [('other', 'Chengde', '1980s'), ('owner', 'Kaifeng', '1980s'), ('owner', 'Chengde', '1990s')]:
        with pytest.raises(Exception) as error:
            cache.page(owner, place, period, first['next_cursor'])
        assert error.value.status_code == 422
    for cursor in ['malformed', first['next_cursor'].split(':')[0] + ':-1']:
        with pytest.raises(Exception) as error:
            cache.page('owner', 'Chengde', '1980s', cursor)
        assert error.value.status_code == 422
    monkeypatch.setattr(pages.time, 'monotonic', lambda: 10 ** 15)
    with pytest.raises(Exception) as error:
        cache.page('owner', 'Chengde', '1980s', first['next_cursor'])
    assert error.value.status_code == 410


def test_completed_time_fallback_ranks_capture_year_above_source_diversity(monkeypatch):
    commons = [picture(i, 'commons.wikimedia.org', date_expression='2008') for i in range(49)]
    cse = [picture(i, 'zh.wikipedia.org', date_expression='2010', providers=['google', 'cse'])
           for i in range(9)]
    calls = []

    def search(place, period, **kwargs):
        calls.append(period)
        if period != photos.ANY_PHOTO_DATE:
            return []
        kwargs['on_items'](commons)
        kwargs['on_items'](cse)
        return commons + cse

    monkeypatch.setattr(pages, 'search_place_photos', search)
    cache = pages.PhotoPages()
    try:
        first = cache.page('owner', 'Chengde', '1980s', None)
        assert all(item['date_expression'] == '2008' for item in first['items']), (
            'References closer to the context must outrank newer CSE results')
        found, page = [], first
        while True:
            found.extend(page['items'])
            if not page['next_cursor']:
                break
            page = cache.page('owner', 'Chengde', '1980s', page['next_cursor'])
        assert len(found) == len({item['asset_id'] for item in found}) == 58
        assert all(item['date_expression'] == '2010' for item in found[-9:])
        assert all(item['period_match'] == 'any_time' for item in found)
        assert cache.page('owner', 'Chengde', '1980s', None)['items'] == first['items']
        assert calls == ['1980s', photos.ANY_PHOTO_DATE]
    finally:
        cache.close()


def test_same_decade_photos_prevent_modern_fallback_for_a_birth_month(monkeypatch):
    queries = []
    historical = picture('historical', date_expression='1986')
    def search(place, period, **kwargs):
        queries.append(period)
        return [historical] if period == '1980s' else []
    monkeypatch.setattr(photos, '_search_period', search)
    cache = pages.PhotoPages()
    try:
        result = cache.page('owner', 'Chengde', '1983年4月', None,
            latitude=40.98, longitude=117.94)
        assert queries == ['1983年4月', '1980s']
        assert [item['asset_id'] for item in result['items']] == [historical['asset_id']]
        assert result['items'][0]['period_match'] == 'decade'
        assert result['items'][0]['requested_period'] == '1983年4月'
        assert result['items'][0]['search_fallback'] == 'none'
    finally:
        cache.close()


def test_endpoint_pages_retain_authorization_and_do_not_repeat_discovery(monkeypatch):
    calls = []
    monkeypatch.setattr(pages, 'search_place_photos', lambda *args, **kwargs:
                        calls.append(args) or [picture(i) for i in range(21)])
    client = TestClient(create_app(MemoryStore()))
    headers = {'X-Account-Id': 'owner'}
    project = client.post('/v1/projects', headers=headers, json={'mode': 'self'}).json()
    url = f"/v1/projects/{project['id']}/place-photos"
    params = {'place': 'Chengde', 'period': '1980s', 'latitude': 40.98, 'longitude': 117.94}
    first = client.get(url, headers=headers, params=params).json()
    second = client.get(url, headers=headers, params={**params, 'cursor': first['next_cursor']}).json()
    assert len(first['items']) == len(second['items']) == 10 and first['count'] == 21
    assert len(calls) == 1
    assert client.get(url, headers={'X-Account-Id': 'other'}, params=params).status_code in {403, 404}
