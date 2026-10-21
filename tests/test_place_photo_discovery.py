"""Provider routing and source-backed discovery, without live credentials."""
import asyncio
import json
from types import SimpleNamespace

import httpx
import pytest

from apps.api import place_photo_browser as browser
from apps.api import place_photos as photos
from test_place_photo_browser import fake_crawler, photo_html, serpapi_sources


@pytest.mark.parametrize('cse_key', ['', 'old-cse-key'])
@pytest.mark.parametrize('serpapi_unavailable', [False, True])
def test_serpapi_does_not_disable_configured_cse(monkeypatch, cse_key, serpapi_unavailable):
    from threading import Event
    monkeypatch.setenv('SERPAPI_KEY', 'server-only-serpapi')
    monkeypatch.setenv('GOOGLE_CSE_API_KEY', cse_key)
    monkeypatch.setenv('GOOGLE_CSE_ID', 'engine')
    calls = []
    serpapi_started, cse_started = Event(), Event()

    def serpapi(*args, **kwargs):
        calls.append('serpapi')
        serpapi_started.set()
        assert cse_started.wait(1), 'CSE must run alongside SerpAPI'
        if serpapi_unavailable:
            raise photos.PhotoResearchUnavailable('google', 'timeout')
        return []

    monkeypatch.setattr(photos, '_google_serpapi', serpapi)

    def denied(*args, **kwargs):
        calls.append('api')
        request = httpx.Request('GET', photos.GOOGLE_CSE_ENDPOINT)
        response = httpx.Response(403, request=request)
        raise httpx.HTTPStatusError('Denied', request=request, response=response)

    def public_engine(*args, **kwargs):
        calls.append('cse')
        cse_started.set()
        assert serpapi_started.wait(1)
        return [{**item, 'providers': ['google', 'cse']} for item in browser._source_items(
            photo_html(licence='https://creativecommons.org/licenses/by/4.0/'),
            'https://archive.example/photo', 'Chengde', '1980s')]

    monkeypatch.setattr(photos, '_google_cse', denied)
    monkeypatch.setattr(photos, '_google_browser', public_engine)
    monkeypatch.setattr('apps.api.place_photo_fingerprints.image_fingerprint', lambda url: {})
    for name in ('_commons', '_loc', '_flickr_browser', '_flickr'):
        monkeypatch.setattr(photos, name, lambda *a, **k: [])
    found = photos.search_place_photos('Chengde', '1980s')
    assert len(found) == 1, 'A configured CSE result was lost when SerpAPI was enabled'
    assert found[0]['providers'] == ['google', 'cse']
    assert sorted(calls) == sorted(['serpapi', 'cse', *(['api'] if cse_key else [])])


def test_cse_api_access_denial_falls_back_to_the_public_engine(monkeypatch):
    monkeypatch.delenv('SERPAPI_KEY', raising=False)
    monkeypatch.setenv('GOOGLE_CSE_API_KEY', 'server-only-cse')
    monkeypatch.setenv('GOOGLE_CSE_ID', 'engine')
    calls = []

    def denied(*args, **kwargs):
        calls.append('api')
        request = httpx.Request('GET', photos.GOOGLE_CSE_ENDPOINT)
        response = httpx.Response(403, request=request)
        raise httpx.HTTPStatusError('Denied', request=request, response=response)

    def public_engine(*args, **kwargs):
        calls.append('browser')
        return browser._source_items(photo_html(licence='https://creativecommons.org/licenses/by/4.0/'),
                                     'https://archive.example/photo', 'Chengde', '1980s')

    monkeypatch.setattr(photos, '_google_cse', denied)
    monkeypatch.setattr(photos, '_google_browser', public_engine)
    monkeypatch.setattr('apps.api.place_photo_fingerprints.image_fingerprint', lambda url: {})
    for name in ('_commons', '_loc', '_flickr_browser', '_flickr'):
        monkeypatch.setattr(photos, name, lambda *a, **k: [])
    assert len(photos.search_place_photos('Chengde', '1980s')) == 1
    assert calls == ['api', 'browser']


