"""Search public photo catalogues using only coarse place and period queries."""
import hashlib
import html
import http.client
import math
import os
import re
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from itertools import zip_longest
from urllib.parse import parse_qsl, unquote, urlencode, urlparse, urlunparse
from zoneinfo import ZoneInfo

import httpx

MAX_RESULTS = 10
DISCOVERY_LIMIT = 50
SEARCH_LIMIT = 50
PHOTO_RADIUS_KM = 20
PHOTO_YEAR_TOLERANCE = 10
PHOTO_SEARCH_POLICY = 'place-fallback-gps-time-v8'
ANY_PHOTO_DATE = 'any-date'
GOOGLE_CSE_ENDPOINT = 'https://customsearch.googleapis.com/customsearch/v1'
GOOGLE_CSE_PAGE_SIZE = 10
GOOGLE_CSE_MAX_PAGES = 10
HEADERS = {'User-Agent': 'MemorySpark/1.0 (memoir place reference images)'}
NON_PHOTO = re.compile(r'\b(banknotes?|coins?|currency|stamps?|maps?|paintings?|illustrations?|drawings?|engravings?)\b|纸币|鈔票|钞票|邮票|绘画|地圖|地图', re.I)
HISTORICAL_PERIODS = {'old', 'historical', 'unspecified-historical', '老照片', '过去', '以前'}


class PhotoResearchUnavailable(ValueError):
    """Safe provider diagnostics, without request URLs or credentials."""
    def __init__(self, provider='', reason='unavailable', *, failures=None):
        self.failures = failures if failures is not None else [{'provider': provider, 'reason': reason}]
        super().__init__('Photo sources unavailable')


def photo_failure_reason(error):
    if isinstance(error, httpx.HTTPStatusError):
        return f'http_{error.response.status_code}'
    if isinstance(error, http.client.HTTPException):
        return 'network_error'
    if isinstance(error, (TimeoutError, httpx.TimeoutException)):
        return 'timeout'
    if isinstance(error, httpx.HTTPError):
        return 'network_error'
    return 'invalid_response'


def _text(value) -> str:
    if isinstance(value, list):
        value = ' '.join(str(item) for item in value)
    return html.unescape(re.sub(r'<[^>]*>', '', str(value or '')))[:4000]


def _configured_env(name: str) -> str:
    value = os.environ.get(name, '').strip()
    return '' if value.casefold() in {'', 'null', '<null>', 'none'} else value


def _years(value: str) -> list[int]:
    return [int(year) for year in re.findall(r'(?<!\d)((?:18|19|20)\d{2})(?!\d)', value)]


def _period_bounds(period: str, *, expand_bare_year: bool = True) -> tuple[int, int] | None:
    years = _years(period)
    if not years:
        return None
    if re.search(r'(?:18|19|20)\d0\s*(?:s|年代)', period, re.I):
        return years[0], years[0] + 9
    if expand_bare_year and re.fullmatch(r'\s*(?:18|19|20)\d{2}\s*', period):
        # A bare year from the memoir is the start of a ten-year visual
        # window. This keeps "1980" useful for a decade search while an
        # explicit range remains authoritative.
        return years[0], years[0] + 9
    return min(years), max(years)


def _is_historical_period(period: str) -> bool:
    return (period or '').strip().casefold() in HISTORICAL_PERIODS


def _photo_period_bounds(period: str) -> tuple[int, int] | None:
    bounds = _period_bounds(period)
    tolerance = _photo_year_tolerance(period)
    return (bounds[0] - tolerance, bounds[1] + tolerance) if bounds else None


def _photo_year_tolerance(period: str) -> int:
    bounds = _period_bounds(period)
    # Bare years retain their documented ten-year window; explicit ranges
    # and decades remain authoritative. Recognize year-only cues positively;
    # calendar dates and named months must not gain the nearby-year allowance.
    year_only = re.fullmatch(
        r'\s*(?:(?:about|around|circa|approximately|ca\.?|c\.)\s+|(?:大约|约|大概)\s*)?'
        r'(?:18|19|20)\d{2}\s*年?\s*(?:左右|前后|前後)?\s*', period, re.I)
    return PHOTO_YEAR_TOLERANCE if bounds and bounds[0] == bounds[1] and year_only else 0


