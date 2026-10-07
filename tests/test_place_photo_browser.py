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


def photo_html(index=1, *, date='1983-10-01', place='Chengde', licence=None):
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
        years = ' OR '.join(str(year) for year in range(1970, 2000))
        assert query == f'("承德" OR "Chengde") ({years})'
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
    assert result[0]['license'] == 'Unknown'
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
                     '<p>Taken on October 1, 1983 Uploaded on October 1, 2025</p>')
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
