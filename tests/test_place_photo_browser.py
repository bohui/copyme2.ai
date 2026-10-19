import asyncio
import json
from datetime import datetime
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit
from zoneinfo import ZoneInfo

import pytest
import httpx

from apps.api import place_photo_browser as browser
from apps.api import place_photos as photos


def photo_html(index=1, *, date='1983-10-01', place='Chengde', licence='https://creativecommons.org/licenses/by/4.0/'):
    record = {'@type': 'Photograph', 'name': f'{place} street', 'dateCreated': date,
              'contentLocation': {'geo': {'latitude': 40.98, 'longitude': 117.94}},
              'contentUrl': f'https://live.staticflickr.com/1/{index}.jpg',
              'creator': {'name': 'Photographer'}}
    if licence:
        record['license'] = licence
    return (f'<title>{place} street</title><meta property="og:title" content="{place} street">'
            f'<script type="application/ld+json">{json.dumps(record)}</script>')


def cse_html(sources):
    return ''.join(f'<div class="gsc-imageResult gsc-result">'
                   f'<a class="gs-previewLink" href="{url}">Chengde 1983</a>'
                   f'<img class="gs-image" src="https://encrypted-tbn0.gstatic.com/preview-{i}">'
                   f'<div class="gs-previewTitle">Chengde street 1983</div></div>'
                   for i, url in enumerate(sources))


def test_chengde_palace_query_expands_verified_names_without_losing_period():
    query = photos._google_query('离宫, 承德市', '1983年', include_decade=True)
    for term in ('离宫', '避暑山庄', 'Mountain Resort', 'summer palace', '承德', 'Chengde', '1983', '80年代', '80s'):
        assert f'"{term}"' in query
    assert ') (' in query, 'landmark, city and date must be separate required groups'


@pytest.mark.parametrize('caption,expected', [
    ('承德避暑山庄 1983', True), ('Chengde Mountain Resort 1983', True),
    ('Chengde summer palace 1983', True), ('Beijing Summer Palace 1983', False),
    ('承德街景 1983', False), ('Summer Palace 1983', False),
])
def test_palace_alias_matches_require_the_landmark_and_city(caption, expected):
    assert photos._location_matches(caption, '离宫, 承德市') is expected
    assert browser._research()._crawl4ai_location_matches(caption, '离宫, 承德市') is expected


@pytest.mark.parametrize('period', ['1980s', '1980年代', '1980-1989'])
def test_decade_discovery_includes_the_local_keyword_used_by_source_pages(period):
    query = photos._google_query('承德市', period, include_decade=True)
    for term in ('80年代', '80s', '1980年代', '1980s'):
        assert f'"{term}"' in query
    assert '1980' in query and '1989' in query


def test_flickr_context_links_are_canonical_photo_discovery_leads():
    page = ('<a href="/photos/kattebelletje/3330975589/in/photostream/">National Day</a>'
            '<a href="/photos/kattebelletje/3330975589/in/album-72157614775600805/">Same photo</a>'
            '<a href="/photos/kattebelletje/albums/72157614775600805/">Album</a>')
    cards = browser._flickr_cards(page, 'https://www.flickr.com/search/')
    assert len(cards) == 1
    assert cards[0]['source_url'] == 'https://www.flickr.com/photos/kattebelletje/3330975589/'


def test_flickr_source_reads_item_tags_album_and_capture_date_without_using_upload_date():
    # Rendered Flickr fields, with an eligible licence so location/date parsing
    # is tested separately from the linked photographer's noncommercial rights.
    page = ('<title>National Day, October 1, 1983</title>'
            '<meta property="og:description" content="903">'
            '<meta property="og:image" content="https://live.staticflickr.com/1/street.jpg">'
            '<p>Uploaded on March 5, 2009 Taken in October 1983</p>'
            '<a href="/photos/kattebelletje/albums/72157614775600805">Chengde 承德 1983</a>'
            '<a href="/photos/tags/承德">承德</a>'
            '<a href="/photos/tags/避暑山庄">避暑山庄</a>'
            '<a href="https://creativecommons.org/licenses/by/2.0/deed.en">Some rights reserved</a>')
    source = 'https://www.flickr.com/photos/kattebelletje/3330975589/'
    found = browser._source_items(page, source, '离宫, 承德市', '1980s')
    assert len(found) == 1
    assert found[0]['date_expression'] == 'October 1983'
    assert '承德' in found[0]['location_evidence']
    assert found[0]['license_url'] == 'https://creativecommons.org/licenses/by/2.0/deed.en'
    assert not browser._source_items(page.replace('/by/2.0/', '/by-nc/2.0/'), source, '离宫, 承德市', '1980s')
    assert not browser._source_items(page, source, 'Chengdu', '1980s')
    undated = page.replace('National Day, October 1, 1983', 'National Day').replace('Taken in October 1983', '')
    assert not browser._source_items(undated, source, '离宫, 承德市', '1980s')


def test_generic_palace_name_without_chengde_context_is_not_reinterpreted():
    assert '避暑山庄' not in photos._google_query('离宫, 北京', '1983年')


def test_alias_source_photos_still_require_the_memory_capture_period():
    place = '离宫, 承德市'
    source = 'https://www.flickr.com/photos/author/1/'
    assert browser._source_items(photo_html(place='Chengde Mountain Resort'), source, place, '1983年')
    assert not browser._source_items(photo_html(place='Beijing Summer Palace'), source, place, '1983年')
    assert not browser._source_items(photo_html(place='Chengde Mountain Resort', date='1994-01-01'), source, place, '1983年')


@pytest.mark.parametrize('period,date', [('1980s', '1983-10-01'), ('', '2025-11-03')])
def test_google_source_extracts_item_capture_dates_without_dating_the_whole_page(period, date):
    page = ('<title>Chengde Mountain Resort photo collection</title>'
            f'<figure><img src="https://archive.example/scene.jpg" alt="Chengde Mountain Resort {date}">'
            f'<figcaption>Chengde Mountain Resort, photographed on {date}</figcaption></figure>')
    items = browser._source_items(page, 'https://archive.example/chengde', '离宫, 承德市', period)
    assert len(items) == 1, 'image-specific capture metadata was discarded because the page title has no date'


def test_google_source_reads_explicit_sibling_captions_not_article_dates():
    page = ('<title>承德建筑新变化</title><p>发表于2019年12月26日</p>'
            '<div class="img-para"><img src="https://archive.example/old.jpg"></div>'
            '<p class="img-desc">八十年代承德全景图。承德市档案馆供图</p>'
            '<div class="img-para"><img src="https://archive.example/new.jpg"></div>'
            '<p class="img-desc">2019年承德市全景。记者摄</p>'
            '<img src="https://archive.example/uncaptioned.jpg"><p>文章讨论1983年的承德</p>')
    items = browser._source_items(page, 'https://archive.example/chengde', '承德市', '1980s')
    assert [item['image_url'] for item in items] == ['https://archive.example/old.jpg']
    assert items[0]['date_expression'] == '1980-1989'


@pytest.mark.parametrize('licences,expected', [
    ((None, 'https://creativecommons.org/licenses/by/4.0/'), (False, True)),
    (('https://creativecommons.org/licenses/by/4.0/', None), (True, False)),
])
def test_json_ld_sibling_licences_are_evaluated_per_image(licences, expected):
    records = []
    for index, licence in enumerate(licences, 1):
        record = {'@type': 'Photograph', 'name': f'Chengde street {index}',
                  'dateTaken': '1983-10-01',
                  'contentUrl': f'https://archive.example/photo-{index}.jpg'}
        if licence:
            record['license'] = licence
        records.append(record)
    page = ('<title>Chengde photo gallery</title>'
            '<script type="application/ld+json">'
            + json.dumps({'@graph': records})
            + '</script>')

    items = browser._source_items(page, 'https://archive.example/chengde', 'Chengde', '1980s')
    by_url = {item['image_url']: item for item in items}
    assert tuple(by_url[f'https://archive.example/photo-{index}.jpg']['allowed_actions']['embed']
                 for index in (1, 2)) == expected


def test_separated_caption_does_not_date_a_previous_unrelated_image():
    page = ('<title>Chengde archive</title><img src="https://archive.example/logo.jpg">'
            '<p>Navigation and unrelated text</p><p class="img-desc">Chengde 1983</p>')
    assert not browser._source_items(page, 'https://archive.example/chengde', 'Chengde', '1980s')