def _date_matches(date: str, period: str, *, tolerance: int | None = None) -> bool:
    bounds = _period_bounds(period)
    if tolerance is None:
        tolerance = _photo_year_tolerance(period)
    years = _years(date)
    # Unresolved periods/dates must not silently turn into unrestricted results.
    any_date = period == ANY_PHOTO_DATE
    if not any_date and (not years or re.search(r'circa|\bca\.?\s|before|after|unknown|约|不详|以前|以后', date, re.I)):
        return False
    today = datetime.now(ZoneInfo('Australia/Sydney')).date()
    if years and max(years) > today.year:
        return False
    iso_date = re.fullmatch(r'(\d{4}-\d{2}-\d{2})(?:[T ].*)?', date.strip())
    if iso_date:
        try:
            if datetime.fromisoformat(iso_date[1]).date() > today:
                return False
        except ValueError:
            return False
    if any_date:
        return True
    if not period.strip():
        from .place_photo_browser import _research
        current = _research().normalize_period(None, datetime.now(ZoneInfo('Australia/Sydney')).date())
        exact = re.fullmatch(r'(\d{4}-\d{2}-\d{2})(?:[T ].*)?', date.strip())
        if not exact:
            try:
                captured = datetime.strptime(date.replace(',', '').strip(), '%B %d %Y').date().isoformat()
                exact = re.fullmatch(r'(\d{4}-\d{2}-\d{2})', captured)
            except ValueError:
                pass
        start = exact[1] if exact else f'{min(years):04d}-01-01'
        end = exact[1] if exact else f'{max(years):04d}-12-31'
        try:
            datetime.fromisoformat(start)
            datetime.fromisoformat(end)
        except ValueError:
            return False
        return current['start'] <= start <= end <= current['end']
    if not bounds:
        if not _is_historical_period(period):
            return False
        from .place_photo_browser import _research
        current = _research().normalize_period(None, datetime.now(ZoneInfo('Australia/Sydney')).date())
        scene = _period_bounds(date, expand_bare_year=False)
        if not scene:
            return False
        exact = re.fullmatch(r'(\d{4}-\d{2}-\d{2})(?:[T ].*)?', date.strip())
        end = exact[1] if exact else f'{scene[1]:04d}-12-31'
        return end < current['start']
    # A source caption containing only "1985" is an observed year, not a
    # request to expand another ten-year window.
    scene = _period_bounds(date, expand_bare_year=False)
    return bool(scene and bounds[0] - tolerance <= scene[0] <= scene[1] <= bounds[1] + tolerance)


def _coordinates(record: dict) -> dict | None:
    if not isinstance(record, dict):
        return None
    latitude = record.get('latitude', record.get('lat', record.get('GPSLatitude')))
    longitude = record.get('longitude', record.get('lng', record.get('lon', record.get('GPSLongitude'))))
    if latitude is not None and longitude is not None and not isinstance(latitude, bool) and not isinstance(longitude, bool):
        try:
            latitude, longitude = float(latitude), float(longitude)
            if math.isfinite(latitude) and math.isfinite(longitude) and -90 <= latitude <= 90 and -180 <= longitude <= 180:
                return {'latitude': latitude, 'longitude': longitude}
        except (ValueError, TypeError):
            pass
    for key in ('geo', 'contentLocation', 'location', 'spatialCoverage'):
        point = _coordinates(record.get(key))
        if point:
            return point
    return None


