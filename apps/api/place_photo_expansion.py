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