@pytest.fixture
def serpapi_sources(monkeypatch):
    import subprocess
    data = {'status': 'success', 'cards': []}
    sources, searches, fetched = {}, [], []
    def run(command, **kwargs):
        searches.append((command, kwargs))
        return SimpleNamespace(stdout='PLACE_PHOTO_RESULT:' + json.dumps(data))
    def fetch(self, url, size, hosts, **kwargs):
        fetched.append(url)
        value = sources[url]
        if isinstance(value, Exception):
            raise value
        return 200, url, {'content-type': 'text/html; charset=utf-8'}, value.encode()
    monkeypatch.setattr(subprocess, 'run', run)
    monkeypatch.setattr(browser._research(), 'public_addresses', lambda *args: ['8.8.8.8'])
    monkeypatch.setattr(browser._research().Fetcher, 'fetch', fetch)
    monkeypatch.setattr('apps.api.place_photo_fingerprints.image_fingerprint', lambda url: {})
    return data, sources, searches, fetched


def test_google_images_inspects_originals_deduplicates_and_ignores_preview_dates(serpapi_sources):
    data, sources, searches, fetched = serpapi_sources
    for index, date in enumerate(('1983-10-01', '2025-11-03', ''), 1):
        url = f'https://archive.example/photo/{index}'
        data['cards'].append({'source_url': url, 'text': 'Chengde 1983',
                              'image_url': 'https://encrypted-tbn0.gstatic.com/preview'})
        sources[url] = photo_html(index, date=date)
    data['cards'].append(data['cards'][0])
    items = photos._google_serpapi('Chengde', '1980s')
    assert [item['image_url'] for item in items] == ['https://live.staticflickr.com/1/1.jpg']
    assert items[0]['providers'] == ['google', 'serpapi']
    assert len(fetched) == 3
    command, options = searches[0]
    assert command[-2:] == ['worker', 'serpapi']
    assert json.loads(options['input'])['refresh'] is True
    query = json.loads(options['input'])['query']
    assert '1980年代 老照片' in query
    assert '"1981" OR' not in query


def test_google_images_keeps_verified_siblings_when_a_source_is_blocked(serpapi_sources):
    data, sources, _, _ = serpapi_sources
    for index in range(2):
        url = f'https://archive.example/photo/{index}'
        data['cards'].append({'source_url': url, 'text': 'Chengde'})
        sources[url] = browser._research().ResearchError('robots.txt disallows this URL') if index else photo_html()
    assert len(photos._google_serpapi('Chengde', '1980s')) == 1
    sources['https://archive.example/photo/0'] = OSError('source down')
    with pytest.raises(photos.PhotoResearchUnavailable) as error:
        photos._google_serpapi('Chengde', '1980s')
    assert error.value.failures == [{'provider': 'google', 'reason': 'source_unavailable'}]


@pytest.mark.parametrize('response', [[], {'status': 'success', 'cards': None},
                                    {'status': 'error', 'error': 'private-key-in-provider-error'}])
def test_google_images_provider_failures_are_safe(serpapi_sources, response):
    import subprocess
    from unittest.mock import patch
    with patch.object(subprocess, 'run', return_value=SimpleNamespace(
            stdout='PLACE_PHOTO_RESULT:' + json.dumps(response))):
        with pytest.raises(photos.PhotoResearchUnavailable) as error:
            photos._google_serpapi('Chengde', '1980s')
    assert error.value.failures[0]['reason'] in {'invalid_response', 'unavailable'}
    assert 'private-key' not in str(error.value)


@pytest.mark.parametrize('capture_date,expected', [('3 November 2025', True), ('3 November 1983', False), ('', False)])
def test_mediawiki_uses_file_capture_date_and_original_not_upload_history(capture_date, expected):
    page = ('<title>File:Chengde Mountain Resort courtyard.jpg</title>'
            '<meta property="og:image" content="https://upload.wikimedia.org/preview.jpg">'
            '<a href="https://upload.wikimedia.org/original.jpg">Original file</a>'
            f'<table><tr><td id="fileinfotpl_date">Date</td><td>{capture_date}</td></tr></table>'
            '<table class="filehistory"><tr><td>Uploaded on 2025-11-03</td></tr></table>')
    items = browser._source_items(page, 'https://commons.wikimedia.org/wiki/File:Chengde_courtyard.jpg',
                                  '离宫, 承德市', '')
    assert bool(items) is expected
    if expected:
        assert items[0]['image_url'] == 'https://upload.wikimedia.org/original.jpg'
        assert items[0]['date_expression'] == '2025-11-03'


@pytest.fixture
def fake_crawler(monkeypatch):
    monkeypatch.setattr('apps.api.place_photo_fingerprints.image_fingerprint', lambda url: {})
    pages, calls, hooks = {}, [], {}
    class Config:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)
    class Crawler:
        def __init__(self, **kwargs):
            self.crawler_strategy = SimpleNamespace(set_hook=lambda name, hook: hooks.update({name: hook}),
                browser_manager=SimpleNamespace(contexts_by_config={}, sessions={}))
        async def start(self):
            return self
        async def close(self):
            pass
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            pass
        async def arun(self, url, config):
            calls.append((url, config))
            value = pages.get(url, '')
            if isinstance(value, Exception):
                raise value
            return SimpleNamespace(success=bool(value), html=value, status_code=200 if value else 403)
    monkeypatch.setitem(__import__('sys').modules, 'crawl4ai', SimpleNamespace(
        AsyncWebCrawler=Crawler, BrowserConfig=Config, CrawlerRunConfig=Config,
        CacheMode=SimpleNamespace(BYPASS='bypass'),
    ))
    monkeypatch.setattr(browser._research(), 'public_addresses', lambda *args: ['8.8.8.8'])
    return pages, calls, hooks


def test_missing_keys_select_both_browser_providers_and_reach_endpoint(monkeypatch):
    from fastapi.testclient import TestClient
    from apps.api.main import create_app
    from apps.api.store import MemoryStore
    monkeypatch.setenv('GOOGLE_CSE_ID', 'my-engine')
    monkeypatch.setenv('GOOGLE_CSE_API_KEY', '<null>')
    monkeypatch.delenv('FLICKR_API_KEY', raising=False)
    calls = []
    def crawl(provider, place, period, **kwargs):
        calls.append((provider, place, period))
        return browser._source_items(photo_html(1 if provider == 'google' else 2),
                                     f'https://www.flickr.com/photos/author/{provider}/', place, period)
    monkeypatch.setattr(browser, 'crawl_place_photos', crawl)
    monkeypatch.setattr(photos, '_commons', lambda *args: [])
    monkeypatch.setattr(photos, '_loc', lambda *args: [])
    monkeypatch.setattr(photos, '_google_cse', lambda *args: pytest.fail('unexpected Google API call'))
    monkeypatch.setattr(photos, '_flickr', lambda *args: pytest.fail('unexpected Flickr API call'))
    client = TestClient(create_app(MemoryStore()))
    headers = {'X-Account-Id': 'browser-owner'}
    project = client.post('/v1/projects', headers=headers, json={'mode': 'self'}).json()
    result = client.get(f"/v1/projects/{project['id']}/place-photos", headers=headers,
                        params={'place': 'Chengde', 'period': '1980s', 'latitude': 40.98, 'longitude': 117.94}).json()
    assert result['status'] == 'PARTIAL' and len(result['items']) == 2
    assert sorted(calls) == [('flickr', 'Chengde', '1980s'), ('google', 'Chengde', '1980s')]
    assert all(item['allowed_actions']['embed'] for item in result['items'])


def test_keys_keep_existing_api_providers(monkeypatch):
    monkeypatch.setenv('GOOGLE_CSE_ID', 'engine')
    monkeypatch.setenv('GOOGLE_CSE_API_KEY', 'configured')
    monkeypatch.setenv('FLICKR_API_KEY', 'configured')
    calls = []
    for name in ('_google_cse', '_flickr', '_commons', '_loc'):
        monkeypatch.setattr(photos, name, lambda *args, name=name, **kwargs: calls.append(name) or [])
    monkeypatch.setattr(browser, 'crawl_place_photos', lambda *args, **kwargs: pytest.fail('unexpected browser'))
    assert photos.search_place_photos('Chengde', '1980s') == []
    assert set(calls) == {'_google_cse', '_flickr', '_commons', '_loc'}