def _distance_km(first: dict, second: dict) -> float:
    lat1, lat2 = map(math.radians, (first['latitude'], second['latitude']))
    delta_lat = lat2 - lat1
    delta_lon = math.radians(second['longitude'] - first['longitude'])
    haversine = math.sin(delta_lat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(delta_lon / 2) ** 2
    return 6371.0088 * 2 * math.asin(math.sqrt(min(1, max(0, haversine))))


def filter_place_photos(items: list[dict], period: str, center: dict | None = None) -> list[dict]:
    accepted = []
    for item in items:
        if not isinstance(item, dict):
            continue
        if not _date_matches(item.get('date_expression', ''), period):
            continue
        if re.search(r'upload|publication|published|modified|visual_guess', item.get('date_basis', ''), re.I):
            continue
        point = _coordinates(item)
        if center is not None and (point is None or _distance_km(center, point) > PHOTO_RADIUS_KM):
            continue
        accepted.append(item)
    return _deduplicate(accepted)


def _search_queries(place: str, period: str) -> list[str]:
    bounds = _photo_period_bounds(period)
    queries = []
    for term in _place_terms(place):
        clean = ' '.join(term.replace('"', ' ').split())
        if bounds:
            years = ' OR '.join(str(year) for year in range(bounds[0], min(bounds[1], bounds[0] + 99) + 1))
            queries.extend([f'"{clean}" filetype:bitmap ({years})', f'"{clean}" filetype:bitmap'])
        else:
            queries.extend([f'"{clean}" filetype:bitmap', clean])
    return queries


def _localized_photo_query(place: str, period: str) -> str:
    bounds = _period_bounds(period)
    chinese = bool(re.search(r'[\u3400-\u9fff]', place))
    if not bounds:
        return f'{place} 街景' if chinese else f'{place} street photos'
    start, end = bounds
    if start % 10 == 0 and end == start + 9:
        label = f'{start % 100:02d}年代' if chinese else f'{start}s photos'
    elif start == end:
        label = f'{start}年' if chinese else f'{start} photos'
    else:
        label = f'{start}–{end}年' if chinese else f'{start}–{end} photos'
    return f'{place} {label}'


def _decade_fallback(period: str) -> str | None:
    bounds = _period_bounds(period)
    if not bounds or bounds[0] // 10 != bounds[1] // 10:
        return None
    start = bounds[0] // 10 * 10
    return f'{start}s' if bounds != (start, start + 9) else None


def _get(url: str, params: dict) -> dict:
    response = httpx.get(url, params=params, headers=HEADERS, timeout=8)
    response.raise_for_status()
    return response.json()


def _https_host(url: str, hosts: set[str]) -> bool:
    parsed = urlparse(url)
    return parsed.scheme == 'https' and parsed.hostname in hosts and not parsed.username and not parsed.password


def _https_url(url: str) -> bool:
    parsed = urlparse(url)
    return bool(parsed.hostname) and parsed.scheme == 'https' and not parsed.username and not parsed.password


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
            if NON_PHOTO.search(caption) or not _location_matches(caption, place) or not _date_matches(date, period):
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
                'location_evidence': caption, 'attribution': value('Artist'), 'license': license_name,
                'license_url': value('LicenseUrl'), 'date_expression': date,
                'original_url': info.get('url', image), 'content_hash': info.get('sha1', ''),
                **(_coordinates({'GPSLatitude': value('GPSLatitude'), 'GPSLongitude': value('GPSLongitude')}) or {}),
                'allowed_actions': {'embed': True, 'download': False, 'print': False},
            })
        if len(_deduplicate(items)) >= MAX_RESULTS:
            break
    return items


def _loc(place: str, period: str) -> list[dict]:
    """Only item-level photographic records with an explicit reuse statement."""
    params = {'fo': 'json', 'q': place, 'c': SEARCH_LIMIT, 'fa': 'online-format:image'}
    bounds = _photo_period_bounds(period)
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
        caption = ' '.join((title, _text(record.get('description')), _text(record.get('subject')),
                            _text(item.get('title')), _text(item.get('location')), _text(item.get('subject'))))
        if not _location_matches(caption, place):
            continue
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
            'location_evidence': caption, 'attribution': _text(record.get('contributor')) or 'Library of Congress',
            'license': rights, 'license_url': source, 'date_expression': date,
            **(_coordinates(item) or _coordinates(record) or {}),
            'allowed_actions': {'embed': True, 'download': False, 'print': False},
        })
    return items


_GOOGLE_LICENSES = (
    (re.compile(r'https?://creativecommons\.org/licenses/by-sa/(?:2\.0|2\.5|3\.0|4\.0)(?:/|\b)', re.I), 'CC BY-SA'),
    (re.compile(r'https?://creativecommons\.org/licenses/by/(?:2\.0|2\.5|3\.0|4\.0)(?:/|\b)', re.I), 'CC BY'),
    (re.compile(r'https?://creativecommons\.org/publicdomain/(?:zero|mark)/1\.0(?:/|\b)', re.I), 'Public domain'),
)


def _google_page_map_values(item: dict, key_pattern: str) -> list[tuple[str, str]]:
    page_map = item.get('pagemap') or {}
    if not isinstance(page_map, dict):
        return []
    values = []
    for object_name, objects in page_map.items():
        if isinstance(objects, dict):
            objects = [objects]
        if not isinstance(objects, list):
            continue
        for obj in objects:
            if not isinstance(obj, dict):
                continue
            for key, value in obj.items():
                if re.search(key_pattern, str(key), re.I):
                    values.append((str(key), _text(value)))
    return values


