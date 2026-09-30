from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient
import pytest

from apps.api import place_photos as photos
from apps.api import place_photo_pages as pages
from apps.api.main import create_app
from apps.api.store import MemoryStore


def picture(index, host='archive.example', **fields):
    return {'asset_id': f'{host}-{index}', 'title': 'Chengde street', 'location': 'Chengde',
            'date_expression': '1983', 'image_url': f'https://images.{host}/{index}.jpg',
            'source_url': f'https://{host}/{index}', 'allowed_actions': {'embed': True}, **fields}


def test_pool_filters_place_period_and_interleaves_original_sources(monkeypatch):
    monkeypatch.delenv('GOOGLE_CSE_API_KEY', raising=False)
    monkeypatch.setenv('GOOGLE_CSE_ID', 'engine')
    monkeypatch.delenv('FLICKR_API_KEY', raising=False)
    monkeypatch.setattr(photos, '_flickr_browser', lambda *args: [picture(i, 'flickr.com') for i in range(20)])
    monkeypatch.setattr(photos, '_google_browser', lambda *args: [picture(i, 'archive.example') for i in range(20)])
    monkeypatch.setattr(photos, '_commons', lambda *args: [picture(i, 'commons.wikimedia.org') for i in range(20)])
    monkeypatch.setattr(photos, '_loc', lambda *args: [picture(1, 'loc.gov'),
        picture(2, 'loc.gov', title='Chengdu street'), picture(3, 'loc.gov', date_expression='1990'),
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


def test_google_webpage_dates_cannot_date_a_photo():
    result = {'title': 'Chengde street', 'pagemap': {'metatags': [
        {'datePublished': '1983', 'dateModified': '1983', 'uploadDate': '1983'}]}}
    assert photos._google_date(result, '1980s') is None


def test_deduplication_matches_flickr_sizes_commons_thumbnails_and_hashes():
    original = picture(1, image_url='https://live.staticflickr.com/12/123_secret_z.jpg')
    larger = picture(2, 'other.example', image_url='https://farm4.staticflickr.com/12/123_secret_b.jpg?utm_source=google')
    commons = picture(3, image_url='https://upload.wikimedia.org/wikipedia/commons/thumb/a/ab/Street.jpg/640px-Street.jpg')
    commons_original = picture(4, 'other.example', image_url='https://upload.wikimedia.org/wikipedia/commons/a/ab/Street.jpg')
    hashed = picture(5, content_hash='verified-hash')
    rehosted = picture(6, 'rehost.example', content_hash='verified-hash')
    assert photos._deduplicate([original, larger, commons, commons_original, hashed, rehosted]) == [original, commons, hashed]
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
    assert cache.page('owner', 'Chengde', '1980s', None) == first
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


def test_endpoint_pages_retain_authorization_and_do_not_repeat_discovery(monkeypatch):
    calls = []
    monkeypatch.setattr(pages, 'search_place_photos', lambda *args, **kwargs:
                        calls.append(args) or [picture(i) for i in range(21)])
    client = TestClient(create_app(MemoryStore()))
    headers = {'X-Account-Id': 'owner'}
    project = client.post('/v1/projects', headers=headers, json={'mode': 'self'}).json()
    url = f"/v1/projects/{project['id']}/place-photos"
    params = {'place': 'Chengde', 'period': '1980s'}
    first = client.get(url, headers=headers, params=params).json()
    second = client.get(url, headers=headers, params={**params, 'cursor': first['next_cursor']}).json()
    assert len(first['items']) == len(second['items']) == 10 and first['count'] == 21
    assert len(calls) == 1
    assert client.get(url, headers={'X-Account-Id': 'other'}, params=params).status_code in {403, 404}
