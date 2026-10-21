"""Bind public place research to its accepted source, without dating other places."""
import re

from .place_identity import geographic_label


def place_aliases(place):
    label = geographic_label(place)
    if label in {'chengde', '承德'}:
        return ('Chengde', '承德')
    return (label,)


def same_research_place(first, second):
    return bool(set(place_aliases(first)) & set(place_aliases(second)))


def _country_key(value):
    label = geographic_label(value)
    return {
        '中国': 'china', 'china': 'china',
        '澳大利亚': 'australia', 'australia': 'australia',
        '美国': 'usa', 'usa': 'usa', 'us': 'usa', 'united states': 'usa',
        '英国': 'uk', 'uk': 'uk', 'united kingdom': 'uk',
    }.get(label, label)


def _research_country(place, public_places):
    known_countries = {_country_key(country) for _, country in public_places}
    hierarchy = place.get('hierarchy') or []
    hierarchy_countries = {_country_key(label) for label in hierarchy
                           if _country_key(label) in known_countries}
    if len(hierarchy_countries) == 1:
        return hierarchy_countries.pop()
    country = _country_key(place.get('country')) if place.get('country') else None
    return country if country in known_countries else None


def _research_pair(place, public_places):
    country = _research_country(place, public_places)
    if not country:
        return None
    matches = [pair for pair in public_places
               if geographic_label(pair[0]) == geographic_label(place['place'])
               and _country_key(pair[1]) == country]
    return matches[0] if len(matches) == 1 else None


def normalized_research_fields(window):
    from .place_journey import PlaceResearchWindow
    if not window:
        return dict(research_period='',research_period_basis='',research_year=None)
    window=PlaceResearchWindow.model_validate(window).model_dump()
    start,end=window['year_start'],window['year_end']
    period=(f'{start}s' if end==start+9 and start%10==0 else str(start) if start==end else f'{start}–{end}')
    return dict(research_period=period,research_period_basis=window['basis'],research_year=window['anchor_year'])


def research_places(places, sources):
    """Project a source-bound normalized model window; never reparse narration."""
    from .place_journey import PlaceResearchWindow
    active = {source.get('sequence'): source for source in sources if source.get('status') == 'active'}
    result = []
    for place in places:
        window = place.get('research')
        source = active.get(place.get('source_sequence'))
        fields = normalized_research_fields(None)
        if window and source:
            window = PlaceResearchWindow.model_validate(window).model_dump()
            if source['text'][window['char_start']:window['char_end']] == window['quote']:
                fields = normalized_research_fields(window)
        result.append({**place, **fields})
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
        pair = _research_pair(place, PUBLIC_PLACES)
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
