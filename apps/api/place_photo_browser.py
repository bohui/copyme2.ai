"""Keyless place-photo discovery through public, browser-rendered pages."""
from __future__ import annotations

import asyncio
from datetime import datetime
from functools import lru_cache
import hashlib
import importlib.util
import logging
from pathlib import Path
import re
import time
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)
MAX_SEARCH_PAGES = 3
MAX_SOURCE_PAGES = 12
BROWSE_TIMEOUT = 90


@lru_cache(maxsize=1)
def _research():
    # Reuse the skill's parsers and URL checks, without creating a local run or
    # importing its candidates as licensed book assets.
    path = Path(__file__).resolve().parents[2] / 'skills/place-photo-research/scripts/photo_research.py'
    spec = importlib.util.spec_from_file_location('place_photo_research', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _search_url(provider: str, place: str, period: str) -> str:
    from .place_photos import _configured_env, _localized_photo_query
    query = _localized_photo_query(place, period)
    if provider == 'flickr':
        return 'https://www.flickr.com/search/?' + urlencode({'text': query})
    raw = _configured_env('GOOGLE_CSE_URL')
    if not raw:
        cx = _configured_env('GOOGLE_CSE_ID')
        if not cx:
            return ''
        raw = 'https://cse.google.com/cse?' + urlencode({'cx': cx})
    parsed = urlsplit(raw)
    params = parse_qs(parsed.query)
    if (parsed.scheme != 'https' or parsed.hostname not in {'cse.google.com', 'www.google.com'}
            or parsed.username or parsed.password or parsed.port not in {None, 443}
            or not params.get('cx')):
        raise ValueError('GOOGLE_CSE_URL must identify a public Google CSE page with cx')
    params['q'] = [query]
    params.pop('start', None)
    params.pop('page', None)
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path or '/cse', urlencode(params, doseq=True), ''))


def _flickr_cards(source_html: str, base: str) -> list[dict]:
    parser = _research().PageParser(base)
    parser.feed(source_html)
    cards = {}
    for link in parser.output()['links']:
        url = urlsplit(link['url'])
        if url.hostname not in {'www.flickr.com', 'flickr.com'}:
            continue
        match = re.fullmatch(r'/photos/[^/]+/\d+/?', url.path)
        if match:
            source = 'https://www.flickr.com' + url.path.rstrip('/') + '/'
            cards[source] = {'source_url': source, 'title': link['text']}
    return list(cards.values())


