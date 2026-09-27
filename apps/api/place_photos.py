"""Public place reference images, with item-level Commons attribution.

Only coarse place/period queries leave the application. No transcript or profile
is sent. Network failure leaves the conversation usable.
"""
import html
import re
from urllib.parse import urlparse

import httpx


def search_place_photos(place: str, period: str = '') -> list[dict]:
    query = '"' + place.replace('"', ' ').strip() + '" filetype:bitmap'
    # Only a date supplied in the period expression is useful to public search.
    years = re.findall(r'\b(?:18|19|20)\d{2}s?\b', period)
    if years:
        query += ' ' + ' '.join(years[:2])
    response = httpx.get('https://commons.wikimedia.org/w/api.php', params={
        'action': 'query', 'format': 'json', 'generator': 'search',
        'gsrsearch': query, 'gsrnamespace': 6, 'gsrlimit': 12,
        'prop': 'imageinfo', 'iiprop': 'url|mime|extmetadata', 'iiurlwidth': 640,
    }, headers={'User-Agent': 'MemorySpark/1.0 (memoir place reference images)'}, timeout=8)
    response.raise_for_status()
    items = []
    for page in response.json().get('query', {}).get('pages', {}).values():
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
        items.append({
            'asset_id': f"commons-{page['pageid']}", 'kind': 'image',
            'title': page.get('title', '').removeprefix('File:'),
            'image_url': image, 'source_url': source, 'location': place,
            'attribution': value('Artist'), 'license': license_name,
            'license_url': value('LicenseUrl'), 'date_expression': value('DateTimeOriginal'),
            'label': 'Public place reference; not a personal photograph. Date and scene may differ from your memory.',
            'allowed_actions': {'embed': True, 'download': False, 'print': False},
        })
        if len(items) == 3:
            break
    return items
