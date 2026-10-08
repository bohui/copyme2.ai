"""Background city membership and individual pins; source memories remain distinct."""
from copy import deepcopy
import json
import math
import unicodedata

import httpx

from .place_geocoding import GoogleMapsUnavailable, search_place_details
from .place_identity import geographic_label

MAX_LOOKUPS = 8


def _label(value):
    label = unicodedata.normalize('NFKC', str(value)).strip().casefold()
    label = {'chengde': '承德', 'china': '中国', 'hebei': '河北'}.get(label, label)
    return geographic_label(label)


def _path(place):
    labels = [label for label in place['hierarchy'] if _label(label) != 'earth']
    if not labels or _label(labels[-1]) != _label(place['place']):
        labels.append(place['place'])
    return labels


def _key(place):
    return json.dumps([_label(label) for label in _path(place)], ensure_ascii=False, separators=(',', ':'))


def _coordinates(place):
    lat, lon = place.get('latitude'), place.get('longitude')
    return all(isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
               for value in (lat, lon)) and -90 <= lat <= 90 and -180 <= lon <= 180


def resolve_place_groups(places, *, allow_provider=True):
    cities = [place for place in places if place['granularity'] == 'city']
    records, lookups, provider_available = [], 0, True
    for index, place in enumerate(places):
        path = [_label(label) for label in _path(place)]
        ancestors = [city for city in cities if len(_path(city)) <= len(path)
                     and [_label(label) for label in _path(city)] == path[:len(_path(city))]]
        # The containing city owns the view, even if a child was labelled city.
        city = deepcopy(min(ancestors, key=lambda item: len(_path(item)))) if ancestors else None
        own_coordinates = _coordinates(place)
        same_as_parent = bool(city and _key(city) != _key(place) and own_coordinates
                              and place.get('latitude') == city.get('latitude')
                              and place.get('longitude') == city.get('longitude'))
        pin = {**deepcopy(place), 'accuracy': 'approximate'} if own_coordinates and not same_as_parent else None
        details = None
        if allow_provider and (not city or not pin) and lookups < MAX_LOOKUPS and provider_available:
            lookups += 1
            try:
                details = search_place_details(', '.join(reversed(_path(place))))
            except (GoogleMapsUnavailable, httpx.HTTPError, ValueError, TypeError):
                provider_available = False
        if details:
            if details.get('city'):
                resolved_city = {'place': details['city'], 'hierarchy': ['Earth', *filter(None,
                    (details.get('country'), details.get('region'), details['city']))], 'granularity': 'city'}
                if city is None or _key(city) != _key(resolved_city):
                    city = resolved_city
            if not details.get('partial_match'):
                pin = {**deepcopy(place), 'latitude': details['latitude'], 'longitude': details['longitude'],
                       'accuracy': 'public-map', 'attribution': details.get('attribution', 'Google Maps')}
            else:
                pin = None
        city = city or deepcopy(place)
        # A provider can return only the city centre despite matching the query.
        # It remains a usable map target, never an independent child's position.
        if (pin and _key(city) != _key(place)
                and pin['latitude'] == city.get('latitude')
                and pin['longitude'] == city.get('longitude')):
            pin = None
        records.append({'index': index, 'city_key': _key(city), 'city': city, 'pin': pin,
                        'pin_status': 'READY' if pin else 'UNRESOLVED'})
    # A coarse city mention can omit the state that a later mention supplies.
    # Complete it only when the same country/name has one unambiguous full path;
    # conflicting regional names remain separate. Source places and pins stay intact.
    for record in records:
        city = record['city']
        path = [_label(label) for label in _path(city)]
        if city['granularity'] != 'city' or len(path) != 2:
            continue
        matches = {}
        for candidate in records:
            full = candidate['city']
            full_path = [_label(label) for label in _path(full)]
            if (full['granularity'] == 'city' and len(full_path) > 2
                    and full_path[0] == path[0] and full_path[-1] == path[-1]):
                matches[_key(full)] = full
        if len(matches) == 1:
            record['city_key'], full = next(iter(matches.items()))
            record['city'] = deepcopy(full)
    return {'schema_version': 1, 'skills': ['memoir-place-groups'], 'places': records,
            'status': 'READY' if all(record['pin'] for record in records) else 'PARTIAL'}