def test_configured_google_images_key_reaches_the_app_provider(monkeypatch):
    monkeypatch.setenv('SERPAPI_KEY', 'private-key')
    monkeypatch.delenv('GOOGLE_CSE_API_KEY', raising=False)
    monkeypatch.setenv('GOOGLE_CSE_ID', 'engine')
    monkeypatch.delenv('MEMORY_SPARK_PHOTO_WEB_SEARCH', raising=False)
    calls = []
    def search(place, period, **kwargs):
        calls.append((place, period))
        return browser._source_items(photo_html(), 'https://archive.example/photo', place, period)
    monkeypatch.setattr(photos, '_google_serpapi', search, raising=False)
    monkeypatch.setattr(photos, '_google_browser', lambda *args: calls.append(('cse', *args)) or [])
    for name in ('_flickr_browser', '_flickr', '_commons', '_loc'):
        monkeypatch.setattr(photos, name, lambda *args: [])
    monkeypatch.setattr('apps.api.place_photo_fingerprints.image_fingerprint', lambda url: {})
    found = photos.search_place_photos('Chengde', '1980s')
    assert len(found) == 1
    assert set(calls) == {('Chengde', '1980s'), ('cse', 'Chengde', '1980s')}


def test_cse_url_and_id_have_same_query_without_page_date_filter(monkeypatch):
    monkeypatch.setenv('GOOGLE_CSE_ID', 'engine')
    monkeypatch.delenv('GOOGLE_CSE_URL', raising=False)
    query = parse_qs(urlsplit(browser._search_url('google', '承德', '1980')).query)
    assert query['cx'] == ['engine'] and query['q'] == [photos._google_query('承德', '1980', include_decade=True)]
    assert 'sort' not in query
    monkeypatch.setenv('GOOGLE_CSE_URL', 'https://cse.google.com/cse?cx=url-engine&page=9')
    query = parse_qs(urlsplit(browser._search_url('google', '承德', '')).query)
    assert query['cx'] == ['url-engine'] and 'page' not in query and '老照片' not in query['q'][0]
    monkeypatch.setenv('GOOGLE_CSE_URL', 'http://localhost/cse?cx=engine')
    with pytest.raises(ValueError):
        browser._search_url('google', '承德', '')


@pytest.mark.parametrize('place,period', [('承德', '1980s'), ('Chengde', ''), ('Chengdu', '1983年')])
def test_google_or_query_is_one_search_and_preserves_place_and_period(monkeypatch, place, period):
    monkeypatch.setenv('GOOGLE_CSE_ID', 'engine')
    monkeypatch.delenv('GOOGLE_CSE_URL', raising=False)
    url = browser._search_url('google', place, period)
    query = parse_qs(urlsplit(url).query)['q'][0]
    assert browser._discovery_queries('google', place, period, url) == [(url, False)]
    if place == '承德':
        assert query.startswith('("承德" OR "Chengde") (')
        assert all(f'"{year}"' in query for year in range(1980, 1990))
        assert '"80年代"' in query
    elif place == 'Chengde':
        current = browser._research().normalize_period(None, datetime.now(ZoneInfo('Australia/Sydney')).date())
        years = ' OR '.join(str(year) for year in range(int(current['start'][:4]), int(current['end'][:4]) + 1))
        assert query == f'("Chengde" OR "承德") ({years})'
    else:
        years = ' OR '.join(f'"{year}"' for year in range(1973, 1994))
        assert query == f'("Chengdu") ({years} OR "80年代" OR "80s" OR "1980年代" OR "1980s")'


def test_cse_reads_originals_deduplicates_and_checks_source_robots(fake_crawler):
    pages, calls, hooks = fake_crawler
    search = 'https://cse.google.com/cse?cx=engine'
    source = 'https://www.flickr.com/photos/author/1/'
    pages[search] = cse_html([source, source, 'http://localhost/private'])
    pages[source] = photo_html()
    result = asyncio.run(browser._browse('google', 'Chengde', '1980s', search))
    assert len(result) == 1
    assert result[0]['image_url'] == 'https://live.staticflickr.com/1/1.jpg'
    assert result[0]['source_url'] == source and result[0]['memory_reference_only']
    assert result[0]['license'] == 'CC BY'
    assert result[0]['allowed_actions'] == {'embed': True, 'memory_reference': True,
                                         'download': False, 'print': False, 'publish': False}
    assert all(config.check_robots_txt for url, config in calls if 'cse.google.com' not in url)
    assert len([url for url, _ in calls if url == source]) == 1
    assert not any('localhost' in url for url, _ in calls)
    assert 'on_page_context_created' in hooks


def test_flickr_browses_public_search_and_ignores_upload_date(fake_crawler):
    pages, calls, _ = fake_crawler
    search = 'https://www.flickr.com/search/?text=Chengde'
    source = 'https://www.flickr.com/photos/author/123/'
    pages[search + '&page=1'] = '<a href="/photos/author/123/">Chengde</a>'
    pages[source] = ('<title>Chengde street</title><meta property="og:image" '
                     'content="https://live.staticflickr.com/1/street.jpg">'
                     '<p>Taken on October 1, 1983 Uploaded on October 1, 2025</p>'
                     '<a href="https://creativecommons.org/licenses/by/4.0/">Licence</a>')
    result = asyncio.run(browser._browse_query('flickr', 'Chengde', '1980s', search))
    assert len(result) == 1 and result[0]['date_expression'] == 'October 1, 1983'
    assert all(config.check_robots_txt for _, config in calls)


def test_blocked_or_failed_browser_does_not_erase_other_catalogues(fake_crawler, monkeypatch):
    monkeypatch.delenv('FLICKR_API_KEY', raising=False)
    monkeypatch.delenv('GOOGLE_CSE_API_KEY', raising=False)
    monkeypatch.setenv('GOOGLE_CSE_ID', 'engine')
    monkeypatch.setattr(photos, '_commons', lambda *args: browser._source_items(
        photo_html(), 'https://www.flickr.com/photos/author/1/', 'Chengde', '1980s'))
    monkeypatch.setattr(photos, '_loc', lambda *args: [])
    assert len(photos.search_place_photos('Chengde', '1980s')) == 1
    async def fail(*args):
        raise RuntimeError('browser launch failed')
    monkeypatch.setattr(browser, '_browse', fail)
    with pytest.raises(photos.PhotoResearchUnavailable):
        browser.crawl_place_photos('flickr', 'Chengde', '1980s')
    assert len(photos.search_place_photos('Chengde', '1980s')) == 1


def test_source_and_later_search_failures_preserve_collected_photos(fake_crawler):
    pages, calls, _ = fake_crawler
    search = 'https://www.flickr.com/search/?text=Chengde'
    first = 'https://www.flickr.com/photos/author/1/'
    failed = 'https://www.flickr.com/photos/author/2/'
    pages[search + '&page=1'] = '<a href="' + first + '">Chengde</a><a href="' + failed + '">Chengde</a>'
    pages[first] = photo_html()
    pages[failed] = RuntimeError('source page closed')
    pages[search + '&page=2'] = RuntimeError('search page closed')
    result = asyncio.run(browser._browse_query('flickr', 'Chengde', '1980s', search))
    assert len(result) == 1 and result[0]['source_url'] == first
    assert any(url == search + '&page=2' for url, _ in calls)


def test_source_dates_places_licences_and_cse_previews_are_not_inferred():
    source = 'https://www.flickr.com/photos/author/1/'
    assert not browser._source_items(photo_html(place='Chengdu'), source, 'Chengde', '1980s')
    assert not browser._source_items(photo_html(date='2000-01-01'), source, 'Chengde', '1980s')
    assert not browser._source_items(photo_html(licence='https://creativecommons.org/licenses/by-nc/2.0/'),
                                     source, 'Chengde', '1980s')
    html = '<title>Chengde street</title><meta property="og:image" content="https://encrypted-tbn0.gstatic.com/a">'
    assert not browser._source_items(html, source, 'Chengde', '1980s')
    assert not browser._source_items(photo_html(date='1983'), source, 'Chengde', '')
    recent = datetime.now(ZoneInfo('Australia/Sydney')).date().isoformat()
    assert browser._source_items(photo_html(date=recent), source, 'Chengde', '')


