"""Bounded historical Google image discovery queries.

Queries are discovery leads, never proof of a photograph's place, scene date,
rights, or identity. Original source inspection retains those responsibilities.
"""
from __future__ import annotations

from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit

MAX_EXPANDED_QUERIES = 7
MAX_EXPANDED_SOURCE_PAGES = 36
MAX_SOURCE_LEADS_PER_QUERY = 12
EXPANDED_SEARCH_SECONDS = 65


def historical_queries(primary: str, location_query: str, bounds: tuple[int, int] | None,
                       *, max_queries: int = MAX_EXPANDED_QUERIES) -> list[str]:
    """Start with the existing query, then pursue sparse historical coverage.

    Only caller-validated place aliases are used. Do not infer additional
    locations or silently replace an explicitly requested historical period.
    """
    if bounds is None or max_queries <= 1:
        return [primary]
    start, end = bounds
    if start < 1800 or end > 2100 or end < start or end - start > 99:
        return [primary]
    years = list(range(start, end + 1))
    # Keep wide ranges small. Relevance is decided from each original image,
    # not from search-result year text or a general album heading.
    samples = list(dict.fromkeys((years[0], years[len(years) // 3],
                                  years[(2 * len(years)) // 3], years[-1])))
    year_group = '(' + ' OR '.join(f'"{year}"' for year in samples) + ')'
    queries = [
        primary,
        f'{location_query} {year_group} ("老照片" OR "档案" OR "archive" OR "historical photos")',
        f'{location_query} {year_group} ("街景" OR "老街" OR "street" OR "daily life")',
        f'{location_query} {year_group} ("相册" OR "影集" OR "album" OR "photographer")',
    ]
    queries.extend(f'{location_query} "{year}" ("照片" OR "photograph")' for year in samples)
    return list(dict.fromkeys(queries))[:max_queries]


def google_search_urls(url: str, queries: list[str]) -> list[str]:
    """Rewrite only the Google CSE q parameter, preserving validated cx."""
    parsed = urlsplit(url)
    if (parsed.scheme != 'https' or parsed.hostname not in {'cse.google.com', 'www.google.com'}
            or parsed.username or parsed.password or parsed.port not in {None, 443}):
        raise ValueError('Expected a validated Google CSE URL')
    params = parse_qs(parsed.query)
    if not params.get('cx'):
        raise ValueError('Expected a Google CSE engine')
    urls = []
    for query in queries:
        values = dict(params)
        values['q'] = [query]
        values.pop('page', None)
        values.pop('start', None)
        urls.append(urlunsplit((parsed.scheme, parsed.netloc, parsed.path,
                               urlencode(values, doseq=True), '')))
    return list(dict.fromkeys(urls))


# A matching source-page title or hostname is not album membership evidence.
# Restrict inherited locality to explicit album/gallery item containers and
# always discard links inside navigation, related or recommended collections.
from html.parser import HTMLParser
from urllib.parse import urljoin
import re

_COLLECTION_REGION = re.compile(
    r'(?:^|[\s_-])(?:album|gallery|photoset|collection|photo-grid|image-grid)(?:$|[\s_-])', re.I,
)
_NON_MEMBER_REGION = re.compile(
    r'(?:^|[\s_-])(?:nav|navigation|related|recommend\w*|suggest\w*|sidebar|footer|header|breadcrumb|advert\w*|sponsor\w*)(?:$|[\s_-])',
    re.I,
)
_VOID_TAGS = frozenset({'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link',
                        'meta', 'param', 'source', 'track', 'wbr'})
# These aliases are defensive evidence of *conflicting* named cities, not a
# gazetteer used to invent a photo location or widen the requested place.
_CITY_ALIASES = (
    ('Chengde', '承德'), ('Chengdu', '成都'), ('Beijing', '北京'),
    ('Shanghai', '上海'), ('Tianjin', '天津'), ('Guangzhou', '广州'),
    ('Shenzhen', '深圳'), ('Sydney', '悉尼'), ('Melbourne', '墨尔本'),
    ('Nanjing', '南京'), ('Hangzhou', '杭州'), ('Chongqing', '重庆'),
)


def verified_album_member_links(source_html: str, source_url: str) -> list[str]:
    """Return photo leads only from explicitly marked album/gallery item regions.

    A parent page title cannot establish that its unrelated navigation,
    recommendation or same-host photo links belong to the album. Every returned
    source remains subject to hostname/URL, capture-date and place validation.
    """
    class Parser(HTMLParser):
        def __init__(self):
            super().__init__(convert_charrefs=True)
            self.stack = []
            self.links = []

        def handle_starttag(self, tag, attrs):
            attributes = dict(attrs)
            parent_member = self.stack[-1][1] if self.stack else False
            parent_blocked = self.stack[-1][2] if self.stack else False
            label = ' '.join(str(attributes.get(key) or '') for key in (
                'class', 'id', 'role', 'aria-label', 'data-testid', 'itemtype',
            ))
            blocked = (parent_blocked or tag in {'nav', 'header', 'footer', 'aside'}
                       or bool(_NON_MEMBER_REGION.search(label)))
            member = not blocked and (parent_member or (
                tag in {'div', 'section', 'ul', 'ol', 'main', 'article'}
                and bool(_COLLECTION_REGION.search(label))
            ))
            if tag == 'a' and member and attributes.get('href'):
                self.links.append(urljoin(source_url, attributes['href']))
            if tag not in _VOID_TAGS:
                self.stack.append((tag, member, blocked))

        def handle_endtag(self, tag):
            for i in range(len(self.stack) - 1, -1, -1):
                if self.stack[i][0] == tag:
                    del self.stack[i:]
                    return

    parsed = Parser()
    parsed.feed(source_html)
    return list(dict.fromkeys(parsed.links[:96]))


def conflicting_item_locality(page: dict, place: str, location_matches) -> bool:
    """Veto item-level location claims incompatible with inherited album context.

    Structured photo location and clearly city-leading photo titles can veto
    inheritance; descriptive subjects like "Willow trees" cannot create a new
    city claim. The caller supplies existing validated location alias matching.
    """
    metadata = {str(item.get('name') or item.get('property') or '').casefold():
                item.get('content') for item in page.get('metadata', [])
                if isinstance(item, dict)}
    explicit = [metadata.get('geo.placename'), metadata.get('place:location:name')]
    titles = [page.get('title', ''), metadata.get('og:title', '')]

    def visit(node, depth=0):
        if depth > 5:
            return
        if isinstance(node, list):
            for child in node[:40]:
                visit(child, depth + 1)
        elif isinstance(node, dict):
            types = node.get('@type', [])
            if isinstance(types, str):
                types = [types]
            if set(types).intersection({'ImageObject', 'Photograph', 'ImageGallery'}):
                titles.append(node.get('name', ''))
                location = node.get('contentLocation') or node.get('spatialCoverage')
                if isinstance(location, dict):
                    explicit.append(location.get('name') or location.get('addressLocality'))
                    address = location.get('address')
                    if isinstance(address, dict):
                        explicit.append(address.get('addressLocality'))
                elif isinstance(location, str):
                    explicit.append(location)
            if '@graph' in node:
                visit(node['@graph'], depth + 1)
    visit(page.get('json_ld', []))
    for locality in explicit:
        if isinstance(locality, str) and locality.strip() and not location_matches(locality, place):
            return True
    for title in titles:
        if not isinstance(title, str):
            continue
        cleaned = re.sub(r'^(?:old|historical|vintage|archive|photo of)\s+', '',
                         title.strip(), flags=re.I)
        for aliases in _CITY_ALIASES:
            if (any(re.match(re.escape(alias) + (r'\b' if alias.isascii() else ''),
                             cleaned, re.I) for alias in aliases)
                    and not any(alias.casefold() in place.casefold() for alias in aliases)):
                return True
    return False