@pytest.mark.parametrize('markup', [
    '<div class="gsc-control-cse">Loading</div>',
    '<div class="gs-error">Search unavailable</div>',
])
def test_unrendered_or_failed_cse_widget_is_retryable(fake_crawler, markup):
    pages, _, _ = fake_crawler
    url = 'https://cse.google.com/cse?cx=engine'
    pages[url] = markup
    with pytest.raises(photos.PhotoResearchUnavailable) as error:
        asyncio.run(browser._browse_query('google', 'Chengde', '1980s', url))
    assert error.value.failures[0]['reason'] in {'widget_not_ready', 'search_error'}


def test_completed_empty_cse_widget_is_a_real_no_match(fake_crawler):
    pages, _, _ = fake_crawler
    url = 'https://cse.google.com/cse?cx=engine'
    pages[url] = '<div class="gs-no-results-result">No results</div>'
    assert asyncio.run(browser._browse_query('google', 'Chengde', '1980s', url)) == []


@pytest.mark.parametrize('later_healthy', [False, True])
def test_blocked_original_does_not_hide_later_cse_pages(monkeypatch, fake_crawler, later_healthy):
    from test_place_photo_browser import cse_html
    monkeypatch.setattr('apps.api.place_photo_fingerprints.image_fingerprint', lambda url: {})
    search = 'https://cse.google.com/cse?cx=engine'
    blocked, healthy = 'https://blocked.example/photo', 'https://archive.example/photo'
    visits = []

    class Crawler:
        crawler_strategy = SimpleNamespace(set_hook=lambda *args: None)

        async def arun(self, url, config):
            visits.append(url)
            if url == search:
                source = healthy if later_healthy and visits.count(search) > 1 else blocked
                return SimpleNamespace(success=True, html=cse_html([source]))
            if url == blocked:
                return SimpleNamespace(success=False, status_code=403,
                                       response_headers={'X-Robots-Status': 'Disallowed'})
            assert url == healthy
            return SimpleNamespace(success=True, html=photo_html())

    def browse():
        return asyncio.run(browser._browse_query('google', 'Chengde', '1980s', search,
            limit=1, page_budget=2, crawler=Crawler()))

    if later_healthy:
        found = browse()
        assert len(found) == 1 and found[0]['source_url'] == healthy
    else:
        with pytest.raises(photos.PhotoResearchUnavailable) as error:
            browse()
        assert error.value.failures == [{'provider': 'google', 'reason': 'robots_denied', 'scope': 'source'}]
    assert visits.count(search) == 2
    assert visits.count(blocked) == 1, 'A source robots denial must never be retried'


def test_chengde_discovery_uses_google_archives_and_baidu_after_images(monkeypatch, serpapi_sources):
    import subprocess
    _, sources, _, fetched = serpapi_sources
    monkeypatch.delenv('MEMOIR_PHOTO_EXPANSION', raising=False)
    monkeypatch.setattr('apps.api.place_photo_fingerprints.image_fingerprint', lambda url: {})
    searches = []
    for index, host in enumerate(('www.cddaw.cn', 'archive.example'), 1):
        sources[f'https://{host}/photo/{index}'] = photo_html(
            index, licence='https://creativecommons.org/licenses/by/4.0/')

    def search(command, **kwargs):
        payload = json.loads(kwargs['input'])
        engine = payload.get('engine', 'google_images')
        searches.append(payload)
        source = {'google': 'https://www.cddaw.cn/photo/1',
                  'baidu': 'https://archive.example/photo/2'}.get(engine)
        # Result snippets deliberately contain no place/date evidence.
        cards = [{'source_url': source, 'text': 'Archive record'}] if source else []
        return SimpleNamespace(stdout='PLACE_PHOTO_RESULT:' + json.dumps({'status': 'success', 'cards': cards}))

    monkeypatch.setattr(subprocess, 'run', search)
    found = photos._google_serpapi('Chengde', '1980s')
    assert len(found) == 2
    assert [item['engine'] for item in searches] == ['google_images', 'google', 'baidu']
    assert 'site:cddaw.cn' in searches[1]['query']
    assert '承德' in searches[2]['query']
    assert all(item['source_url'] in fetched for item in found)
    assert all(item['date_expression'] == '1983-10-01' for item in found)


