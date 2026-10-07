from fastapi.testclient import TestClient
from io import BytesIO
import math
import random
from threading import Event

from PIL import Image
import pytest

from apps.api import place_photos as photos
from apps.api import place_photo_pages as pages
from apps.api.main import create_app
from apps.api.store import MemoryStore
from apps.api.place_photo_fingerprints import fingerprint_bytes


def picture(identifier, **fields):
    return {
        'asset_id': identifier, 'title': 'Chengde courtyard', 'location': 'Chengde',
        'date_expression': '1983', 'image_url': f'https://images.example/{identifier}.jpg',
        'source_url': f'https://archive.example/{identifier}', 'allowed_actions': {'embed': True},
        **fields,
    }


def test_wikimedia_redirect_revision_and_thumbnail_are_one_photo():
    name = 'Chengde_courtyard.jpg'
    original = picture('original', image_url=f'https://upload.wikimedia.org/wikipedia/commons/a/ab/{name}')
    redirect = picture('redirect', image_url=f'https://commons.wikimedia.org/wiki/Special:FilePath/{name}?width=300')
    revision = picture('revision', image_url=f'https://upload.wikimedia.org/wikipedia/commons/thumb/a/ab/{name}/120px-{name}',
                       source_url='https://zh.wikipedia.org/w/index.php?title=File:Chengde_courtyard.jpg&oldid=123')
    assert photos._deduplicate([original, redirect, revision]) == [original]


def test_period_accepts_only_photographs_within_ten_years():
    assert photos._date_matches('1973', '1983年')
    assert photos._date_matches('1993', '1983年')
    assert not photos._date_matches('1972', '1983年')
    assert not photos._date_matches('1994', '1983年')
    assert not photos._date_matches('', '1983年')
    assert not photos._date_matches('1983-02-30', '1983年')


def test_endpoint_filters_persisted_photos_by_distance_and_year(monkeypatch):
    center = {'latitude': 40.98, 'longitude': 117.94}
    items = [
        picture('near', **center),
        picture('near-year-boundary', date_expression='1973', latitude=41.1, longitude=117.94),
        picture('far', latitude=41.3, longitude=117.94),
        picture('wrong-period', date_expression='2025', **center),
        picture('unknown-location'),
    ]
    monkeypatch.setattr(pages, 'search_place_photos', lambda *args, **kwargs: items)
    with TestClient(create_app(MemoryStore())) as client:
        headers = {'X-Account-Id': 'photo-owner'}
        project = client.post('/v1/projects', headers=headers, json={'mode': 'self'}).json()
        response = client.get(f"/v1/projects/{project['id']}/place-photos", headers=headers,
                              params={'place': 'Chengde', 'period': '1983年', **center})
    assert response.status_code == 200
    assert [item['asset_id'] for item in response.json()['items']] == ['near', 'near-year-boundary']


@pytest.mark.parametrize('coordinates', [
    {'latitude': 40.98}, {'longitude': 117.94},
    {'latitude': 91, 'longitude': 117.94},
    {'latitude': 40.98, 'longitude': 181},
])
def test_endpoint_rejects_incomplete_or_invalid_photo_coordinates(monkeypatch, coordinates):
    monkeypatch.setattr(pages, 'search_place_photos', lambda *args, **kwargs: [])
    with TestClient(create_app(MemoryStore())) as client:
        headers = {'X-Account-Id': 'photo-owner'}
        project = client.post('/v1/projects', headers=headers, json={'mode': 'self'}).json()
        response = client.get(f"/v1/projects/{project['id']}/place-photos", headers=headers,
                              params={'place': 'Chengde', 'period': '1983年', **coordinates})
    assert response.status_code == 422


def test_distance_boundary_invalid_coordinates_and_the_date_line():
    center = {'latitude': 0, 'longitude': 0}
    limit = math.degrees(20 / 6371.0088)
    inside = picture('inside', latitude=limit - 0.000001, longitude=0)
    outside = picture('outside', latitude=limit + 0.000001, longitude=0)
    invalid = picture('invalid', latitude=True, longitude=0)
    assert photos.filter_place_photos([inside, outside, invalid], '1983年', center) == [inside]
    east = picture('east', latitude=0, longitude=-179.99)
    assert photos.filter_place_photos([east], '1983年', {'latitude': 0, 'longitude': 179.99}) == [east]


