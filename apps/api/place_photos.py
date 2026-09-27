"""Public place reference images, with item-level Commons attribution.

Only coarse place/period queries leave the application. No transcript or profile
is sent. Network failure leaves the conversation usable.
"""
import html
import re
from urllib.parse import urlparse

import httpx

MAX_RESULTS = 3
SEARCH_LIMIT = 50


def _search_queries(place: str, period: str) -> list[str]:
    clean_place = " ".join(place.replace('"', ' ').split())
    years = re.findall(r'\b(?:18|19|20)\d{2}s?\b', period)
    suffix = ' ' + ' '.join(years[:2]) if years else ''
    queries = [f'"{clean_place}" filetype:bitmap', clean_place]
    return [query + suffix for query in queries]


def search_place_photos(place: str, period: str = '') -> list[dict]:
    items = []
    seen = set()
    last_error = None
    for query in _search_queries(place, period):
        try:
            response = httpx.get('https://commons.wikimedia.org/w/api.php', params={
                'action': 'query', 'format': 'json', 'generator': 'search',
                'gsrsearch': query, 'gsrnamespace': 6, 'gsrlimit': SEARCH_LIMIT,
                'prop': 'imageinfo', 'iiprop': 'url|mime|extmetadata', 'iiurlwidth': 640,
            }, headers={'User-Agent': 'MemorySpark/1.0 (memoir place reference images)'}, timeout=8)
            response.raise_for_status()
        except httpx.HTTPError as error:
            last_error = error
            continue

        for page in response.json().get('query', {}).get('pages', {}).values():
            asset_id = f"commons-{page.get('pageid')}"
            if asset_id in seen:
                continue
            info = (page.get('imageinfo') or [{}])[0]
            metadata = info.get('extmetadata', {})

            def value(key):
                return html.unescape(re.sub(r'<[^>]*>', '', str(metadata.get(key, {}).get('value', ''))))[:1000]

            license_name = value('LicenseShortName')
            if license_name not in {'CC0', 'CC0 1.0', 'Public domain', 'CC BY 4.0', 'CC BY-SA 4.0'}:
                continue
            image = info.get('thumburl', '')
            source = info.get('descriptionurl', '')
            if (urlparse(image).scheme != 'https' or urlparse(image).hostname != 'upload.wikimedia.org'
                    or urlparse(source).scheme != 'https' or urlparse(source).hostname != 'commons.wikimedia.org'
                    or info.get('mime') not in {'image/jpeg', 'image/png', 'image/webp'}):
                continue
            seen.add(asset_id)
            items.append({
                'asset_id': asset_id, 'kind': 'image',
                'title': page.get('title', '').removeprefix('File:'),
                'image_url': image, 'source_url': source, 'location': place,
                'attribution': value('Artist'), 'license': license_name,
                'license_url': value('LicenseUrl'), 'date_expression': value('DateTimeOriginal'),
                'label': 'Public place reference; not a personal photograph. Date and scene may differ from your memory.',
                'allowed_actions': {'embed': True, 'download': False, 'print': False},
            })
            if len(items) >= MAX_RESULTS:
                return items
    if not items and last_error:
        raise last_error
    return items