def test_article_extracts_multiple_originals_from_one_relevant_source():
    page = '<title>承德 1983年老照片</title><h1>承德 1983年老照片</h1>'
    page += ''.join(f'<figure><img src="https://archive.example/{i}.jpg" alt="承德街景 1983">'
                    '<figcaption>承德街景 1983</figcaption></figure>' for i in range(10))
    items = browser._source_items(page, 'https://archive.example/chengde', '承德', '1980s')
    assert len(items) == 10 and len({item['image_url'] for item in items}) == 10
    assert len(photos._deduplicate(items + items)) == 10


def test_bilingual_queries_and_album_share_budgets_without_overlapping_browsers(monkeypatch, fake_crawler):
    monkeypatch.setenv('GOOGLE_CSE_ID', 'engine')
    monkeypatch.delenv('GOOGLE_CSE_URL', raising=False)
    queries = browser._discovery_queries('google', '承德', '1983年', browser._search_url('google', '承德', '1983年'))
    assert [parse_qs(urlsplit(url).query)['q'][0] for url, _ in queries] == [
        photos._google_query('承德', '1983年', include_decade=True)]
    calls = []
    active = 0
    peak = 0
    async def query(provider, place, period, url, **kwargs):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        calls.append((url, kwargs))
        await asyncio.sleep(0.01)
        active -= 1
        return []
    monkeypatch.setattr(browser, '_browse_query', query)
    asyncio.run(asyncio.wait_for(browser._browse('flickr', '承德', '1983年', browser._search_url('flickr', '承德', '1983年')), 1))
    assert sum(options['page_budget'] for _, options in calls) == browser.MAX_SEARCH_PAGES
    assert sum(options['source_budget'] for _, options in calls) <= browser.MAX_SOURCE_PAGES
    assert sum(options['album'] for _, options in calls) == 1
    assert peak == 1


def test_browser_providers_and_requests_do_not_launch_chromium_together(monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Lock
    active = peak = 0
    guard = Lock()
    async def browse(*args, **kwargs):
        nonlocal active, peak
        with guard:
            active += 1
            peak = max(peak, active)
        await asyncio.sleep(0.03)
        with guard:
            active -= 1
        return []
    monkeypatch.setattr(browser, '_browse', browse)
    monkeypatch.setenv('GOOGLE_CSE_ID', 'engine')
    monkeypatch.delenv('GOOGLE_CSE_URL', raising=False)
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(lambda provider: browser.crawl_place_photos(provider, 'Chengde', '1980s'),
                      ['google', 'flickr', 'google', 'flickr']))
    assert peak == 1


def test_album_location_does_not_inherit_album_date(fake_crawler):
    pages, calls, _ = fake_crawler
    album = 'https://www.flickr.com/photos/kattebelletje/albums/72157614775600805/'
    first = 'https://www.flickr.com/photos/kattebelletje/1/'
    second = 'https://www.flickr.com/photos/kattebelletje/2/'
    pages[album] = f'<title>Chengde 承德 1983</title><a href="{first}">Willow trees</a><a href="{second}">Lake</a>'
    pages[first] = photo_html(place='Willow trees')
    pages[second] = photo_html(2, place='Lake', date='1984-05-01')
    exact = asyncio.run(browser._browse_query('flickr', '承德', '1983年', album, album=True, page_budget=1))
    assert sorted(item['date_expression'] for item in exact) == ['1983-10-01', '1984-05-01']
    decade = asyncio.run(browser._browse_query('flickr', '承德', '1980s', album, album=True, page_budget=1))
    assert len(decade) == 2
    assert all(config.check_robots_txt for _, config in calls)


def test_sparse_exact_search_expands_decade_labels_and_deduplicates(monkeypatch):
    exact = browser._source_items(photo_html(), 'https://www.flickr.com/photos/author/1/', '承德', '1983年')
    wider = browser._source_items(photo_html(2, date='1984-05-01'), 'https://www.flickr.com/photos/author/2/', '承德', '1980s')
    calls = []
    def search(place, period, **kwargs):
        calls.append(period)
        return exact if period == '1983年' else wider + exact
    monkeypatch.setattr(photos, '_search_period', search)
    items = photos.search_place_photos('承德', '1983年', limit=None)
    assert calls == ['1983年', '1980s']
    assert [item['period_match'] for item in items] == ['requested', 'decade']
    assert items[1]['requested_period'] == '1983年' and items[1]['date_expression'] == '1984-05-01'
    assert items[1]['matched_period'] == '1980s'


@pytest.mark.parametrize('period', ['', '1980s', '1989–1991', 'unknown'])
def test_current_full_decade_and_cross_decade_do_not_expand(period):
    assert photos._decade_fallback(period) is None


def test_failed_decade_search_preserves_exact_matches(monkeypatch):
    exact = browser._source_items(photo_html(), 'https://www.flickr.com/photos/author/1/', '承德', '1983年')
    def search(place, period, **kwargs):
        if period == '1980s':
            raise ValueError('source unavailable')
        return exact
    monkeypatch.setattr(photos, '_search_period', search)
    assert photos.search_place_photos('承德', '1983年')[0]['period_match'] == 'requested'


def test_source_pages_overlap_with_a_bound_and_publish_before_the_slow_page(fake_crawler, monkeypatch):
    import crawl4ai
    pages, calls, _ = fake_crawler
    search = 'https://cse.google.com/cse?cx=engine'
    sources = [f'https://www.flickr.com/photos/author/{i}/' for i in range(1, 5)]
    pages[search] = cse_html(sources)
    crawler = crawl4ai.AsyncWebCrawler()
    original = crawler.arun
    active = peak = 0
    published = []
    async def run(url, config):
        nonlocal active, peak
        if url not in sources:
            return await original(url, config)
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(0.08 if url == sources[0] else 0.01)
        active -= 1
        return SimpleNamespace(success=True, html=photo_html(sources.index(url) + 1), status_code=200)
    crawler.arun = run
    async def check():
        result = await browser._browse_query('google', 'Chengde', '1980s', search,
            crawler=crawler, source_slots=asyncio.Semaphore(2),
            on_items=lambda items: published.append((items, active)))
        assert len(result) == 4
    asyncio.run(check())
    assert peak == 2
    assert published[0][1] > 0, 'The first photo waited for every original page'


def test_one_crawler_serves_all_language_queries(fake_crawler, monkeypatch):
    import crawl4ai
    created = []
    original = crawl4ai.AsyncWebCrawler
    def create(**kwargs):
        created.append(original(**kwargs))
        return created[-1]
    monkeypatch.setattr(crawl4ai, 'AsyncWebCrawler', create)
    monkeypatch.setenv('GOOGLE_CSE_ID', 'engine')
    with pytest.raises(photos.PhotoResearchUnavailable):
        asyncio.run(browser._browse('google', '承德', '1980s', browser._search_url('google', '承德', '1980s')))
    assert len(created) == 1


def test_warm_worker_reuses_chromium_across_requests_and_closes_search_contexts(fake_crawler, monkeypatch):
    import crawl4ai
    created, closed = [], []
    original = crawl4ai.AsyncWebCrawler
    class Context:
        pages = []
        async def close(self):
            closed.append(self)
    def create(**kwargs):
        instance = original(**kwargs)
        created.append(instance)
        run = instance.arun
        async def arun(url, config):
            instance.crawler_strategy.browser_manager.contexts_by_config.setdefault('query', Context())
            return await run(url, config)
        instance.arun = arun
        return instance
    monkeypatch.setattr(crawl4ai, 'AsyncWebCrawler', create)
    async def check():
        runtime = await browser.WarmPhotoBrowser().start()
        try:
            for period in ('1980s', '1990s'):
                with pytest.raises(photos.PhotoResearchUnavailable):
                    await runtime.search('google', 'Chengde', period, 'https://cse.google.com/cse?cx=engine',
                                         limit=10, timeout=1)
            assert len(created) == 1
            assert len(closed) == 2
            assert not runtime.crawler.crawler_strategy.browser_manager.contexts_by_config
        finally:
            await runtime.close()
    asyncio.run(check())


