"""Keyless place-photo discovery through public, browser-rendered pages."""
from __future__ import annotations

import asyncio
from contextlib import nullcontext
from datetime import datetime
from functools import lru_cache
import hashlib
import importlib.util
import logging
from pathlib import Path
import re
import time
from threading import BoundedSemaphore
from urllib.parse import parse_qs, unquote, urlencode, urlsplit, urlunsplit
from zoneinfo import ZoneInfo

from .place_photos import PhotoResearchUnavailable, photo_failure_reason

logger = logging.getLogger(__name__)
MAX_SEARCH_PAGES = 3
MAX_SOURCE_PAGES = 12
BROWSE_TIMEOUT = 90
# Standalone callers retain a bounded fallback; the app uses the warm worker.
_browser_slot = BoundedSemaphore(1)
_warm_runtime = None


def _crawl_failure(result):
    headers = getattr(result, 'response_headers', {}) or {}
    if headers.get('X-Robots-Status') or 'robots.txt' in (getattr(result, 'error_message', '') or ''):
        return 'robots_denied'
    status = getattr(result, 'status_code', None)
    return f'http_{status}' if status else 'network_error'


@lru_cache(maxsize=1)
def _research():
    # Reuse the skill's parsers and URL checks, without creating a local run or
    # importing its candidates as licensed book assets.
    path = Path(__file__).resolve().parents[2] / 'skills/memoir-place-photo-research/scripts/photo_research.py'
    spec = importlib.util.spec_from_file_location('place_photo_research', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _search_url(provider: str, place: str, period: str) -> str:
    from .place_photos import _configured_env, _google_query, _localized_photo_query
    if provider == 'flickr':
        return 'https://www.flickr.com/search/?' + urlencode({'text': _localized_photo_query(place, period)})
    query = _google_query(place, period, include_decade=True)
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
        match = re.fullmatch(r'(/photos/[^/]+/\d+)(?:/in/[^/]+)?/?', url.path)
        if match:
            source = 'https://www.flickr.com' + match[1] + '/'
            cards[source] = {'source_url': source, 'title': link['text']}
    return list(cards.values())


def _json_ld_photo_records(value) -> list[dict]:
    """Collect photo nodes using the same bounded traversal as source extraction."""
    records = []

    def visit(node, depth=0):
        if depth > 10:
            return
        if isinstance(node, list):
            for child in node[:150]:
                visit(child, depth + 1)
        elif isinstance(node, dict):
            kinds = node.get('@type', [])
            if isinstance(kinds, str):
                kinds = [kinds]
            if (isinstance(kinds, list)
                    and any(isinstance(kind, str) and kind in {'Photograph', 'ImageObject'}
                            for kind in kinds)):
                records.append(node)
            for child in node.values():
                visit(child, depth + 1)

    visit(value)
    return records


def _item_locality_matches(value: str, requested: str) -> bool:
    return _research()._crawl4ai_item_locality_matches(value, requested)


def _source_items(source_html: str, source_url: str, place: str, period: str,
                  *, location_context: str = '') -> list[dict]:
    """Use source captions and capture metadata; page/upload dates cannot date photos."""
    from .place_photos import ANY_PHOTO_DATE, _coordinates, _date_matches, _google_license, _photo_period_bounds, _text
    from .place_photo_sources import source_registry_id, usage_permissions
    from .place_photo_expansion import conflicting_item_locality
    helper = _research()
    any_date = period == ANY_PHOTO_DATE
    parser = helper.PageParser(source_url)
    parser.feed(source_html)
    page = parser.output()
    meta = {item.get('property') or item.get('name'): item.get('content', '') for item in page['metadata']}
    title = meta.get('og:title') or page['title']
    description = meta.get('og:description') or meta.get('description') or ''
    context = ' '.join((title, description))
    is_flickr = urlsplit(source_url).hostname in {'www.flickr.com', 'flickr.com'}
    item_location = ''
    flickr_item = re.match(r'/photos/([^/]+)/\d+(?:/|$)', urlsplit(source_url).path) if is_flickr else None
    if flickr_item:
        owner = flickr_item[1]
        # These links describe this photo. Album years and tags may establish
        # place, but never supply capture dates or unrelated page context.
        item_location = ' '.join(link['text'] for link in page['links']
            if urlsplit(link['url']).hostname in {'www.flickr.com', 'flickr.com'}
            and (urlsplit(link['url']).path.startswith('/photos/tags/')
                 or re.fullmatch(r'/photos/' + re.escape(owner) + r'/albums/\d+/?',
                                 urlsplit(link['url']).path)))
    # An unrelated item on a relevant search page is still unrelated.
    location_evidence = ' '.join((context, item_location, location_context)).strip()
    page_matches = helper._crawl4ai_location_matches(location_evidence, place)

    photo_records = _json_ld_photo_records(page['json_ld'])
    # Nested gallery images are not primary unless the page explicitly selects their URL.
    photo = next((item for document in page['json_ld']
                  for item in (document if isinstance(document, list) else [document])
                  if item in photo_records), {})
    photo_by_url = {}
    photos_by_url = {}
    for record in photo_records:
        record_url = helper._crawl4ai_image_url(record.get('contentUrl') or record.get('url'))
        if record_url:
            photo_by_url[record_url] = record
            photos_by_url.setdefault(record_url, []).append(record)
    photo = photo_by_url.get(helper._crawl4ai_image_url(meta.get('og:image'))) or photo
    taken = _text(photo.get('dateTaken') or photo.get('dateCreated'))
    if not taken:
        # Flickr exposes this separately from its "Uploaded on" timestamp.
        match = re.search(r'Taken (?:on|in)\s+((?:[A-Za-z]+\s+(?:\d{1,2},?\s+)?)?(?:18|19|20)\d{2})',
                          page['text_excerpt'], re.I)
        taken = match.group(1) if match else ''
    if not taken:
        for key in ('dateTaken', 'date_taken', 'exif:DateTimeOriginal'):
            if meta.get(key):
                taken = meta[key]
                break
    source_host = urlsplit(source_url).hostname or ''
    source_path = unquote(urlsplit(source_url).path)
    source_title = parse_qs(urlsplit(source_url).query).get('title', [''])[0]
    mediawiki_file = ((source_host == 'commons.wikimedia.org' or source_host.endswith('.wikipedia.org'))
                     and bool(re.search(r'/(?:File|文件|檔案):|^(?:File|文件|檔案):', source_path + '\n' + source_title, re.I | re.M)))
    if not taken and mediawiki_file:
        # MediaWiki's file-description Date field is separate from upload and
        # file-history timestamps. Read only that explicit image metadata cell.
        match = re.search(r'<td\b[^>]*\bid=["\']fileinfotpl_date["\'][^>]*>.*?</td>\s*<td\b[^>]*>(.*?)</td>',
                          source_html, re.I | re.S)
        if match:
            day = re.search(r'\bdatetime=["\']([^"\']+)', match[1], re.I)
            taken = day[1] if day else _text(match[1]).split(',')[0].strip()
            for format in ('%d %B %Y', '%d %b %Y', '%Y年%m月%d日'):
                try:
                    taken = datetime.strptime(taken, format).date().isoformat()
                    break
                except ValueError:
                    pass
    if mediawiki_file and not taken and not any_date:
        return []
    # A year in the item title/caption is a source assertion; a whole article's
    # publication year and recommendation text are deliberately excluded.
    bounds = _photo_period_bounds(period)
    temporal = {
        'mode': 'historical_range',
        'start': f'{bounds[0]:04d}-01-01' if bounds else '2000-01-01',
        'end': f'{bounds[1]:04d}-12-31' if bounds else '2000-12-31',
    }
    if any_date:
        temporal = {'mode': 'any_time'}
        if taken and not _date_matches(taken, period):
            return []
    if not period:
        temporal = helper.normalize_period(None, datetime.now(ZoneInfo('Australia/Sydney')).date())
    primary_record_url = helper._crawl4ai_image_url(photo.get('contentUrl') or photo.get('url'))
    records_for_primary = photos_by_url.get(primary_record_url, [photo])
    field_records = []
    for record in records_for_primary:
        fields = {key: _text(record.get(key)) for key in
                  ('name', 'caption', 'description', 'dateTaken', 'dateCreated', 'datePublished', 'uploadDate')
                  if _text(record.get(key))}
        field_records.append(fields)
    if field_records and any(field_records):
        scene_date = helper._reconcile_capture_dates(field_records, temporal)
    else:
        scene_date = helper._crawl4ai_scene_date(taken or context, temporal)
    if period and not any_date and (not scene_date or (taken and not _date_matches(taken, period))):
        scene_date = None
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
    creator = photo.get('creator') or photo.get('author') or {}
    attribution = _text(creator.get('name') if isinstance(creator, dict) else creator)
    source_licence_url = _text(meta.get('license'))
    if not source_licence_url and mediawiki_file:
        # Commons' hidden file licence is distinct from the page/footer licence.
        match = re.search(r'<[^>]+class=["\'][^"\']*\blicensetpl_link\b[^"\']*["\'][^>]*>(.*?)</',
                          source_html, re.I | re.S)
        source_licence_url = _text(match[1]) if match else ''
    if not source_licence_url and is_flickr:
        source_licence_url = next((link['url'] for link in page['links']
            if urlsplit(link['url']).hostname == 'creativecommons.org'
            and urlsplit(link['url']).path.startswith('/licenses/')), '')
    licence_url = _text(photo.get('license')) or source_licence_url
    image_urls = []
    primary = photo.get('contentUrl') or meta.get('og:image')
    if mediawiki_file:
        original = next((link['url'] for link in page['links']
                         if re.search(r'original file|原始文件', link['text'], re.I)), None)
        primary = original or primary
    if primary and (scene_date or any_date) and page_matches and (is_flickr or mediawiki_file or location_context):
        image_urls.append((primary, title, scene_date))
    if not is_flickr and not mediawiki_file:
        images = helper._crawl4ai_source_images(
            {'url': source_url, 'html': source_html}, {'title': title, 'text': context},
            {'place': place, 'temporal': temporal},
        )
        image_urls.extend((image['image_url'], image['title'], image['scene_date']) for image in images)
    elif not primary and (scene_date or any_date):
        for image in page['image_candidates']:
            caption = ' '.join((image['alt'], image['figure_text']))
            if (helper.NON_PHOTO.search(caption)
                    or not helper._crawl4ai_location_matches(caption, place)):
                continue
            image_urls.extend((url, caption, scene_date) for url in image['candidate_urls'])
    point = _coordinates(photo)
    if point is None:
        point = _coordinates({'latitude': meta.get('place:location:latitude') or meta.get('geo:lat'),
                              'longitude': meta.get('place:location:longitude') or meta.get('geo:long')})
    if point is None:
        position = meta.get('geo.position') or meta.get('ICBM') or ''
        values = re.fullmatch(r'\s*(-?\d+(?:\.\d+)?)\s*[;,]\s*(-?\d+(?:\.\d+)?)\s*', position)
        if not values and mediawiki_file:
            values = re.search(r'class=["\'][^"\']*geo(?:-decimal)?[^"\']*["\'][^>]*>\s*(-?\d+(?:\.\d+)?)\s*[;,]\s*(-?\d+(?:\.\d+)?)', source_html, re.I)
        if values:
            point = _coordinates({'latitude': values[1], 'longitude': values[2]})
    if point is None and mediawiki_file:
        values = re.search(r'params=(\d+(?:\.\d+)?)(?:_(\d+(?:\.\d+)?))?(?:_(\d+(?:\.\d+)?))?_([NS])_(\d+(?:\.\d+)?)(?:_(\d+(?:\.\d+)?))?(?:_(\d+(?:\.\d+)?))?_([EW])(?:_|[&"\'])', unquote(source_html), re.I)
        if values:
            latitude = sum(float(values[i] or 0) / divisor for i, divisor in ((1, 1), (2, 60), (3, 3600)))
            longitude = sum(float(values[i] or 0) / divisor for i, divisor in ((5, 1), (6, 60), (7, 3600)))
            point = _coordinates({'latitude': latitude * (-1 if values[4].upper() == 'S' else 1),
                                  'longitude': longitude * (-1 if values[8].upper() == 'W' else 1)})
    items = []
    for observed, caption, image_date in image_urls:
        image = helper._crawl4ai_image_url(observed)
        if not image or helper.NON_PHOTO.search(caption):
            continue
        if is_flickr:
            if not re.fullmatch(r'(?:live|farm\d+)\.staticflickr\.com', urlsplit(image).hostname or ''):
                continue
        image_photo = photo_by_url.get(image)
        if image_photo is not None:
            if conflicting_item_locality({'json_ld': [image_photo], 'title': image_photo.get('caption', '')},
                                         place, _item_locality_matches):
                continue
            image_licence_url = _text(image_photo.get('license')) or source_licence_url
        elif image == helper._crawl4ai_image_url(primary):
            image_licence_url = licence_url
        else:
            image_licence_url = source_licence_url
        image_licence = _google_license({'license': image_licence_url})
        if image_licence_url and not image_licence:
            continue
        image_point = _coordinates(image_photo or {})
        if image_point is None and observed == primary:
            image_point = point
        image_creator = (image_photo or {}).get('creator') or (image_photo or {}).get('author') or ''
        creators = image_creator if isinstance(image_creator, list) else [image_creator]
        image_attribution = ', '.join(filter(None, (_text(creator.get('name') if isinstance(creator, dict) else creator)
                                                    for creator in creators)))
        if not image_attribution and image == helper._crawl4ai_image_url(primary):
            image_attribution = attribution
        image_location = helper._crawl4ai_photo_location(image_photo or {})
        identifier = hashlib.sha256(f'{source_url}\n{image}'.encode()).hexdigest()[:24]
        items.append({
            'asset_id': 'crawl4ai-' + identifier, 'kind': 'image', 'title': _text(caption),
            'source_url': source_url, 'image_url': image, 'original_url': image,
            'location': place, 'attribution': image_attribution or urlsplit(source_url).hostname,
            'location_evidence': ' '.join(filter(None, (location_evidence, image_location, _text(caption)))),
            'date_expression': (
                '' if image_date is None else image_date['start'] if image_date['start'] == image_date['end'] else
                image_date['start'][:7] if image_date['precision'] == 'month' else
                image_date['start'][:4] if image_date['start'][:4] == image_date['end'][:4] else
                image_date['start'][:4] + '-' + image_date['end'][:4]),
            'scene_date_range': image_date,
            'date_basis': image_date.get('basis','source_caption') if image_date else 'unknown',
            **(image_point or {}),
            'license': image_licence[0] if image_licence else 'Unknown', 'license_url': image_licence_url,
            'source_registry_id': source_registry_id(source_url),
            'usage_permissions': usage_permissions(bool(image_licence)),
            'memory_reference_only': True,
            'allowed_actions': {'embed': bool(image_licence), 'memory_reference': True, 'download': False,
                                'print': False, 'publish': False},
        })
    return items


async def _browse_query(provider: str, place: str, period: str, search_url: str, *, limit: int = 10,
                        timeout: float = BROWSE_TIMEOUT, page_budget: int = MAX_SEARCH_PAGES,
                        source_budget: int = MAX_SOURCE_PAGES, album: bool = False,
                        crawler=None, source_slots=None, on_items=None) -> list[dict]:
    from crawl4ai import AsyncWebCrawler, BrowserConfig, CacheMode, CrawlerRunConfig
    from .place_photos import _deduplicate
    helper = _research()
    source_period = period
    seen_sources, items, source_errors = set(), [], []
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

    source_slots = source_slots or asyncio.Semaphore(2)
    manager = nullcontext(crawler) if crawler is not None else AsyncWebCrawler(
        config=BrowserConfig(headless=True, verbose=False, ignore_https_errors=False))
    async with manager as crawler:
        crawler.crawler_strategy.set_hook('on_page_context_created', setup_page)
        session = f'place-photo-{provider}-{time.time_ns()}'
        for page_number in range(1, page_budget + 1):
            if time.monotonic() >= deadline:
                if items:
                    return items[:limit]
                raise PhotoResearchUnavailable(provider, 'timeout')
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
                if items:
                    return items[:limit]
                raise PhotoResearchUnavailable(provider, photo_failure_reason(error)) from None
            if not result.success:
                logger.info('%s photo browser search unavailable (HTTP %s)', provider, result.status_code)
                if items:
                    return items[:limit]
                raise PhotoResearchUnavailable(provider, _crawl_failure(result))
            if provider == 'google' and re.search(
                    r'please verify that you are not a robot|unusual traffic from your computer network',
                    result.html or '', re.I):
                if items:
                    return items[:limit]
                raise PhotoResearchUnavailable(provider, 'verification_required')
            cards = (helper.parse_crawl4ai_image_results(result.html or '') if provider == 'google'
                     else _flickr_cards(result.html or '', url))
            if provider == 'google' and not cards:
                markup = result.html or ''
                if not re.search(r'class=["\'][^"\']*\bgs-no-results-result\b', markup, re.I):
                    if items:
                        return items[:limit]
                    reason = 'search_error' if re.search(r'class=["\'][^"\']*\bgs-error\b', markup, re.I) else 'widget_not_ready'
                    raise PhotoResearchUnavailable(provider, reason)
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
            async def inspect_source(source):
                async with source_slots:
                    if time.monotonic() >= deadline:
                        source_errors.append('timeout')
                        return []
                    try:
                        detail = await asyncio.wait_for(crawler.arun(url=source, config=CrawlerRunConfig(
                            cache_mode=CacheMode.BYPASS, page_timeout=12000, verbose=False,
                            check_robots_txt=True, delay_before_return_html=0.2,
                        )), timeout=min(15, max(0.1, deadline - time.monotonic())))
                        if detail.success:
                            found = [{**item, 'providers': ['google', 'cse'] if provider == 'google' else [provider]}
                                for item in _source_items(
                                detail.html or '', source, place, source_period,
                                location_context=album_context) if item['allowed_actions']['embed']]
                            from .place_photo_fingerprints import image_fingerprint
                            for item in found:
                                if time.monotonic() >= deadline:
                                    break
                                item.update(await asyncio.to_thread(image_fingerprint, item['image_url']))
                            return found
                        source_errors.append(_crawl_failure(detail))
                    except Exception as error:
                        logger.info('%s photo source unavailable: %s', provider, type(error).__name__)
                        source_errors.append(photo_failure_reason(error))
                    return []

            tasks = [asyncio.create_task(inspect_source(source)) for source in pending]
            try:
                for completed in asyncio.as_completed(tasks):
                    found = await completed
                    items = _deduplicate(items + found)
                    if found and on_items:
                        on_items(found)
                    if len(items) >= limit:
                        return items[:limit]
            finally:
                for task in tasks:
                    if not task.done():
                        task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
            if len(seen_sources) >= source_budget:
                break
    # A denied original cannot establish failure for later search pages.
    if not items and source_errors:
        raise PhotoResearchUnavailable(failures=[{
            'provider': provider, 'reason': reason, 'scope': 'source',
        } for reason in dict.fromkeys(source_errors)])
    return items[:limit]


def _discovery_queries(provider: str, place: str, period: str, search_url: str) -> list[tuple[str, bool]]:
    from .place_photos import _localized_photo_query, _period_bounds, _place_terms
    queries = [(search_url, False)]
    if provider == 'google':
        # The CSE query already combines verified aliases and years with OR.
        return queries
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
                  timeout: float = BROWSE_TIMEOUT, crawler=None, source_slots=None, on_items=None) -> list[dict]:
    if crawler is None:
        from crawl4ai import AsyncWebCrawler, BrowserConfig
        async with AsyncWebCrawler(config=BrowserConfig(
                headless=True, verbose=False, ignore_https_errors=False)) as opened:
            return await _browse(provider, place, period, search_url, limit=limit, timeout=timeout,
                                 crawler=opened, source_slots=asyncio.Semaphore(2), on_items=on_items)
    from .place_photos import _deduplicate, _mix_sources
    queries = _discovery_queries(provider, place, period, search_url)
    if provider == 'google':
        from .place_photos import _configured_env, _period_bounds
        if _configured_env('MEMOIR_PHOTO_EXPANSION').lower() in {'1', 'true', 'yes'}:
            from .place_photo_expansion import google_search_urls, historical_queries
            primary = parse_qs(urlsplit(search_url).query).get('q', [''])[0]
            expanded = historical_queries(
                primary, _research()._crawl4ai_place_query(place), _period_bounds(period),
                max_queries=MAX_SEARCH_PAGES,
            )
            queries = [(url, False) for url in google_search_urls(search_url, expanded)]
    deadline = time.monotonic() + timeout
    items, failures = [], []
    for index, (url, album) in enumerate(queries):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        try:
            items.extend(await _browse_query(
                provider, place, period, url, limit=limit, timeout=remaining,
                page_budget=MAX_SEARCH_PAGES // len(queries) + (index < MAX_SEARCH_PAGES % len(queries)),
                source_budget=MAX_SOURCE_PAGES // len(queries), album=album,
                crawler=crawler, source_slots=source_slots, on_items=on_items,
            ))
        except Exception as error:
            logger.warning('%s photo browser query unavailable: %s', provider, type(error).__name__)
            failures.extend(error.failures if isinstance(error, PhotoResearchUnavailable)
                            else [{'provider': provider, 'reason': photo_failure_reason(error)}])
            if any(failure['reason'] in {'verification_required', 'robots_denied'}
                   and failure.get('scope') != 'source' for failure in failures):
                break
        if len(_deduplicate(items)) >= limit:
            break
    if not items and failures:
        raise PhotoResearchUnavailable(failures=failures)
    return _deduplicate(_mix_sources(items))[:limit]