def test_filtered_pagination_keeps_offsets_counts_and_cursor_scope(monkeypatch):
    calls = []
    center = {'latitude': 40.98, 'longitude': 117.94}
    items = [picture(f'near-{index}', **center) for index in range(25)]
    items += [picture('far', latitude=41.3, longitude=117.94), picture('unknown')]
    items += [picture('revision', image_url=items[0]['image_url'], **center)]
    monkeypatch.setattr(pages, 'search_place_photos', lambda *args, **kwargs: calls.append(args) or items)
    cache = pages.PhotoPages()
    try:
        first = cache.page('owner', 'Chengde', '1983年', None, **center)
        second = cache.page('owner', 'Chengde', '1983年', first['next_cursor'], **center)
        last = cache.page('owner', 'Chengde', '1983年', second['next_cursor'], **center)
        assert first['count'] == 25
        assert [len(page['items']) for page in (first, second, last)] == [10, 10, 5]
        assert last['next_cursor'] is None
        with pytest.raises(Exception) as error:
            cache.page('owner', 'Chengde', '1983年', first['next_cursor'], latitude=41.3, longitude=117.94)
        assert error.value.status_code == 422
        farther = cache.page('owner', 'Chengde', '1983年', None, latitude=41.3, longitude=117.94)
        assert [item['asset_id'] for item in farther['items']] == ['far']
        assert len(calls) == 1
    finally:
        cache.close()


def test_resized_and_recompressed_images_share_a_perceptual_identity():
    rng = random.Random(104)
    image = Image.new('RGB', (160, 120))
    image.putdata([(rng.randrange(256), rng.randrange(256), rng.randrange(256)) for _ in range(160 * 120)])
    def encoded(candidate):
        data = BytesIO()
        candidate.save(data, format='JPEG', quality=92)
        return fingerprint_bytes(data.getvalue())
    original = picture('original', **encoded(image))
    compressed = picture('compressed', **encoded(image.resize((80, 60))))
    assert original['content_hash'] != compressed['content_hash']
    assert photos._deduplicate([original, compressed]) == [original]


def test_wikipedia_revision_dates_do_not_substitute_for_capture_metadata():
    from apps.api import place_photo_browser as browser
    page = ('<title>2025年2月18日 承德照片修订</title>'
            '<meta property="og:image" content="https://upload.wikimedia.org/preview.jpg">'
            '<table class="filehistory"><tr><td>Uploaded on 2025-02-18</td></tr></table>')
    source = 'https://zh.wikipedia.org/w/index.php?title=File:Chengde_courtyard.jpg&oldid=123'
    assert browser._source_items(page, source, 'Chengde', '2025年') == []


def test_a_verified_fingerprint_streams_before_the_remaining_images_finish(monkeypatch):
    release = Event()
    monkeypatch.delenv('GOOGLE_CSE_API_KEY', raising=False)
    monkeypatch.delenv('GOOGLE_CSE_ID', raising=False)
    monkeypatch.delenv('GOOGLE_CSE_URL', raising=False)
    monkeypatch.delenv('FLICKR_API_KEY', raising=False)
    monkeypatch.setattr(photos, '_commons', lambda *args: [picture('early'), picture('later')])
    monkeypatch.setattr(photos, '_loc', lambda *args: [])
    monkeypatch.setattr(photos, '_flickr_browser', lambda *args, **kwargs: [])
    def fingerprint(url):
        if url.endswith('/later.jpg'):
            assert release.wait(1), 'the first verified photo waited for every image fingerprint'
        return {'content_hash': url}
    monkeypatch.setattr('apps.api.place_photo_fingerprints.image_fingerprint', fingerprint)
    received = []
    def publish(items):
        received.extend(items)
        if any(item['asset_id'] == 'early' for item in items):
            release.set()
    assert len(photos.search_place_photos('Chengde', '1980s', on_items=publish)) == 2
    assert received[0]['asset_id'] == 'early'