def _google_license(item: dict) -> tuple[str, str] | None:
    for _, value in _google_page_map_values(item, r'license|rights|creativecommons'):
        for pattern, name in _GOOGLE_LICENSES:
            match = pattern.search(value)
            if match:
                return name, match.group(0).rstrip('/')
    for value in (item.get('license'), item.get('rights')):
        for pattern, name in _GOOGLE_LICENSES:
            match = pattern.search(_text(value))
            if match:
                return name, match.group(0).rstrip('/')
    return None


def _google_date_values(item: dict) -> list[tuple[str, str]]:
    values = _google_page_map_values(item, r'date|time|created|taken|published|modified')
    # Titles and snippets often carry the historical capture year when a page
    # does not expose structured metadata. Treat them as source assertions and
    # still apply the same strict year-range check.
    values.extend([
        ('title', _text(item.get('title'))),
        ('snippet', _text(item.get('snippet'))),
    ])
    return [(basis, value) for basis, value in values
            if value and not re.search(r'publish|modified|upload|scan', basis, re.I)]


def _google_date(item: dict, period: str) -> tuple[str, str] | None:
    for basis, value in _google_date_values(item):
        if period == ANY_PHOTO_DATE and not _years(value):
            continue
        if _date_matches(value, period):
            return value, basis
    return None


def _google_creator(item: dict) -> str:
    for _, value in _google_page_map_values(item, r'author|creator|artist|photographer|byline'):
        if value:
            return value
    return ''


def _google_query(place: str, period: str, *, include_decade: bool = False) -> str:
    from .place_photo_browser import _research
    location_query = _research()._crawl4ai_place_query(place)
    bounds = _photo_period_bounds(period)
    if not bounds:
        if not period.strip():
            current = _research().normalize_period(None, datetime.now(ZoneInfo('Australia/Sydney')).date())
            years = range(int(current['start'][:4]), int(current['end'][:4]) + 1)
            return location_query + ' (' + ' OR '.join(str(year) for year in years) + ')'
        return location_query
    fallback = _decade_fallback(period) if include_decade else None
    if not fallback and bounds[0] % 10 == 0 and bounds[1] == bounds[0] + 9:
        # A decade's local name is a query synonym, not a wider time filter.
        fallback = f'{bounds[0]}s'
    if fallback:
        decade = int(fallback[:4])
        terms = [str(year) for year in range(bounds[0], bounds[1] + 1)]
        terms += [f'{decade % 100:02d}年代', f'{decade % 100:02d}s', f'{decade}年代', f'{decade}s']
        return f'{location_query} (' + ' OR '.join(f'"{term}"' for term in terms) + ')'
    years = ' OR '.join(str(year) for year in range(bounds[0], min(bounds[1], bounds[0] + 99) + 1))
    return f'{location_query} ({years})'


def _google_date_sort(period: str) -> str | None:
    bounds = _period_bounds(period)
    if not bounds:
        return None
    return f'date:r:{bounds[0]:04d}0101:{bounds[1]:04d}1231'


def _google_location_matches(item: dict, place: str) -> bool:
    image = item.get('image') if isinstance(item.get('image'), dict) else {}
    haystack = ' '.join([
        _text(item.get('title')), _text(item.get('snippet')), _text(item.get('displayLink')),
        _text(image.get('contextLink')),
    ]).casefold()
    return _location_matches(haystack, place)


def _location_matches(caption: str, place: str) -> bool:
    from .place_photo_browser import _research
    return _research()._crawl4ai_location_matches(caption, place)