def _source_items(source_html: str, source_url: str, place: str, period: str,
                  *, location_context: str = '') -> list[dict]:
    """Use source captions and capture metadata; page/upload dates cannot date photos."""
    from .place_photos import _date_matches, _google_license, _period_bounds, _text
    helper = _research()
    parser = helper.PageParser(source_url)
    parser.feed(source_html)
    page = parser.output()
    meta = {item.get('property') or item.get('name'): item.get('content', '') for item in page['metadata']}
    title = meta.get('og:title') or page['title']
    description = meta.get('og:description') or meta.get('description') or ''
    context = ' '.join((title, description))
    # An unrelated item on a relevant search page is still unrelated.
    location_evidence = ' '.join((context, location_context)).strip()
    if not helper._crawl4ai_location_matches(location_evidence, place):
        return []

    objects = []
    for record in page['json_ld']:
        records = record if isinstance(record, list) else [record]
        for item in records:
            if isinstance(item, dict):
                objects.extend(item.get('@graph', [item]))
    photo = next((item for item in objects if isinstance(item, dict)
                  and item.get('@type') in ('Photograph', 'ImageObject')), {})
    taken = _text(photo.get('dateCreated'))
    if not taken:
        # Flickr exposes this separate from its "Uploaded on" timestamp.
        match = re.search(r'Taken on\s+([A-Za-z]+\s+\d{1,2},?\s+(?:18|19|20)\d{2})', page['text_excerpt'], re.I)
        taken = match.group(1) if match else ''
    if not taken:
        for key in ('dateTaken', 'date_taken', 'exif:DateTimeOriginal'):
            if meta.get(key):
                taken = meta[key]
                break
    # A year in the item title/caption is a source assertion; a whole article's
    # publication year and recommendation text are deliberately excluded.
    bounds = _period_bounds(period)
    temporal = {
        'mode': 'historical_range',
        'start': f'{bounds[0]:04d}-01-01' if bounds else '2000-01-01',
        'end': f'{bounds[1]:04d}-12-31' if bounds else '2000-12-31',
    }
    scene_date = helper._crawl4ai_scene_date(taken or context, temporal)
    if period and (not scene_date or (taken and not _date_matches(taken, period))):
        return []
    if not period:
        current = helper.normalize_period(None, datetime.now(ZoneInfo('Australia/Sydney')).date())
        years = helper._crawl4ai_years(taken or context)
        scene_date = None
        if years:
            year = years[0]
            start, end = f'{year:04d}-01-01', f'{year:04d}-12-31'
            iso_date = re.match(r'\d{4}-\d{2}-\d{2}', taken)
            if iso_date:
                start = end = iso_date.group()
            elif taken:
                try:
                    start = end = datetime.strptime(taken.replace(',', ''), '%B %d %Y').date().isoformat()
                except ValueError:
                    pass
            if current['start'] <= start and end <= current['end']:
                scene_date = {'start': start, 'end': end}
        if not scene_date:
            return []
    creator = photo.get('creator') or photo.get('author') or {}
    attribution = _text(creator.get('name') if isinstance(creator, dict) else creator)
    licence_url = _text(photo.get('license') or meta.get('license'))
    licence = _google_license({'license': licence_url})
    if licence_url and not licence:
        return []
    image_urls = []
    primary = photo.get('contentUrl') or meta.get('og:image')
    if primary:
        image_urls.append((primary, title, scene_date))
    is_flickr = urlsplit(source_url).hostname in {'www.flickr.com', 'flickr.com'}
    if period and not is_flickr:
        images = helper._crawl4ai_source_images(
            {'url': source_url, 'html': source_html}, {'title': title, 'text': context},
            {'place': place, 'temporal': temporal},
        )
        image_urls.extend((image['image_url'], image['title'], image['scene_date']) for image in images)
    elif not primary:
        for image in page['image_candidates']:
            caption = ' '.join((image['alt'], image['figure_text']))
            if (helper.NON_PHOTO.search(caption)
                    or not helper._crawl4ai_location_matches(caption, place)):
                continue
            image_urls.extend((url, caption, scene_date) for url in image['candidate_urls'])
    items = []
    for observed, caption, image_date in image_urls:
        image = helper._crawl4ai_image_url(observed)
        if not image or helper.NON_PHOTO.search(caption):
            continue
        if is_flickr:
            if not re.fullmatch(r'(?:live|farm\d+)\.staticflickr\.com', urlsplit(image).hostname or ''):
                continue
        identifier = hashlib.sha256(f'{source_url}\n{image}'.encode()).hexdigest()[:24]
        items.append({
            'asset_id': 'crawl4ai-' + identifier, 'kind': 'image', 'title': _text(caption),
            'source_url': source_url, 'image_url': image, 'original_url': image,
            'location': place, 'attribution': attribution or urlsplit(source_url).hostname,
            'location_evidence': location_evidence,
            'date_expression': taken or image_date['start'][:4],
            'scene_date_range': image_date, 'date_basis': 'Source capture metadata or caption',
            'license': licence[0] if licence else 'Unknown', 'license_url': licence_url,
            'memory_reference_only': True,
            'allowed_actions': {'embed': True, 'memory_reference': True, 'download': False,
                                'print': False, 'publish': False},
        })
    return items