def test_unknown_rights_are_leads_without_app_or_publication_permission():
    item = browser._source_items(photo_html(licence=None), 'https://archive.example/photo', 'Chengde', '1980s')[0]
    assert item['usage_permissions'] == {
        'app_display': 'needs_permission', 'ebook': 'needs_review',
        'print': 'needs_review', 'game': 'needs_review',
    }
    assert item['allowed_actions']['embed'] is False
    assert photos.filter_place_photos([item], '1980s') == []


def test_commons_source_uses_file_licence_separately_from_website_footer():
    source = 'https://commons.wikimedia.org/wiki/File:Chengde_street.jpg'
    markup = (photo_html(licence=None)
              + '<span class="licensetpl_link">https://creativecommons.org/licenses/by/3.0/</span>'
              + '<footer><a href="https://creativecommons.org/licenses/by-sa/4.0/">Page text</a></footer>')
    item = browser._source_items(markup, source, 'Chengde', '1980s')[0]
    assert item['license_url'] == 'https://creativecommons.org/licenses/by/3.0/'
    assert item['allowed_actions']['embed']
    without_file_licence = markup.replace('<span class="licensetpl_link">https://creativecommons.org/licenses/by/3.0/</span>', '')
    assert not browser._source_items(without_file_licence, source, 'Chengde', '1980s')[0]['allowed_actions']['embed']


def test_commons_keeps_original_dimensions_and_licence_but_rejects_upload_date(monkeypatch):
    from test_place_workspace import photo_page
    page = photo_page(1, date='')
    info = page['imageinfo'][0]
    info.update(timestamp='1983-10-01T00:00:00Z', width=1200, height=800,
                url='https://upload.wikimedia.org/wikipedia/commons/original.jpg')
    info['extmetadata'].update(LicenseShortName={'value': 'CC BY 3.0'},
                               LicenseUrl={'value': 'https://creativecommons.org/licenses/by/3.0/'})
    monkeypatch.setattr(photos, '_get', lambda *a: {'query': {'pages': {'1': page}}})
    assert photos._commons('Chengde', '1980s') == []
    info['extmetadata']['DateTimeOriginal']['value'] = '1983-10-01'
    item = photos._commons('Chengde', '1980s')[0]
    assert (item['width'], item['height']) == (1200, 800)
    assert item['usage_permissions']['app_display'] == 'permitted'
    assert item['date_basis'] == 'original_exif'


def test_chinese_sydney_search_discovers_and_accepts_english_catalogue_records(monkeypatch):
    from test_place_workspace import photo_page
    page = photo_page(1, date=photos.datetime.now(photos.ZoneInfo('Australia/Sydney')).date().isoformat())
    page['title'] = 'File:Sydney Harbour.jpg'
    page['imageinfo'][0]['extmetadata']['ImageDescription'] = {'value': 'Sydney Harbour, Australia'}
    queries = []
    def catalogue(url, params):
        queries.append(params['gsrsearch'])
        return {'query': {'pages': {'1': page}}} if 'Sydney' in params['gsrsearch'] else {}
    monkeypatch.setattr(photos, '_get', catalogue)
    items = photos._commons('悉尼', '')
    assert len(photos._deduplicate(items)) == 1
    assert any('Sydney' in query for query in queries)
    assert items[0]['allowed_actions']['embed'] is True
    assert photos._location_matches('Sydney Harbour, Australia', '悉尼')


@pytest.mark.parametrize('host,expected', [('thumb.wikimedia.org', 1), ('thumb.wikimedia.org.example', 0)])
def test_commons_accepts_its_thumbnail_host_without_trusting_lookalikes(monkeypatch, host, expected):
    from test_place_workspace import photo_page
    page = photo_page(1)
    page['imageinfo'][0]['thumburl'] = f'https://{host}/wikipedia/commons/thumb/street.jpg'
    monkeypatch.setattr(photos, '_get', lambda *a: {'query': {'pages': {'1': page}}})
    assert len(photos._deduplicate(photos._commons('Chengde', '1980s'))) == expected