def _google_cse(place: str, period: str, *, limit: int = MAX_RESULTS) -> list[dict]:
    """Search an optional Google Programmable Search Engine image index.

    Google returns image links and source-page links, but it does not guarantee
    that every result exposes an item-level licence or capture date. Such hits
    stay out of the gallery until a compatible licence and date assertion are
    present in the result metadata.
    """
    key = _configured_env('GOOGLE_CSE_API_KEY')
    cx = _configured_env('GOOGLE_CSE_ID')
    if not key or not cx:
        return []

    query = _google_query(place, period)
    common = {
        'key': key, 'cx': cx, 'q': query, 'searchType': 'image',
        'num': GOOGLE_CSE_PAGE_SIZE, 'safe': 'active', 'filter': '1',
        # Ask Google for commercially compatible candidates, then require the
        # result itself to expose a matching licence URL before displaying it.
        'rights': 'cc_publicdomain|cc_attribute|cc_sharealike',
    }
    # A scan/article published recently can depict an older scene. Year terms
    # and item capture evidence filter the photo, not webpage publication sort.

    items = []
    start = 1
    for _ in range(GOOGLE_CSE_MAX_PAGES):
        data = _get(GOOGLE_CSE_ENDPOINT, {**common, 'start': start})
        results = data.get('items') or []
        for result in results:
            if not isinstance(result, dict):
                continue
            image_info = result.get('image') if isinstance(result.get('image'), dict) else {}
            image = _text(result.get('link'))
            source = _text(image_info.get('contextLink'))
            if not _https_url(image) or not _https_url(source):
                continue
            title = _text(result.get('title'))
            snippet = _text(result.get('snippet'))
            caption = ' '.join((title, snippet, _text(result.get('displayLink'))))
            if NON_PHOTO.search(caption) or not _google_location_matches(result, place):
                continue
            scene_date = _google_date(result, period)
            if scene_date is None:
                if period != ANY_PHOTO_DATE or any(_years(value) for _, value in _google_date_values(result)):
                    continue
                scene_date = ('', 'unknown capture date')
            licence = _google_license(result)
            if not licence:
                continue
            license_name, license_url = licence
            asset_id = 'google-' + hashlib.sha256(f'{source}\n{image}'.encode('utf-8')).hexdigest()[:24]
            items.append({
                'asset_id': asset_id, 'kind': 'image', 'title': title or 'Google image result',
                'image_url': image, 'source_url': source, 'location': place,
                'location_evidence': caption, 'attribution': _google_creator(result) or _text(result.get('displayLink')) or source,
                'license': license_name, 'license_url': license_url,
                'date_expression': scene_date[0], 'date_basis': f'Google {scene_date[1]}',
                **next((point for records in (result.get('pagemap') or {}).values() if isinstance(records, list)
                        for record in records if (point := _coordinates(record))), {}),
                'allowed_actions': {'embed': True, 'download': False, 'print': False},
            })
        unique = _deduplicate(items)
        if len(unique) >= limit:
            return unique[:limit]
        next_pages = data.get('queries', {}).get('nextPage', [])
        if next_pages and isinstance(next_pages[0], dict) and next_pages[0].get('startIndex'):
            next_start = int(next_pages[0]['startIndex'])
        elif len(results) == GOOGLE_CSE_PAGE_SIZE:
            next_start = start + GOOGLE_CSE_PAGE_SIZE
        else:
            break
        if next_start <= start or next_start > 100:
            break
        start = next_start
    return _deduplicate(items)



def _place_terms(place: str) -> list[str]:
    terms = [place.strip()]
    # Keep aliases geographically narrow: Jehol also named a much larger region.
    if re.search(r"\bchengde\b|承德", place, re.I):
        terms += ['Chengde', '承德']
    return list(dict.fromkeys(terms))


def _flickr(place: str, period: str) -> list[dict]:
    key = _configured_env('FLICKR_API_KEY')
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
    bounds = _photo_period_bounds(period)
    params = {'per_page': 100, 'sort': 'relevance', 'media': 'photos', 'content_types': '0',
              'safe_search': 1, 'license': ','.join(allowed),
              'extras': 'description,license,date_taken,owner_name,tags,media,geo,url_z,url_c'}
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
                        or (period != ANY_PHOTO_DATE and str(photo.get('datetakenunknown', '0')) != '0')
                        or (not album and not _location_matches(caption, place))):
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
                    'location': place, 'location_evidence': caption if not album else f'{place}: verified photographer collection',
                    'attribution': _text(photo.get('ownername')) or owner,
                    'license': licence['name'], 'license_url': licence['url'],
                    'date_expression': date if str(photo.get('datetakenunknown', '0')) == '0' else '',
                    'date_basis': 'Flickr date taken' if str(photo.get('datetakenunknown', '0')) == '0' else 'Unknown capture date',
                    **((_coordinates(photo) if str(photo.get('accuracy', '0')) != '0' else None) or {}),
                    'allowed_actions': {'embed': True, 'download': False, 'print': False},
                })
            if len(_deduplicate(items)) >= MAX_RESULTS:
                return items
            if page >= int(data.get('pages', 1)):
                break
    return items


