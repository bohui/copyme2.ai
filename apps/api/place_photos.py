"""Search public photo catalogues using only coarse place and period queries."""
import html
import os
import re
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import unquote, urlparse

import httpx

MAX_RESULTS = 10
SEARCH_LIMIT = 50
HEADERS = {'User-Agent': 'MemorySpark/1.0 (memoir place reference images)'}
NON_PHOTO = re.compile(r'\b(banknotes?|coins?|currency|stamps?|maps?|paintings?|illustrations?|drawings?|engravings?)\b|纸币|鈔票|钞票|邮票|绘画|地圖|地图', re.I)


def _text(value) -> str:
    if isinstance(value, list):
        value = ' '.join(str(item) for item in value)
    return html.unescape(re.sub(r'<[^>]*>', '', str(value or '')))[:4000]


def _years(value: str) -> list[int]:
    return [int(year) for year in re.findall(r'(?<!\d)((?:18|19|20)\d{2})(?!\d)', value)]


def _period_bounds(period: str) -> tuple[int, int] | None:
    years = _years(period)
    if not years:
        return None
    if re.search(r'(?:18|19|20)\d0\s*(?:s|年代)', period, re.I):
        return years[0], years[0] + 9
    return min(years), max(years)


def _date_matches(date: str, period: str) -> bool:
    if not period.strip():
        return True
    bounds = _period_bounds(period)
    years = _years(date)
    # Unresolved periods/dates must not silently turn into unrestricted results.
    if not bounds or not years or re.search(r'circa|\bca\.?\s|before|after|unknown|约|不详|以前|以后', date, re.I):
        return False
    scene = _period_bounds(date)
    return bool(scene and bounds[0] <= scene[0] <= scene[1] <= bounds[1])


def _search_queries(place: str, period: str) -> list[str]:
    clean = ' '.join(place.replace('"', ' ').split())
    bounds = _period_bounds(period)
    if bounds:
        years = ' OR '.join(str(year) for year in range(bounds[0], min(bounds[1], bounds[0] + 99) + 1))
        return [f'"{clean}" filetype:bitmap ({years})', f'"{clean}" filetype:bitmap']
    return [f'"{clean}" filetype:bitmap', clean]


def _get(url: str, params: dict) -> dict:
    response = httpx.get(url, params=params, headers=HEADERS, timeout=8)
    response.raise_for_status()
    return response.json()


def _https_host(url: str, hosts: set[str]) -> bool:
    parsed = urlparse(url)
    return parsed.scheme == 'https' and parsed.hostname in hosts and not parsed.username and not parsed.password


def _commons(place: str, period: str) -> list[dict]:
    items = []
    for query in _search_queries(place, period):
        data = _get('https://commons.wikimedia.org/w/api.php', {
            'action': 'query', 'format': 'json', 'generator': 'search',
            'gsrsearch': query, 'gsrnamespace': 6, 'gsrlimit': SEARCH_LIMIT,
            'prop': 'imageinfo', 'iiprop': 'url|mime|extmetadata|sha1', 'iiurlwidth': 640,
        })
        for page in data.get('query', {}).get('pages', {}).values():
            info = (page.get('imageinfo') or [{}])[0]
            metadata = info.get('extmetadata', {})
            def value(key):
                return _text(metadata.get(key, {}).get('value', ''))
            title = page.get('title', '').removeprefix('File:')
            caption = ' '.join((title, value('ImageDescription'), value('Categories')))
            date = value('DateTimeOriginal')
            if NON_PHOTO.search(caption) or not _date_matches(date, period):
                continue
            license_name = value('LicenseShortName')
            if license_name not in {'CC0', 'CC0 1.0', 'Public domain', 'CC BY 4.0', 'CC BY-SA 4.0'}:
                continue
            image, source = info.get('thumburl', ''), info.get('descriptionurl', '')
            if (not _https_host(image, {'upload.wikimedia.org'})
                    or not _https_host(source, {'commons.wikimedia.org'})
                    or info.get('mime') not in {'image/jpeg', 'image/png', 'image/webp'}):
                continue
            items.append({
                'asset_id': f"commons-{page.get('pageid')}", 'kind': 'image',
                'title': title, 'image_url': image, 'source_url': source, 'location': place,
                'attribution': value('Artist'), 'license': license_name,
                'license_url': value('LicenseUrl'), 'date_expression': date,
                'original_url': info.get('url', image), 'content_hash': info.get('sha1', ''),
                'allowed_actions': {'embed': True, 'download': False, 'print': False},
            })
        if len(_deduplicate(items)) >= MAX_RESULTS:
            break
    return items