def crawl_place_photos(provider: str, place: str, period: str, *, limit: int = 10,
                       timeout: float = BROWSE_TIMEOUT, on_items=None) -> list[dict]:
    """Run in the catalogue thread pool; a browser failure cannot hide other sources."""
    url = _search_url(provider, place, period)
    if not url:
        return []
    if _warm_runtime is not None:
        future = asyncio.run_coroutine_threadsafe(
            _warm_runtime.search(provider, place, period, url, limit=limit, timeout=timeout, on_items=on_items),
            _warm_runtime.loop,
        )
        try:
            return future.result(timeout=timeout * 2 + 5)
        except Exception as error:
            future.cancel()
            logger.warning('%s photo browser unavailable: %s', provider, type(error).__name__)
            if isinstance(error, PhotoResearchUnavailable):
                raise
            raise PhotoResearchUnavailable(provider, photo_failure_reason(error)) from None
    async def bounded():
        return await asyncio.wait_for(_browse(provider, place, period, url, limit=limit,
                                             timeout=timeout, on_items=on_items), timeout=timeout)
    # Acquire in this synchronous catalogue thread, before creating an event
    # loop: cancelling an async waiter must never leak a browser slot.
    if not _browser_slot.acquire(timeout=timeout):
        logger.warning('%s photo browser unavailable: busy', provider)
        raise PhotoResearchUnavailable(provider, 'busy')
    try:
        return asyncio.run(bounded())
    except Exception as error:
        # URLs can contain search details; log only provider/type, never credentials.
        logger.warning('%s photo browser unavailable: %s', provider, type(error).__name__)
        if isinstance(error, PhotoResearchUnavailable):
            raise
        raise PhotoResearchUnavailable(provider, photo_failure_reason(error)) from None
    finally:
        _browser_slot.release()