def _canonical_image(url: str) -> str:
    if not url:
        return ''
    parsed = urlparse(unquote(url))
    host = (parsed.hostname or '').lower()
    path = parsed.path
    if host == 'upload.wikimedia.org' and '/thumb/' in path:
        path = path.replace('/thumb/', '/', 1).rsplit('/', 1)[0]
    if re.fullmatch(r'(?:live|farm\d+)\.staticflickr\.com', host):
        host = 'staticflickr.com'
        path = re.sub(r'_[sqtmnzcbhokw](\.[a-zA-Z]+)$', r'\1', path)
    params = sorted((key, value) for key, value in parse_qsl(parsed.query)
                    if not key.startswith('utm_') and key not in {'width', 'height', 'w', 'h', 'fbclid', 'gclid'})
    return urlunparse(('https', host, path, '', urlencode(params), ''))


def _wikimedia_file(url: str) -> str | None:
    parsed = urlparse(unquote(url))
    host = parsed.hostname or ''
    if host == 'upload.wikimedia.org':
        path = parsed.path.replace('/thumb/', '/', 1)
        if '/thumb/' in parsed.path:
            path = path.rsplit('/', 1)[0]
        filename = path.rsplit('/', 1)[-1]
        filename = re.sub(r'^\d{14}!', '', filename)
    elif host == 'commons.wikimedia.org' or host.endswith('.wikipedia.org'):
        match = re.search(r'/(?:Special:(?:FilePath|Redirect/file)/|(?:File|文件|檔案):)(.+)$', parsed.path, re.I)
        filename = match[1] if match else dict(parse_qsl(parsed.query)).get('title', '')
        filename = re.sub(r'^(?:File|文件|檔案):', '', filename, flags=re.I)
    else:
        return None
    if not re.search(r'\.(?:jpe?g|png|webp|gif|tiff?)$', filename, re.I):
        return None
    return filename.replace('_', ' ').strip()


def _deduplicate(items: list[dict]) -> list[dict]:
    unique, seen = [], {}
    for item in items:
        original = _canonical_image(item.get('original_url') or item.get('image_url', ''))
        # A crawled article can contain several distinct photographs. Its
        # source-page URL alone must not collapse the whole article to one.
        source_url = item.get('source_url', '')
        source_key = (source_url, original) if item.get('memory_reference_only') else source_url
        source = urlparse(source_url)
        flickr_id = re.fullmatch(r'/photos/[^/]+/(\d+)/?', source.path)
        if source.hostname in {'www.flickr.com', 'flickr.com'} and flickr_id:
            source_key = ('flickr', flickr_id[1])
        keys = {('asset', item.get('asset_id')), ('source', source_key), ('image', original),
                ('image', _canonical_image(item.get('image_url', '')))}
        keys = {key for key in keys if key[1]}
        for value in (item.get('original_url'), item.get('image_url')):
            filename = _wikimedia_file(value or '')
            if filename:
                keys.add(('wikimedia', filename))
        if item.get('content_hash'):
            keys.add(('hash', item['content_hash']))
        fingerprint = item.get('perceptual_hash', '')
        similar = next((index for index, other in enumerate(unique) if
            re.fullmatch(r'[0-9a-f]{16}', fingerprint) and
            re.fullmatch(r'[0-9a-f]{16}', other.get('perceptual_hash', ''))
            and (int(fingerprint, 16) ^ int(other['perceptual_hash'], 16)).bit_count() <= 6
            ), None)
        matches = {seen[key] for key in keys if key in seen}
        if matches or similar is not None:
            index = min(matches) if matches else similar
            exact_images = {seen[key] for key in keys if key in seen
                            and (key[0] in {'asset', 'image', 'hash', 'wikimedia'}
                                 or (key[0] == 'source' and isinstance(key[1], tuple)
                                     and key[1][0] == 'flickr'))}
            for match in exact_images:
                if _coordinates(unique[match]) is None and _coordinates(item) is not None:
                    # Keep the whole source-backed candidate, including its
                    # provenance. Similar-looking scenes do not confer GPS.
                    unique[match] = item
            for key in keys:
                seen.setdefault(key, index)
            continue
        index = len(unique)
        unique.append(item)
        seen.update((key, index) for key in keys)
    return unique