def test_google_verification_screen_is_unavailable_not_a_successful_empty_search(fake_crawler):
    pages, calls, _ = fake_crawler
    search = 'https://cse.google.com/cse?cx=engine'
    pages[search] = '<title>Programmable Search Engine</title><p>Please verify that you are not a robot.</p>'
    with pytest.raises(ValueError) as error:
        asyncio.run(browser._browse_query('google', 'Chengde', '1980s', search))
    assert error.value.failures == [{'provider': 'google', 'reason': 'verification_required'}]
    assert len(calls) == 1


def test_robots_denial_is_not_an_empty_album(fake_crawler):
    with pytest.raises(ValueError) as error:
        asyncio.run(browser._browse_query('flickr', 'Chengde', '1980s',
            'https://www.flickr.com/photos/author/albums/1/', album=True))
    assert error.value.failures[0]['reason'] == 'http_403'


def test_empty_results_with_blocked_providers_reach_retryable_response(monkeypatch):
    from apps.api.place_photo_pages import PhotoPages
    monkeypatch.delenv('GOOGLE_CSE_API_KEY', raising=False)
    monkeypatch.setenv('GOOGLE_CSE_ID', 'engine')
    monkeypatch.delenv('FLICKR_API_KEY', raising=False)
    def blocked(*args, **kwargs):
        raise httpx.HTTPStatusError('blocked', request=httpx.Request('GET', 'https://archive.example'),
                                   response=httpx.Response(403))
    monkeypatch.setattr(photos, '_google_browser', blocked)
    monkeypatch.setattr(photos, '_flickr_browser', blocked)
    monkeypatch.setattr(photos, '_loc', blocked)
    monkeypatch.setattr(photos, '_commons', lambda *args: [])
    cache = PhotoPages()
    try:
        result = cache.page('owner', 'Chengde', '', None)
        assert result['status'] == 'UNAVAILABLE'
        assert result['failures'] == [
            {'provider': 'flickr', 'reason': 'http_403'},
            {'provider': 'google', 'reason': 'http_403'},
            {'provider': 'loc', 'reason': 'http_403'}]
    finally:
        cache.close()


def test_challenge_stops_language_retries_but_other_providers_keep_their_photos(fake_crawler, monkeypatch):
    pages, calls, _ = fake_crawler
    monkeypatch.setenv('GOOGLE_CSE_ID', 'engine')
    monkeypatch.delenv('GOOGLE_CSE_URL', raising=False)
    search = browser._search_url('google', '承德', '1980s')
    pages[search] = '<p>Please verify that you are not a robot.</p>'
    with pytest.raises(ValueError):
        asyncio.run(browser._browse('google', '承德', '1980s', search))
    assert len(calls) == 1


def test_crawl4ai_synthetic_robots_response_has_a_distinct_failure_reason():
    result = SimpleNamespace(status_code=403, response_headers={'X-Robots-Status': 'Blocked by robots.txt'},
                             error_message='Access denied by robots.txt')
    assert browser._crawl_failure(result) == 'robots_denied'


def test_blocked_exact_search_can_still_return_labelled_decade_photos(monkeypatch):
    def search(place, period, **kwargs):
        if period == '1983年':
            raise photos.PhotoResearchUnavailable('google', 'verification_required')
        return [{'asset_id': 'commons-1', 'title': 'Chengde street',
                 'image_url': 'https://archive.example/1.jpg', 'date_expression': '1985',
                 'source_url': 'https://archive.example/photos/1'}]
    monkeypatch.setattr(photos, '_search_period', search)
    result = photos.search_place_photos('承德', '1983年')
    assert len(result) == 1
    assert result[0]['period_match'] == 'decade'


def test_combined_google_search_returns_exact_then_decade_without_second_query(monkeypatch):
    monkeypatch.setenv('GOOGLE_CSE_ID', 'engine')
    monkeypatch.delenv('GOOGLE_CSE_API_KEY', raising=False)
    monkeypatch.delenv('GOOGLE_CSE_URL', raising=False)
    monkeypatch.delenv('FLICKR_API_KEY', raising=False)
    calls, streamed = [], []
    def google(place, period, **kwargs):
        calls.append(period)
        items = browser._source_items(photo_html(2, date='1986-05-01'),
                                      'https://www.flickr.com/photos/author/2/', place, '1980s')
        items += browser._source_items(photo_html(1), 'https://www.flickr.com/photos/author/1/', place, '1980s')
        items += [{**items[0], 'asset_id': 'wrong-period', 'date_expression': '1994'}]
        if kwargs.get('on_items'):
            kwargs['on_items'](items)
        return items
    monkeypatch.setattr(photos, '_google_browser', google)
    for name in ('_flickr_browser', '_commons', '_loc'):
        monkeypatch.setattr(photos, name, lambda *args, **kwargs: [])
    items = photos.search_place_photos('承德', '1983年', limit=None, on_items=streamed.extend)
    assert calls == ['1983年']
    assert [item['period_match'] for item in items] == ['requested', 'decade']
    assert items[1]['matched_period'] == '1980s'
    assert any(item['period_match'] == 'decade' for item in streamed)
    assert all(item['date_expression'] != '1994' for item in items + streamed)


def test_combined_google_source_inspection_accepts_only_the_ten_year_tolerance(fake_crawler):
    pages, calls, _ = fake_crawler
    search = 'https://cse.google.com/cse?cx=engine'
    sources = [f'https://www.flickr.com/photos/author/{i}/' for i in range(1, 6)]
    pages[search] = cse_html(sources)
    for index, date in enumerate(('1972-01-01', '1973-01-01', '1983-10-01', '1993-01-01', '1994-01-01'), 1):
        pages[sources[index - 1]] = photo_html(index, date=date)
    items = asyncio.run(browser._browse_query('google', 'Chengde', '1983年', search,
                                             page_budget=1))
    assert sorted(item['date_expression'] for item in items) == ['1973-01-01', '1983-10-01', '1993-01-01']


def test_blocked_combined_google_query_is_not_repeated_for_decade_fallback(monkeypatch):
    monkeypatch.setenv('GOOGLE_CSE_ID', 'engine')
    monkeypatch.delenv('GOOGLE_CSE_API_KEY', raising=False)
    monkeypatch.delenv('GOOGLE_CSE_URL', raising=False)
    monkeypatch.delenv('FLICKR_API_KEY', raising=False)
    calls = []
    def google(place, period, **kwargs):
        calls.append(period)
        raise photos.PhotoResearchUnavailable('google', 'verification_required')
    monkeypatch.setattr(photos, '_google_browser', google)
    for name in ('_flickr_browser', '_commons', '_loc'):
        monkeypatch.setattr(photos, name, lambda *args, **kwargs: [])
    with pytest.raises(photos.PhotoResearchUnavailable) as error:
        photos.search_place_photos('承德', '1983年')
    assert calls == ['1983年']
    assert error.value.failures == [{'provider': 'google', 'reason': 'verification_required'}]



# Issue #66: offline discovery expansion, with no local database or live provider.
def test_historical_query_expansion_has_bounded_archive_street_album_and_year_leads():
    from apps.api.place_photo_expansion import historical_queries, google_search_urls
    base = '("承德" OR "Chengde") ("1980" OR "1989")'
    queries = historical_queries(base, '("承德" OR "Chengde")', (1980, 1989))
    assert queries[0] == base
    assert len(queries) == len(set(queries)) == 7
    assert any('archive' in query and '档案' in query for query in queries[1:])
    assert any('street' in query and '街景' in query for query in queries[1:])
    assert any('album' in query and '相册' in query for query in queries[1:])
    assert all('Chengde' in query for query in queries)
    assert historical_queries(base, 'Chengde', None) == [base]
    assert historical_queries(base, 'Chengde', (1800, 1901)) == [base]
    urls = google_search_urls('https://cse.google.com/cse?cx=engine&page=9', queries)
    assert len(urls) == len(queries)
    assert all(parse_qs(urlsplit(url).query).get('cx') == ['engine'] for url in urls)
    assert all('page' not in parse_qs(urlsplit(url).query) for url in urls)
    with pytest.raises(ValueError):
        google_search_urls('https://attacker.example/cse?cx=engine', queries)