def _loc(place: str, period: str) -> list[dict]:
    """Only item-level photographic records with an explicit reuse statement."""
    params = {'fo': 'json', 'q': place, 'c': SEARCH_LIMIT, 'fa': 'online-format:image'}
    bounds = _period_bounds(period)
    if bounds:
        params['dates'] = f'{bounds[0]}/{bounds[1]}'
    data = _get('https://www.loc.gov/photos/', params)
    def inspect(record):
        source = record.get('id', '')
        if (record.get('access_restricted') or not _date_matches(_text(record.get('date')), period)
                or NON_PHOTO.search(_text(record.get('title')))
                or not _https_host(source, {'www.loc.gov', 'loc.gov'})):
            return record
        item = record.get('item') or {}
        if not item.get('medium') or not item.get('rights'):
            try:
                detail = _get(source, {'fo': 'json'}).get('item') or {}
                # The full item wraps bibliographic fields in its own item key.
                item = detail.get('item') or detail
                return {**record, 'item': item}
            except (httpx.HTTPError, ValueError, KeyError, TypeError):
                pass
        return record

    candidates = [record for record in data.get('results', [])
                  if _date_matches(_text(record.get('date')), period)
                  and not NON_PHOTO.search(_text(record.get('title')))]
    with ThreadPoolExecutor(max_workers=4) as pool:
        records = list(pool.map(inspect, candidates[:20]))
    items = []
    for record in records:
        title, date = _text(record.get('title')), _text(record.get('date'))
        if record.get('access_restricted') or NON_PHOTO.search(title) or not _date_matches(date, period):
            continue
        source = record.get('id', '')
        if not _https_host(source, {'www.loc.gov', 'loc.gov'}):
            continue
        # Search summaries may omit medium and rights. Do not invent either or
        # treat unrestricted online access as copyright permission.
        item = record.get('item') or {}
        medium = _text(item.get('medium', []))
        rights = _text(item.get('rights', []))
        if not re.search(r'photograph|negative|transparenc', medium, re.I):
            continue
        if not re.search(r'no known restrictions on publication|public domain', rights, re.I):
            continue
        images = [url for url in record.get('image_url', []) if isinstance(url, str)]
        images = ['https:' + url if url.startswith('//') else url for url in images]
        images = [url for url in images if _https_host(url, {'tile.loc.gov', 'cdn.loc.gov', 'www.loc.gov'})]
        if not images:
            continue
        items.append({
            'asset_id': 'loc-' + source.rstrip('/').rsplit('/', 1)[-1], 'kind': 'image',
            'title': title, 'image_url': images[-1], 'source_url': source, 'location': place,
            'attribution': _text(record.get('contributor')) or 'Library of Congress',
            'license': rights, 'license_url': source, 'date_expression': date,
            'allowed_actions': {'embed': True, 'download': False, 'print': False},
        })
    return items



def _place_terms(place: str) -> list[str]:
    terms = [place.strip()]
    # Keep aliases geographically narrow: Jehol also named a much larger region.
    if re.search(r"\bchengde\b|承德", place, re.I):
        terms += ['Chengde', '承德']
    return list(dict.fromkeys(terms))


