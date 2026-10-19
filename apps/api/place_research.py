"""Bind public place research to its accepted source, without dating other places."""
import re

from .place_identity import geographic_label

DATE = re.compile(r'(?<!\d)(?:18|19|20)\d{2}(?:\s*(?:s|年代)|年(?:\d{1,2}月(?:\d{1,2}日)?)?)?'
                  r'(?:\s*(?:[–—-]|至|到|to)\s*(?:18|19|20)\d{2}年?)?', re.I)
UNRESOLVED = re.compile(r'\bnot\b|never|maybe|perhaps|about|around|不是|并非|大约|可能|不确定', re.I)


def place_aliases(place):
    label = geographic_label(place)
    if label in {'chengde', '承德'}:
        return ('Chengde', '承德')
    return (label,)


def same_research_place(first, second):
    return bool(set(place_aliases(first)) & set(place_aliases(second)))


def _named(clause, place):
    return any(re.search((r'(?<![a-z])' if alias.isascii() else '') + re.escape(alias)
                         + (r'(?![a-z])' if alias.isascii() else ''), clause, re.I)
               for alias in place_aliases(place))


def research_places(places, sources):
    """A birth decade is a reference-search window, never a memoir event date."""
    active = {source.get('sequence'): source for source in sources if source.get('status') == 'active'}
    result = []
    for place in places:
        period, basis = '', ''
        source = active.get(place.get('source_sequence'))
        for clause in re.split(r'[，。!?！？；;\n]|\bbut\b|但是|不过|然而', (source or {}).get('text', '')):
            if not _named(clause, place['place']) or UNRESOLVED.search(clause):
                continue
            if any(other['place'] != place['place'] and not same_research_place(other['place'], place['place'])
                   and _named(clause, other['place']) for other in places):
                continue
            dates = DATE.findall(clause)
            if len(dates) != 1:
                continue
            expression = dates[0]
            years = [int(year) for year in re.findall(r'(?:18|19|20)\d{2}', expression)]
            birth = bool(re.search(r'\bborn\b|出生', clause, re.I))
            if birth and (not re.search(r'\bI\b|我(?:于|在|是|生|出)|本人', clause, re.I)
                          or re.search(r'我(?:的)?(?:父|母|爸|妈|祖|外|儿|女)|\bmy\b', clause, re.I)):
                continue
            if len(years) == 2:
                if years[0] > years[1] or years[1] - years[0] > 15:
                    continue
                period, basis = f'{years[0]}–{years[1]}', 'explicit_period'
            elif re.search(r's|年代', expression, re.I) or birth:
                period, basis = f'{years[0] // 10 * 10}s', 'birth_decade' if birth else 'explicit_period'
            else:
                period, basis = expression, 'explicit_period'
        result.append({**place, 'research_period': period, 'research_period_basis': basis})
    return result


def research_hypothesis(places, *, selection=None, current_year=None):
    from .historical_news import PUBLIC_PLACES, _window
    from datetime import datetime, timezone
    current_year = current_year or datetime.now(timezone.utc).year
    for place in reversed(places):
        period = place.get('research_period', '')
        if not period or selection and (not same_research_place(place['place'], selection['place'])
                                        or period != selection['period']):
            continue
        pair = next((pair for pair in PUBLIC_PLACES
                     if geographic_label(pair[0]) == geographic_label(place['place'])), None)
        if not pair:
            continue
        years = [int(year) for year in re.findall(r'(?:18|19|20)\d{2}', period)]
        start, end = years[0], years[-1]
        if period.endswith('s'):
            end = start + 9
        if start > current_year or not _window({'start': start, 'end': end}):
            continue
        return {'place': ', '.join(pair), 'country': pair[1], 'start': start, 'end': min(end, current_year),
                'granularity': PUBLIC_PLACES[pair], 'tentative': True,
                'time_basis': place['research_period_basis'], 'age_interval': None}
    return None


def load_research_places(storage, project_id, places):
    sequences = sorted({place['source_sequence'] for place in places
                        if type(place.get('source_sequence')) is int})
    if not sequences:
        return research_places(places, [])
    response = storage.request('GET', '/rest/v1/user_narrator_source', params={
        'select': 'id,version,sequence,status,text', 'user_id': 'eq.' + storage.user_id,
        'project_id': 'eq.' + project_id, 'status': 'eq.active',
        'sequence': 'in.(' + ','.join(map(str, sequences)) + ')', 'limit': str(len(sequences))})
    return research_places(places, response.json())