def test_sparse_serpapi_expansion_inspects_ten_distinct_history_photos(serpapi_sources, monkeypatch):
    import subprocess
    _, sources, _, fetched = serpapi_sources
    monkeypatch.setenv('MEMOIR_PHOTO_EXPANSION', '1')
    monkeypatch.setattr('apps.api.place_photo_fingerprints.image_fingerprint', lambda url: {})
    queries = []

    def search(command, **kwargs):
        payload = json.loads(kwargs['input'])
        assert payload['refresh'] is True
        queries.append(payload['query'])
        batch = ([1] if len(queries) == 1 else list(range(2, 11)))
        cards = [{'source_url': f'https://archive.example/photo/{i}',
                  'text': 'Chengde 1980s historical image'} for i in batch]
        if len(queries) == 2:
            cards += [{'source_url': 'https://archive.example/modern', 'text': 'Chengde'},
                      {'source_url': 'https://archive.example/chengdu', 'text': 'Chengde'},
                      cards[0]]
        return SimpleNamespace(stdout='PLACE_PHOTO_RESULT:' + json.dumps({
            'status': 'success', 'cards': cards,
        }))

    for index in range(1, 11):
        sources[f'https://archive.example/photo/{index}'] = photo_html(index, date='1983-10-01')
    sources['https://archive.example/modern'] = photo_html(50, date='2025-10-01')
    sources['https://archive.example/chengdu'] = photo_html(51, place='Chengdu')
    monkeypatch.setattr(subprocess, 'run', search)
    items = photos._google_serpapi('Chengde', '1980s')
    assert len(items) == 10
    assert len({item['image_url'] for item in items}) == 10
    assert all(item['date_expression'] == '1983-10-01' for item in items)
    assert all(item['source_url'] in fetched for item in items)
    assert all(item['providers'] == ['google', 'serpapi'] for item in items)
    assert len(queries) == 2, 'stop after reaching ten verified originals'


def test_sparse_serpapi_outage_preserves_verified_result_and_stops_retries(serpapi_sources, monkeypatch):
    import subprocess
    _, sources, _, _ = serpapi_sources
    monkeypatch.setenv('MEMOIR_PHOTO_EXPANSION', 'yes')
    monkeypatch.setattr('apps.api.place_photo_fingerprints.image_fingerprint', lambda url: {})
    sources['https://archive.example/photo/1'] = photo_html()
    searches = []

    def search(command, **kwargs):
        searches.append(json.loads(kwargs['input']))
        if len(searches) == 1:
            payload = {'status': 'success', 'cards': [
                {'source_url': 'https://archive.example/photo/1', 'text': 'Chengde 1983'},
            ]}
        else:
            payload = {'status': 'error', 'error': 'TimeoutError'}
        return SimpleNamespace(stdout='PLACE_PHOTO_RESULT:' + json.dumps(payload))

    monkeypatch.setattr(subprocess, 'run', search)
    items = photos._google_serpapi('Chengde', '1980s')
    assert len(items) == 1 and items[0]['date_expression'] == '1983-10-01'
    assert len(searches) == 2


def test_enabled_browser_expansion_uses_shared_page_source_budgets(monkeypatch, fake_crawler):
    monkeypatch.setenv('GOOGLE_CSE_ID', 'engine')
    monkeypatch.setenv('MEMOIR_PHOTO_EXPANSION', 'true')
    monkeypatch.delenv('GOOGLE_CSE_URL', raising=False)
    calls = []

    async def query(provider, place, period, url, **kwargs):
        calls.append((parse_qs(urlsplit(url).query)['q'][0], kwargs))
        return []

    monkeypatch.setattr(browser, '_browse_query', query)
    url = browser._search_url('google', '承德', '1980s')
    assert asyncio.run(browser._browse('google', '承德', '1980s', url)) == []
    assert len(calls) == browser.MAX_SEARCH_PAGES
    assert len({query for query, _ in calls}) == len(calls)
    assert sum(opts['page_budget'] for _, opts in calls) == browser.MAX_SEARCH_PAGES
    assert sum(opts['source_budget'] for _, opts in calls) <= browser.MAX_SOURCE_PAGES
    assert all(opts['album'] is False for _, opts in calls)



def test_expanded_cache_is_separate_and_does_not_trust_sparse_legacy_completion(monkeypatch):
    from apps.api.place_photo_repository import PhotoRepository, search_key
    rows = {}

    def storage(request):
        if request.method == 'POST':
            record = json.loads(request.content)
            rows[record['search_key']] = record['result']
            return httpx.Response(201)
        key = request.url.params['search_key'].removeprefix('eq.')
        return httpx.Response(200, json=[{'result': rows[key]}] if key in rows else [])

    repository = PhotoRepository('https://example.supabase.co', 'synthetic',
                                 transport=httpx.MockTransport(storage))
    monkeypatch.delenv('MEMOIR_PHOTO_EXPANSION', raising=False)
    legacy = search_key('承德', '1980s')
    repository.save('承德', '1980s', {
        'items': [{'asset_id': 'sparse', 'date_expression': '1983'}], 'complete': True,
    })
    assert len(repository.load('承德', '1980s')['items']) == 1

    monkeypatch.setenv('MEMOIR_PHOTO_EXPANSION', '1')
    assert search_key('承德', '1980s') != legacy
    assert repository.load('承德', '1980s') is None, 'expanded mode must re-research legacy complete caches'
    repository.save('承德', '1980s', {'items': [{'asset_id': 'expanded'}], 'complete': True})
    assert repository.load('承德', '1980s')['items'][0]['asset_id'] == 'expanded'
    monkeypatch.setenv('MEMOIR_PHOTO_EXPANSION', '0')
    assert repository.load('承德', '1980s')['items'][0]['asset_id'] == 'sparse'


def test_expansion_through_authenticated_photo_endpoint_without_database(monkeypatch, serpapi_sources):
    import subprocess
    from fastapi.testclient import TestClient
    from apps.api.main import create_app
    from apps.api.store import MemoryStore

    _, sources, _, _ = serpapi_sources
    monkeypatch.setenv('MEMOIR_PHOTO_EXPANSION', '1')
    monkeypatch.setenv('SERPAPI_KEY', 'synthetic-provider-key')
    monkeypatch.delenv('GOOGLE_CSE_API_KEY', raising=False)
    monkeypatch.setenv('GOOGLE_CSE_ID', 'engine')
    monkeypatch.delenv('FLICKR_API_KEY', raising=False)
    monkeypatch.setenv('MEMORY_SPARK_PHOTO_WEB_SEARCH', '0')
    for provider in ('_commons', '_loc', '_flickr_browser'):
        monkeypatch.setattr(photos, provider, lambda *args, **kwargs: [])
    monkeypatch.setattr('apps.api.place_photo_fingerprints.image_fingerprint', lambda url: {})
    searches = []

    def discovered(command, **kwargs):
        searches.append(json.loads(kwargs['input']))
        batch = [1] if len(searches) == 1 else list(range(2, 11))
        return SimpleNamespace(stdout='PLACE_PHOTO_RESULT:' + json.dumps({
            'status': 'success', 'cards': [
                {'source_url': f'https://archive.example/photo/{index}', 'text': 'Chengde photo'}
                for index in batch],
        }))

    monkeypatch.setattr(subprocess, 'run', discovered)
    for index in range(1, 11):
        sources[f'https://archive.example/photo/{index}'] = photo_html(index)

    with TestClient(create_app(MemoryStore())) as client:
        headers = {'X-Account-Id': 'cloud-fixture-owner'}
        created = client.post('/v1/projects', headers=headers, json={'mode': 'self'})
        assert created.status_code in {200, 201}
        project = created.json()['id']
        url = f'/v1/projects/{project}/place-photos'
        scope = {'place': 'Chengde', 'period': '1980s', 'latitude': 40.98, 'longitude': 117.94}
        response = client.get(url, headers=headers, params=scope)
        assert response.status_code == 200
        page = response.json()
        assert page['status'] == 'READY'
        assert len(page['items']) == page['count'] == page['target_count'] == 10
        assert page['shortfall'] == 0
        assert all(item['requested_period'] == '1980s' for item in page['items'])
        other = client.get(url, headers={'X-Account-Id': 'other-owner'}, params=scope)
        assert other.status_code in {403, 404}
    assert len(searches) == 2 and all(query['refresh'] is True for query in searches)