async def _browse_query(provider: str, place: str, period: str, search_url: str, *, limit: int = 10,
                        timeout: float = BROWSE_TIMEOUT, page_budget: int = MAX_SEARCH_PAGES,
                        source_budget: int = MAX_SOURCE_PAGES, album: bool = False) -> list[dict]:
    from crawl4ai import AsyncWebCrawler, BrowserConfig, CacheMode, CrawlerRunConfig
    from .place_photos import _deduplicate
    helper = _research()
    seen_sources, items = set(), []
    checked_hosts = {}
    deadline = time.monotonic() + timeout - min(10, timeout / 4)

    async def public_request(route):
        try:
            _, host, port = helper.valid_url(route.request.url)
            if (host, port) not in checked_hosts:
                checked_hosts[host, port] = await asyncio.to_thread(helper.public_addresses, host, port)
            await route.continue_()
        except (helper.ResearchError, ValueError, OSError):
            await route.abort()

    async def setup_page(page, context, **kwargs):
        await page.route('**/*', public_request)
        return page

    async with AsyncWebCrawler(config=BrowserConfig(headless=True, verbose=False, ignore_https_errors=False)) as crawler:
        crawler.crawler_strategy.set_hook('on_page_context_created', setup_page)
        session = f'place-photo-{provider}-{time.time_ns()}'
        for page_number in range(1, page_budget + 1):
            if time.monotonic() >= deadline:
                break
            url = search_url if provider == 'google' or album else search_url + f'&page={page_number}'
            search_config = CrawlerRunConfig(
                cache_mode=CacheMode.BYPASS, page_timeout=20000, verbose=False,
                session_id=session, js_only=provider == 'google' and page_number > 1,
                js_code=helper._crawl4ai_search_js(page_number) if provider == 'google' else None,
                scan_full_page=provider == 'flickr', max_scroll_steps=4,
                delay_before_return_html=0.5,
                # The configured CSE widget is the skill's explicit rendering
                # exception. Flickr and all linked sources respect robots.txt.
                check_robots_txt=provider != 'google',
            )
            try:
                result = await asyncio.wait_for(
                    crawler.arun(url=url, config=search_config),
                    timeout=min(25, max(0.1, deadline - time.monotonic())),
                )
            except Exception as error:
                logger.info('%s photo browser search unavailable: %s', provider, type(error).__name__)
                break
            if not result.success:
                logger.info('%s photo browser search unavailable (HTTP %s)', provider, result.status_code)
                break
            cards = (helper.parse_crawl4ai_image_results(result.html or '') if provider == 'google'
                     else _flickr_cards(result.html or '', url))
            album_context = ''
            if album:
                parser = helper.PageParser(url)
                parser.feed(result.html or '')
                album_context = parser.output()['title']
                if not helper._crawl4ai_location_matches(album_context, place):
                    break
                # The verified album supplies location, never capture dates.
                album_context = f'{album_context} (album location: {url})'
            pending = []
            for card in cards:
                if provider == 'google' and not helper._crawl4ai_location_matches(
                        ' '.join((card.get('title', ''), card.get('text', ''))), place):
                    continue
                source = card.get('source_url')
                if not source or source in seen_sources:
                    continue
                seen_sources.add(source)
                try:
                    _, host, port = helper.valid_url(source)
                    await asyncio.to_thread(helper.public_addresses, host, port)
                except (helper.ResearchError, ValueError, OSError):
                    continue
                pending.append(source)
                if len(seen_sources) >= source_budget:
                    break
            if not pending:
                if not cards:
                    break
                continue
            for source in pending:
                if time.monotonic() >= deadline:
                    return items[:limit]
                try:
                    detail = await asyncio.wait_for(crawler.arun(url=source, config=CrawlerRunConfig(
                        cache_mode=CacheMode.BYPASS, page_timeout=12000, verbose=False,
                        check_robots_txt=True, delay_before_return_html=0.2,
                    )), timeout=min(15, max(0.1, deadline - time.monotonic())))
                    if detail.success:
                        items.extend(_source_items(detail.html or '', source, place, period,
                                                   location_context=album_context))
                except Exception as error:
                    logger.info('%s photo source unavailable: %s', provider, type(error).__name__)
                    continue
                items = _deduplicate(items)
                if len(items) >= limit:
                    return items[:limit]
            if len(seen_sources) >= source_budget:
                break
    return items[:limit]


def _discovery_queries(provider: str, place: str, period: str, search_url: str) -> list[tuple[str, bool]]:
    from .place_photos import _localized_photo_query, _period_bounds, _place_terms
    queries = [(search_url, False)]
    parsed = urlsplit(search_url)
    for term in _place_terms(place)[1:]:
        params = parse_qs(parsed.query)
        params['q' if provider == 'google' else 'text'] = [_localized_photo_query(term, period)]
        url = urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urlencode(params, doseq=True), ''))
        if (url, False) not in queries:
            queries.append((url, False))
    bounds = _period_bounds(period)
    if provider == 'flickr' and re.search(r'\bchengde\b|承德', place, re.I) and bounds and bounds[0] <= 1984 and bounds[1] >= 1983:
        queries.append(('https://www.flickr.com/photos/kattebelletje/albums/72157614775600805/', True))
    return queries[:MAX_SEARCH_PAGES]


async def _browse(provider: str, place: str, period: str, search_url: str, *, limit: int = 10,
                  timeout: float = BROWSE_TIMEOUT) -> list[dict]:
    from .place_photos import _deduplicate, _mix_sources
    queries = _discovery_queries(provider, place, period, search_url)
    # Independent language/album searches run together, sharing fixed budgets.
    # Each retains its own browser session; CSE pagination cannot cross queries.
    results = await asyncio.gather(*(
        _browse_query(provider, place, period, url, limit=limit, timeout=timeout,
                      page_budget=MAX_SEARCH_PAGES // len(queries) + (index < MAX_SEARCH_PAGES % len(queries)),
                      source_budget=MAX_SOURCE_PAGES // len(queries), album=album)
        for index, (url, album) in enumerate(queries)
    ), return_exceptions=True)
    return _deduplicate(_mix_sources([item for result in results if isinstance(result, list)
                                     for item in result]))[:limit]


def crawl_place_photos(provider: str, place: str, period: str, *, limit: int = 10,
                       timeout: float = BROWSE_TIMEOUT) -> list[dict]:
    """Run in the catalogue thread pool; a browser failure cannot hide other sources."""
    url = _search_url(provider, place, period)
    if not url:
        return []
    async def bounded():
        return await asyncio.wait_for(_browse(provider, place, period, url, limit=limit, timeout=timeout), timeout=timeout)
    try:
        return asyncio.run(bounded())
    except Exception as error:
        # URLs can contain search details; log only provider/type, never credentials.
        logger.warning('%s photo browser unavailable: %s', provider, type(error).__name__)
        return []
