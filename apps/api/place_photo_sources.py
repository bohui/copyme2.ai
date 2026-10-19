"""Priority discovery sites, never blanket permission to reuse their photographs."""
import re
from urllib.parse import urlsplit


ARCHIVE_SOURCES = (
    {'id': 'chengde-archives', 'name': 'Chengde Municipal Archives',
     'url': 'https://www.cddaw.cn/', 'domain': 'cddaw.cn',
     'places': ('Chengde', '承德', '承德市', '河北省承德市', '河北承德'), 'language': 'zh-CN'},
    {'id': 'city-of-sydney-archives', 'name': 'City of Sydney Archives',
     'url': 'https://archives.cityofsydney.nsw.gov.au/', 'domain': 'archives.cityofsydney.nsw.gov.au',
     'places': ('Sydney', 'City of Sydney', 'Sydney CBD', '悉尼', '悉尼市'), 'language': 'en-AU'},
)


def archive_sources(place):
    parts = [part.strip().casefold() for part in re.split(r'[,，/|、]', place)]
    # City of Sydney is a local council, not every suburb in greater Sydney.
    return [source for source in ARCHIVE_SOURCES
            if any(alias.casefold() in (parts if source['language'] == 'zh-CN' else parts[:1])
                   for alias in source['places'])]


def source_registry_id(url):
    host = urlsplit(url).hostname or ''
    return next((source['id'] for source in ARCHIVE_SOURCES
                 if host == source['domain'] or host.endswith('.' + source['domain'])), '')


def discovery_queries(place, period, primary):
    """Two requests normally; a third Chinese web search for Chinese locations."""
    from .place_photos import _google_query, _localized_photo_query
    sources = archive_sources(place)
    location = _google_query(place, period)
    sites = ' OR '.join('site:' + source['domain'] for source in sources)
    web = f'{location} ({sites})' if sites else f'{location} (archive OR photographs OR 老照片)'
    queries = [('google_images', primary), ('google', web)]
    chinese = next((source for source in sources if source['language'] == 'zh-CN'), None)
    if chinese or re.search(r'[\u3400-\u9fff]', place):
        local = next((alias for alias in chinese['places'] if not alias.isascii()), place) if chinese else place
        keywords = ' 老照片 档案' if period else ' 照片 街景'
        queries.append(('baidu', _localized_photo_query(local, period) + keywords))
    return queries


def usage_permissions(permitted):
    # An app-display licence does not approve the particular book/game use.
    return {'app_display': 'permitted' if permitted else 'needs_permission',
            'ebook': 'needs_review', 'print': 'needs_review', 'game': 'needs_review'}