def test_album_link_expansion_requires_each_photo_own_capture_date(monkeypatch, serpapi_sources):
    import subprocess
    _, sources, _, fetched = serpapi_sources
    monkeypatch.setenv('MEMOIR_PHOTO_EXPANSION', 'yes')
    monkeypatch.setattr('apps.api.place_photo_fingerprints.image_fingerprint', lambda url: {})
    album = 'https://archive.example/albums/chengde/'
    sources[album] = (
        '<title>Chengde 1980s photographer album</title>'
        '<nav><a href="https://archive.example/photos/navigation-beijing">Other cities</a></nav>'
        '<section class="album-items">' +
        ''.join(f'<article class="album-photo">'
                f'<a href="https://archive.example/photos/{i}">Photo {i}</a></article>'
                for i in range(1, 7)) +
        '<div class="recommendations">'
        '<a href="https://archive.example/photos/related-beijing">Recommended Beijing street</a>'
        '</div></section>'
        '<aside class="related-gallery">'
        '<a href="https://archive.example/photos/related-beijing">More photos</a></aside>'
    )
    sources['https://archive.example/photos/1'] = photo_html(1, place='Willow trees', date='1983-10-01')
    sources['https://archive.example/photos/2'] = photo_html(2, place='Market street', date='1984-05-01')
    sources['https://archive.example/photos/3'] = photo_html(3, place='Museum', date='2025-05-01')
    sources['https://archive.example/photos/4'] = photo_html(4, place='Chengdu', date='1983-10-01')
    sources['https://archive.example/photos/5'] = photo_html(5, place='Hillside', date='')
    sources['https://archive.example/photos/6'] = photo_html(6, place='Beijing', date='1983-10-01')
    sources['https://archive.example/photos/navigation-beijing'] = photo_html(20, place='Beijing')
    sources['https://archive.example/photos/related-beijing'] = photo_html(21, place='Beijing')

    def discovery(command, **kwargs):
        return SimpleNamespace(stdout='PLACE_PHOTO_RESULT:' + json.dumps({
            'status': 'success',
            'cards': [{'source_url': album, 'text': 'Chengde photographer album'}],
        }))

    monkeypatch.setattr(subprocess, 'run', discovery)
    result = photos._google_serpapi('Chengde', '1980s')
    assert [item['date_expression'] for item in result] == ['1983-10-01', '1984-05-01']
    assert {item['source_url'] for item in result} == {
        'https://archive.example/photos/1', 'https://archive.example/photos/2'}
    assert album in fetched and 'https://archive.example/photos/3' in fetched
    assert 'https://archive.example/photos/4' in fetched
    assert 'https://archive.example/photos/6' in fetched
    assert 'https://archive.example/photos/navigation-beijing' not in fetched
    assert 'https://archive.example/photos/related-beijing' not in fetched
    assert all('Chengde' in item['location_evidence'] for item in result)




def test_gallery_item_with_structured_conflicting_city_cannot_inherit_album_location(
        monkeypatch, serpapi_sources):
    import subprocess
    _, sources, _, fetched = serpapi_sources
    monkeypatch.setenv('MEMOIR_PHOTO_EXPANSION', 'yes')
    monkeypatch.setattr('apps.api.place_photo_fingerprints.image_fingerprint', lambda url: {})
    album = 'https://archive.example/albums/chengde/'
    source = 'https://archive.example/photos/7'
    sources[album] = (
        '<title>Chengde 1980s photographer album</title>'
        '<section class="album-items">'
        '<a href="https://archive.example/photos/1">Local album image</a>'
        '<a href="https://archive.example/photos/7">Other city image</a>'
        '</section>')
    sources['https://archive.example/photos/1'] = photo_html(1, place='Willow trees')
    claim = {'@type': 'Photograph', 'name': 'Willow trees', 'dateCreated': '1983-10-01',
             'contentLocation': {'name': 'Beijing'},
             'contentUrl': 'https://live.staticflickr.com/1/7.jpg'}
    sources[source] = ('<title>Willow trees</title>'
                       '<script type="application/ld+json">' + json.dumps(claim) + '</script>')

    def discovery(command, **kwargs):
        return SimpleNamespace(stdout='PLACE_PHOTO_RESULT:' + json.dumps({
            'status': 'success',
            'cards': [{'source_url': album, 'text': 'Chengde historical photo album'}],
        }))

    monkeypatch.setattr(subprocess, 'run', discovery)
    photos_found = photos._google_serpapi('Chengde', '1980s')
    assert len(photos_found) == 1
    assert photos_found[0]['image_url'] == 'https://live.staticflickr.com/1/1.jpg'
    assert source in fetched, 'conflicting item must be inspected, then excluded'
    assert all('Beijing' not in item['location_evidence'] for item in photos_found)


def test_only_gallery_member_markup_can_inherit_album_locality():
    from apps.api.place_photo_expansion import verified_album_member_links
    base = 'https://archive.example/albums/chengde/'
    html = ('<title>Chengde history</title>'
            '<nav><a href="/photos/beijing">Navigation: Beijing street</a></nav>'
            '<a href="/photos/unscoped">Other same-host photograph</a>'
            '<div class="album-grid"><figure><a href="/photos/1">Photo one</a></figure>'
            '<section class="recommendations"><a href="/photos/recommended">Related</a></section>'
            '<figure><a href="/photos/2">Photo two</a></figure></div>'
            '<aside class="related-gallery"><a href="/photos/more">More photos</a></aside>')
    assert verified_album_member_links(html, base) == [
        'https://archive.example/photos/1',
        'https://archive.example/photos/2',
    ]
    assert verified_album_member_links(
        '<title>Chengde album</title><a href="/photos/unscoped">Not a member</a>', base,
    ) == []


@pytest.mark.parametrize('scope,expected_queries', [('source', 3), ('provider', 1)])
def test_source_robots_denial_does_not_stop_healthy_google_expansion(
        monkeypatch, fake_crawler, scope, expected_queries):
    monkeypatch.setenv('GOOGLE_CSE_ID', 'engine')
    monkeypatch.setenv('MEMOIR_PHOTO_EXPANSION', '1')
    monkeypatch.delenv('GOOGLE_CSE_URL', raising=False)
    accepted = browser._source_items(photo_html(), 'https://archive.example/photo/1',
                                     'Chengde', '1980s')
    calls = []

    async def query(provider, place, period, url, **kwargs):
        calls.append(url)
        if len(calls) == 1:
            raise photos.PhotoResearchUnavailable(failures=[{
                'provider': 'google', 'reason': 'robots_denied', 'scope': scope,
            }])
        return accepted

    monkeypatch.setattr(browser, '_browse_query', query)
    search = browser._search_url('google', 'Chengde', '1980s')
    if scope == 'source':
        results = asyncio.run(browser._browse('google', 'Chengde', '1980s', search))
        assert len(results) == 1 and results[0]['date_expression'] == '1983-10-01'
    else:
        with pytest.raises(photos.PhotoResearchUnavailable):
            asyncio.run(browser._browse('google', 'Chengde', '1980s', search))
    assert len(calls) == expected_queries



def test_expansion_cache_identity_tracks_server_provider_mode_not_credential_values(monkeypatch):
    from apps.api.place_photo_repository import search_key
    monkeypatch.setenv('MEMOIR_PHOTO_EXPANSION', '1')
    monkeypatch.setenv('GOOGLE_CSE_ID', 'synthetic-engine')
    monkeypatch.delenv('GOOGLE_CSE_API_KEY', raising=False)
    monkeypatch.delenv('SERPAPI_KEY', raising=False)
    monkeypatch.delenv('GOOGLE_CSE_URL', raising=False)
    browser_key = search_key('Chengde', '1980s')
    monkeypatch.setenv('SERPAPI_KEY', 'private-one')
    serpapi_key = search_key('Chengde', '1980s')
    assert browser_key != serpapi_key
    monkeypatch.setenv('SERPAPI_KEY', 'private-two')
    assert search_key('Chengde', '1980s') == serpapi_key
    monkeypatch.setenv('GOOGLE_CSE_API_KEY', 'private-three')
    assert search_key('Chengde', '1980s') != serpapi_key, 'Adding a CSE route requires fresh research'
    combined_api_key = search_key('Chengde', '1980s')
    monkeypatch.setenv('GOOGLE_CSE_API_KEY', 'private-four')
    assert search_key('Chengde', '1980s') == combined_api_key
    monkeypatch.delenv('SERPAPI_KEY')
    assert search_key('Chengde', '1980s') not in {browser_key, serpapi_key, combined_api_key}