def _flickr(place: str, period: str) -> list[dict]:
    key = os.environ.get('FLICKR_API_KEY', '').strip()
    if not key:
        return []

    def call(method, **params):
        data = _get('https://api.flickr.com/services/rest/', {
            'method': method, 'api_key': key, 'format': 'json', 'nojsoncallback': 1, **params,
        })
        if data.get('stat') != 'ok':
            # Do not include the request URL: it contains the app credential.
            raise ValueError('Flickr API request failed')
        return data

    licences = call('flickr.photos.licenses.getInfo').get('licenses', {}).get('license', [])
    allowed = {}
    for licence in licences:
        url = licence.get('url', '')
        parsed = urlparse(url)
        if (parsed.scheme in {'http', 'https'} and parsed.hostname == 'creativecommons.org'
                and re.fullmatch(r'/(?:licenses/(?:by|by-sa)/(?:2\.0|2\.5|3\.0|4\.0)|publicdomain/(?:zero|mark)/1\.0)/?', parsed.path)):
            allowed[str(licence['id'])] = licence
    if not allowed:
        return []
    bounds = _period_bounds(period)
    params = {'per_page': 100, 'sort': 'relevance', 'media': 'photos', 'content_types': '0',
              'safe_search': 1, 'license': ','.join(allowed),
              'extras': 'description,license,date_taken,owner_name,tags,media,url_z,url_c'}
    if bounds:
        params.update(min_taken_date=f'{bounds[0]}-01-01 00:00:00',
                      max_taken_date=f'{bounds[1]}-12-31 23:59:59')
    items = []
    searches = [('flickr.photos.search', {'text': term}, False) for term in _place_terms(place)]
    # Verified photographer collection; each item's date and rights still gate it.
    if ('Chengde' in _place_terms(place) and bounds
            and bounds[0] <= 1984 and bounds[1] >= 1983):
        try:
            owner = call('flickr.urls.lookupUser', url='https://www.flickr.com/photos/kattebelletje/').get('user', {}).get('id')
        except (httpx.HTTPError, ValueError, KeyError, TypeError):
            owner = None
        if owner:
            searches.insert(0, ('flickr.photosets.getPhotos', {
                'photoset_id': '72157614775600805', 'user_id': owner,
            }, True))
    for method, search, album in searches:
        for page in range(1, 4):
            options = {key: params[key] for key in ('per_page', 'extras', 'media')} if album else params
            try:
                data = call(method, page=page, **search, **options).get('photoset' if album else 'photos', {})
            except (httpx.HTTPError, ValueError, KeyError, TypeError):
                break
            for photo in data.get('photo', []):
                date = _text(photo.get('datetaken'))
                description = _text((photo.get('description') or {}).get('_content'))
                caption = ' '.join((_text(photo.get('title')), description, _text(photo.get('tags'))))
                if (photo.get('media', 'photo') != 'photo' or NON_PHOTO.search(caption)
                        or not _date_matches(date, period)
                        or str(photo.get('datetakenunknown', '0')) != '0'
                        or (not album and not any(alias.casefold() in caption.casefold() for alias in _place_terms(place)))):
                    continue
                licence = allowed.get(str(photo.get('license')))
                image = photo.get('url_z') or photo.get('url_c') or ''
                host = urlparse(image).hostname or ''
                if (not licence or not _https_host(image, {host})
                        or not (host == 'live.staticflickr.com' or re.fullmatch(r'farm\d+\.staticflickr\.com', host))):
                    continue
                photo_id, owner = str(photo.get('id', '')), str(photo.get('owner') or (search.get('user_id') if album else ''))
                if not photo_id.isdigit() or not re.fullmatch(r'\d+@N\d+', owner):
                    continue
                items.append({
                    'asset_id': 'flickr-' + photo_id, 'kind': 'image',
                    'title': _text(photo.get('title')), 'image_url': image,
                    'source_url': f'https://www.flickr.com/photos/{owner}/{photo_id}/',
                    'location': place, 'attribution': _text(photo.get('ownername')) or owner,
                    'license': licence['name'], 'license_url': licence['url'],
                    'date_expression': date, 'date_basis': 'Flickr date taken',
                    'allowed_actions': {'embed': True, 'download': False, 'print': False},
                })
            if len(_deduplicate(items)) >= MAX_RESULTS:
                return items
            if page >= int(data.get('pages', 1)):
                break
    return items


def _deduplicate(items: list[dict]) -> list[dict]:
    unique, seen = [], set()
    for item in items:
        keys = {item['asset_id'], item['source_url'], unquote(item.get('original_url') or item['image_url']).split('#')[0]}
        if item.get('content_hash'):
            keys.add(item['content_hash'])
        if seen.intersection(keys):
            continue
        unique.append(item)
        seen.update(keys)
    return unique


def search_place_photos(place: str, period: str = '') -> list[dict]:
    if period.strip() and not _period_bounds(period):
        return []
    items, errors = [], []
    # Independent catalogues overlap their network waits; one failure must not
    # hide the other catalogue's usable photographs.
    providers = [_commons, _loc]
    if os.environ.get("FLICKR_API_KEY", "").strip():
        providers.insert(0, _flickr)
    with ThreadPoolExecutor(max_workers=len(providers)) as pool:
        futures = [pool.submit(provider, place, period) for provider in providers]
        for future in futures:
            try:
                items.extend(future.result())
            except (httpx.HTTPError, ValueError, KeyError, TypeError) as error:
                errors.append(error)
    if not items and len(errors) == len(futures):
        raise errors[-1]
    return _deduplicate(items)[:MAX_RESULTS]