def _mix_sources(items: list[dict]) -> list[dict]:
    groups = {}
    for item in items:
        host = (urlparse(item['source_url']).hostname or '').removeprefix('www.')
        groups.setdefault(host, []).append(item)
    return [item for row in zip_longest(*groups.values()) for item in row if item is not None]


def _search_period(place: str, period: str, *, limit: int | None = MAX_RESULTS, on_items=None,
                   skip_google_browser: bool = False) -> list[dict]:
    if period.strip() and period != ANY_PHOTO_DATE and not _period_bounds(period) and not _is_historical_period(period):
        return []
    items, errors = [], []
    # Independent catalogues overlap their network waits; one failure must not
    # hide the other catalogue's usable photographs.
    providers = [('commons', _commons), ('loc', _loc)]
    if _configured_env('GOOGLE_CSE_API_KEY') and _configured_env('GOOGLE_CSE_ID'):
        providers.insert(0, ('google', lambda p, t: _google_cse(p, t, limit=DISCOVERY_LIMIT if limit is None else limit)))
    elif not skip_google_browser and (_configured_env('GOOGLE_CSE_URL') or _configured_env('GOOGLE_CSE_ID')):
        providers.insert(0, ('google', _google_browser))
    providers.insert(0, ('flickr', _flickr if _configured_env('FLICKR_API_KEY') else _flickr_browser))
    if _configured_env('MEMORY_SPARK_PHOTO_WEB_SEARCH').lower() in {'1', 'true', 'yes'}:
        providers.insert(0, ('llm_web_search', _llm_web_search))
    def run(provider):
        def matching(found):
            return [item for item in found
                    if _location_matches(item.get('location_evidence') or item.get('title', ''), place)
                    and _date_matches(item.get('date_expression', ''), period)]
        def publish(found):
            accepted = matching(found)
            if accepted and on_items:
                on_items(_deduplicate(accepted))
        if on_items and provider in (_google_browser, _flickr_browser):
            found = provider(place, period, on_items=publish)
        else:
            found = matching(provider(place, period))
            if provider not in (_google_browser, _flickr_browser):
                from .place_photo_fingerprints import image_fingerprint
                def fingerprint(item):
                    return {**item, **image_fingerprint(item['image_url'])}
                with ThreadPoolExecutor(max_workers=4) as images:
                    if on_items:
                        pending = [images.submit(fingerprint, item) for item in found]
                        found = []
                        for completed in as_completed(pending):
                            found.append(completed.result())
                            if len(found) == 1 or len(found) % 4 == 0:
                                publish(found)
                    else:
                        found = list(images.map(fingerprint, found))
        publish(found)
        return matching(found)

    with ThreadPoolExecutor(max_workers=len(providers)) as pool:
        futures = [(name, pool.submit(run, provider)) for name, provider in providers]
        for name, future in futures:
            try:
                items.extend(future.result())
            except (http.client.HTTPException, httpx.HTTPError, ValueError, KeyError, TypeError) as error:
                errors.extend(error.failures if isinstance(error, PhotoResearchUnavailable)
                              else [{'provider': name, 'reason': photo_failure_reason(error)}])
    items = filter_place_photos(items, period)
    exact = [item for item in items if _date_matches(item.get('date_expression', ''), period, tolerance=0)]
    broader = [item for item in items if not _date_matches(item.get('date_expression', ''), period, tolerance=0)]
    mixed = _deduplicate(_mix_sources(exact) + _mix_sources(broader))
    # A successful empty catalogue cannot establish no-match for blocked sources.
    if not mixed and errors:
        raise PhotoResearchUnavailable(failures=errors)
    return mixed[:limit] if limit is not None else mixed[:150]