def test_rehosted_duplicate_never_fills_ten_photo_target(monkeypatch, serpapi_sources):
    import subprocess
    _, sources, _, _ = serpapi_sources
    monkeypatch.setenv('MEMOIR_PHOTO_EXPANSION', 'true')
    attempts = []

    def fingerprint(image_url):
        number = int(image_url.rsplit('/', 1)[1].split('.')[0])
        return {'content_hash': 'same-photo' if number in {1, 2} else f'unique-{number}'}

    monkeypatch.setattr('apps.api.place_photo_fingerprints.image_fingerprint', fingerprint)

    def discovered(command, **kwargs):
        attempts.append(json.loads(kwargs['input'])['query'])
        ids = [1] if len(attempts) == 1 else (
            list(range(2, 11)) if len(attempts) == 2 else [11])
        return SimpleNamespace(stdout='PLACE_PHOTO_RESULT:' + json.dumps({
            'status': 'success', 'cards': [
                {'source_url': f'https://archive.example/photos/{index}', 'text': 'Chengde street'}
                for index in ids
            ],
        }))

    monkeypatch.setattr(subprocess, 'run', discovered)
    for index in range(1, 12):
        sources[f'https://archive.example/photos/{index}'] = photo_html(index)
    result = photos._google_serpapi('Chengde', '1980s')
    assert len(result) == 10
    assert len({item['content_hash'] for item in result}) == 10
    assert len(attempts) == 3, 'one rehosted duplicate must not prematurely satisfy the target'



def test_serpapi_verifies_and_publishes_initial_photo_before_followup_query(
        monkeypatch, serpapi_sources):
    import subprocess
    _, sources, _, _ = serpapi_sources
    monkeypatch.setenv('MEMOIR_PHOTO_EXPANSION', '1')
    monkeypatch.setenv('SERPAPI_KEY', 'synthetic-key')
    monkeypatch.setenv('GOOGLE_CSE_ID', 'engine')
    monkeypatch.delenv('GOOGLE_CSE_API_KEY', raising=False)
    monkeypatch.delenv('FLICKR_API_KEY', raising=False)
    monkeypatch.setenv('MEMORY_SPARK_PHOTO_WEB_SEARCH', '0')
    for name in ('_google_browser', '_flickr_browser', '_commons', '_loc'):
        monkeypatch.setattr(photos, name, lambda *args, **kwargs: [])
    monkeypatch.setattr('apps.api.place_photo_fingerprints.image_fingerprint', lambda url: {})
    sources['https://archive.example/photos/1'] = photo_html(1)
    sources['https://archive.example/photos/2'] = photo_html(2)
    messages, searches = [], []

    def search(command, **kwargs):
        searches.append(json.loads(kwargs['input'])['query'])
        if len(searches) == 2:
            assert messages and len(messages[0]) == 1, (
                'first verified original must reach callback before second provider request')
        index = min(len(searches), 2)
        return SimpleNamespace(stdout='PLACE_PHOTO_RESULT:' + json.dumps({
            'status': 'success', 'cards': [
                {'source_url': f'https://archive.example/photos/{index}', 'text': 'Chengde 1983'}
            ],
        }))

    monkeypatch.setattr(subprocess, 'run', search)
    found = photos._search_period('Chengde', '1980s', on_items=lambda items: messages.append(items))
    assert len(found) == 2 and len(searches) >= 2
    assert len(messages[0]) == 1
    assert all(item['date_expression'] == '1983-10-01' for item in found)



def test_album_landmark_alias_cannot_override_wrong_city_on_photo(
        monkeypatch, serpapi_sources):
    """Regression: Chengde 离宫 is not Beijing's Summer Palace."""
    import subprocess

    _, sources, _, fetched = serpapi_sources
    monkeypatch.setenv('MEMOIR_PHOTO_EXPANSION', 'yes')
    monkeypatch.setattr('apps.api.place_photo_fingerprints.image_fingerprint', lambda url: {})
    album = 'https://archive.example/albums/chengde/'
    local = 'https://archive.example/photos/chengde'
    other = 'https://archive.example/photos/beijing'
    anchored = 'https://archive.example/photos/anchored'

    sources[album] = (
        '<title>承德 避暑山庄 1983 album</title>'
        '<section class="album-items">'
        f'<a href="{local}">Local photo</a>'
        f'<a href="{other}">Marble boat</a>'
        f'<a href="{anchored}">Another local photo</a>'
        '</section>')
    sources[local] = photo_html(71, place='Chengde Mountain Resort')
    sources[other] = (
        '<title>Marble Boat</title>'
        '<script type="application/ld+json">' + json.dumps({
            '@type': 'Photograph', 'name': 'Marble Boat',
            'contentLocation': {'name': 'Summer Palace, Beijing'},
            'dateCreated': '1983-10-01',
            'contentUrl': 'https://live.staticflickr.com/1/72.jpg',
        }) + '</script>')
    sources[anchored] = (
        '<title>Willow trees</title>'
        '<script type="application/ld+json">' + json.dumps({
            '@type': 'Photograph', 'name': 'Willow trees',
            'contentLocation': {'name': 'Chengde'},
            'dateCreated': '1983-10-01',
            'license': 'https://creativecommons.org/licenses/by/4.0/',
            'contentUrl': 'https://live.staticflickr.com/1/73.jpg',
        }) + '</script>')

    def discovery(command, **kwargs):
        return SimpleNamespace(stdout='PLACE_PHOTO_RESULT:' + json.dumps({
            'status': 'success',
            'cards': [{'source_url': album,
                       'text': '离宫 承德市 Mountain Resort 1983'}],
        }))
    monkeypatch.setattr(subprocess, 'run', discovery)

    result = photos._google_serpapi('离宫, 承德市', '1980s')
    assert set(item['source_url'] for item in result) == {local, anchored}
    assert other in fetched, 'the linked wrong-city original was inspected, not silently skipped'
    assert not any(item['image_url'].endswith('/72.jpg') for item in result)


@pytest.mark.parametrize('child_location,accepted', [
    ('Summer Palace, Beijing', False),
    ('北京颐和园', False),
    ('summer palace', False),
    ('Summer Palace, Chengde', True),
    ('承德市', True),
    ('Chengde', True),
    ('Chengde and Beijing', False),
])
def test_explicit_album_photo_locality_requires_city_anchor(
        monkeypatch, serpapi_sources, child_location, accepted):
    import subprocess
    _, sources, _, _ = serpapi_sources
    monkeypatch.setenv('MEMOIR_PHOTO_EXPANSION', 'yes')
    monkeypatch.setattr('apps.api.place_photo_fingerprints.image_fingerprint', lambda url: {})
    album = 'https://archive.example/albums/chengde/'
    item = 'https://archive.example/photos/locality'
    sources[album] = (
        '<title>承德 避暑山庄 photo album</title>'
        '<section class="gallery"><a href="' + item + '">Photo</a></section>'
    )
    sources[item] = (
        '<title>Marble Boat</title>'
        '<script type="application/ld+json">' + json.dumps({
            '@type': 'Photograph', 'name': 'Marble Boat', 'dateCreated': '1983-10-01',
            'contentLocation': {'name': child_location},
            'license': 'https://creativecommons.org/licenses/by/4.0/',
            'contentUrl': 'https://live.staticflickr.com/1/75.jpg',
        }) + '</script>')

    def discovery(command, **kwargs):
        return SimpleNamespace(stdout='PLACE_PHOTO_RESULT:' + json.dumps({
            'status': 'success',
            'cards': [{'source_url': album, 'text': '离宫 承德市 historical photograph'}],
        }))
    monkeypatch.setattr(subprocess, 'run', discovery)
    found = photos._google_serpapi('离宫, 承德市', '1980s')
    assert bool(found) is accepted
    if accepted:
        assert found[0]['source_url'] == item
