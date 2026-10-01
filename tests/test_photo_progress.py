import asyncio
import json
import threading

from apps.api import place_photo_pages as pages


def picture(index):
    return {'asset_id': str(index), 'image_url': f'https://images.example/{index}.jpg',
            'source_url': f'https://archive.example/{index}', 'title': 'Chengde street',
            'date_expression': '1983', 'allowed_actions': {'embed': True}}


def test_first_photos_stream_before_completion_and_shared_search_keeps_cursors_owned(monkeypatch):
    release = threading.Event()
    calls = []
    def search(place, period, *, on_items, **kwargs):
        calls.append((place, period))
        on_items([picture(1)])
        assert release.wait(3)
        return [picture(i) for i in range(1, 23)]
    monkeypatch.setattr(pages, 'search_place_photos', search)
    cache = pages.PhotoPages()
    async def check():
        stream = cache.stream('alice', 'Chengde', '1980s', None)
        try:
            assert json.loads(await anext(stream))['searching']
            partial = json.loads(await asyncio.wait_for(anext(stream), 1))
            assert len(partial['items']) == 1 and partial['searching']
            release.set()
            final = partial
            async for line in stream:
                final = json.loads(line)
            assert not final['searching'] and len(final['items']) == 10
            second = cache.page('bob', 'chengde', '1980s', None)
            assert len(calls) == 1, 'A second project reran public research'
            assert second['next_cursor'] != final['next_cursor']
            assert cache.page('alice', 'Chengde', '1980s', final['next_cursor'])['items'][0]['asset_id'] == '11'
            try:
                cache.page('bob', 'Chengde', '1980s', final['next_cursor'])
            except Exception as error:
                assert error.status_code == 422
            else:
                raise AssertionError('A cursor crossed project ownership')
        finally:
            release.set()
            await stream.aclose()
    try:
        asyncio.run(check())
    finally:
        release.set()
        cache.close()


def test_a_failed_empty_search_can_be_retried_immediately(monkeypatch):
    calls = []
    def search(*args, **kwargs):
        calls.append(True)
        if len(calls) == 1:
            raise ValueError('unavailable')
        return [picture(1)]
    monkeypatch.setattr(pages, 'search_place_photos', search)
    cache = pages.PhotoPages()
    try:
        assert cache.page('alice', 'Chengde', '1980s', None)['status'] == 'UNAVAILABLE'
        assert cache.page('alice', 'Chengde', '1980s', None)['items']
        assert len(calls) == 2
    finally:
        cache.close()