def search_place_photos(place: str, period: str = '', *, limit: int | None = MAX_RESULTS, on_items=None) -> list[dict]:
    fallback = _decade_fallback(period)
    def label(items):
        return [{**item, 'requested_period': period,
                 'matched_period': period if _date_matches(item.get('date_expression', ''), period, tolerance=0) else fallback,
                 'period_match': 'requested' if _date_matches(item.get('date_expression', ''), period, tolerance=0) else
                    'decade' if fallback and _date_matches(item.get('date_expression', ''), fallback, tolerance=0) else 'nearby'}
                for item in items if _date_matches(item.get('date_expression', ''), period)]

    def run(search_period, search_limit):
        progress = {'on_items': lambda items: on_items(label(items))} if on_items else {}
        # Google browser has already searched both scopes, including when blocked.
        if search_period != period:
            progress['skip_google_browser'] = True
        return _search_period(place, search_period, limit=search_limit, **progress)

    failures = []
    try:
        requested = run(period, limit)
    except PhotoResearchUnavailable as error:
        requested = []
        failures.extend(error.failures)
    broader = []
    if fallback and sum(_date_matches(item.get('date_expression', ''), period, tolerance=0) for item in requested) < MAX_RESULTS:
        try:
            broader = run(fallback, None)
        except PhotoResearchUnavailable as error:
            failures.extend(error.failures)
        except (httpx.HTTPError, ValueError, KeyError, TypeError):
            pass  # A wider search must not erase exact-year results.
    exact, decade = [], []
    for labelled in label(requested + broader):
        matches_requested = labelled['period_match'] == 'requested'
        (exact if matches_requested else decade).append(labelled)
    mixed = _deduplicate(_mix_sources(exact) + _mix_sources(decade))
    if not mixed and failures:
        raise PhotoResearchUnavailable(failures=[dict(item) for item in dict.fromkeys(
            tuple(failure.items()) for failure in failures)])
    return mixed[:limit] if limit is not None else mixed[:150]


def _google_browser(place: str, period: str, *, on_items=None) -> list[dict]:
    from .place_photo_browser import crawl_place_photos
    return crawl_place_photos('google', place, period, limit=DISCOVERY_LIMIT, timeout=45, on_items=on_items)


def _llm_web_search(place: str, period: str) -> list[dict]:
    from .place_photo_browser import _research
    helper = _research()
    clock = datetime.now(ZoneInfo('Australia/Sydney')).date()
    # The app accepts explicit year expressions in addition to standalone
    # skill periods. Preserve its resolved window rather than reinterpreting it.
    bounds = _period_bounds(period)
    temporal = ({'mode': 'any_time'} if period == ANY_PHOTO_DATE else
                {'mode': 'historical_range', 'start': f'{bounds[0]}-01-01', 'end': f'{bounds[1]}-12-31'}
                if bounds else helper.normalize_period(period if _is_historical_period(period) else None, clock))
    try:
        discovery = helper.llm_search(place, temporal)
        items, source_failed = [], False
        for origin in discovery['sources'][:12]:
            try:
                images = helper.llm_source_photos(origin['source_url'], place, temporal)
            except (helper.ResearchError, OSError, ValueError, http.client.HTTPException):
                source_failed = True
                continue
            for image in images:
                scene = image['scene_date']
                expression = scene['start'] if scene else ''
                if scene and scene['precision'] == 'month':
                    expression = scene['start'][:7]
                elif scene and scene['precision'] == 'year':
                    expression = scene['start'][:4]
                elif scene and scene['precision'] in {'decade', 'range'}:
                    expression = scene['start'][:4] + '-' + scene['end'][:4]
                items.append({
                    'asset_id': 'llm-' + hashlib.sha256(image['image_url'].encode()).hexdigest()[:24],
                    'kind': 'image', 'title': image['title'], 'location': place,
                    'location_evidence': image['source_excerpt'],
                    'image_url': image['image_url'], 'original_url': image['image_url'],
                    'source_url': image['source_page_url'],
                    'date_expression': expression, 'scene_date_range': scene,
                    'date_basis': 'Source capture metadata' if scene else 'Unknown capture date',
                    'attribution': urlparse(image['source_page_url']).hostname,
                    'license': 'Unknown', 'memory_reference_only': True,
                    'providers': ['llm_web_search'], 'discovery_origins': [origin],
                    'allowed_actions': {'embed': True, 'memory_reference': True, 'download': False,
                                        'print': False, 'publish': False},
                })
        if not items and source_failed:
            raise PhotoResearchUnavailable('llm_web_search', 'source_unavailable')
        return _deduplicate(items)
    except http.client.HTTPException:
        raise PhotoResearchUnavailable('llm_web_search', 'source_unavailable') from None
    except helper.ResearchError as error:
        raise PhotoResearchUnavailable('llm_web_search', str(error) if str(error).startswith('llm_') else 'source_unavailable') from None


def _flickr_browser(place: str, period: str, *, on_items=None) -> list[dict]:
    from .place_photo_browser import crawl_place_photos
    return crawl_place_photos('flickr', place, period, limit=DISCOVERY_LIMIT, timeout=45, on_items=on_items)