class WarmPhotoBrowser:
    """One worker-owned Chromium process; two original pages at a time."""

    async def start(self):
        from crawl4ai import AsyncWebCrawler, BrowserConfig
        self.loop = asyncio.get_running_loop()
        self.lock = asyncio.Lock()
        self.source_slots = asyncio.Semaphore(2)
        self.crawler = AsyncWebCrawler(config=BrowserConfig(
            headless=True, verbose=False, ignore_https_errors=False))
        await self.crawler.start()
        return self

    async def search(self, provider, place, period, url, *, limit, timeout, on_items=None):
        async with self.lock:
            try:
                return await asyncio.wait_for(_browse(
                    provider, place, period, url, limit=limit, timeout=timeout,
                    crawler=self.crawler, source_slots=self.source_slots, on_items=on_items,
                ), timeout)
            finally:
                # Crawl4AI caches contexts by run configuration. Clear their
                # cookies/storage between public searches, retaining Chromium.
                manager = self.crawler.crawler_strategy.browser_manager
                for context in list(manager.contexts_by_config.values()):
                    for page in context.pages:
                        await page.unroute_all(behavior='ignoreErrors')
                    await context.close()
                manager.contexts_by_config.clear()
                manager.sessions.clear()

    async def close(self):
        await self.crawler.close()


def set_warm_browser(runtime):
    global _warm_runtime
    _warm_runtime = runtime
