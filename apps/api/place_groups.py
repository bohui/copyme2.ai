"""Resolve map city membership and individual pins for public places."""
import asyncio
from copy import deepcopy
import json
import math
import unicodedata

import httpx
from fastapi import HTTPException

from .place_geocoding import GeocodingUnavailable, search_place_details
from .place_identity import geographic_label
from .place_journey import validate_event_location

MAX_LOOKUPS = 8


async def resolve_map_place_groups(payload):
    raw_places = payload.get('places')
    if not isinstance(raw_places, list) or len(raw_places) > 1000:
        raise HTTPException(422, 'Invalid place group input')
    places = [validate_event_location(place) for place in raw_places]
    if any(place is None for place in places):
        raise HTTPException(422, 'Invalid place group input')
    language = payload.get('language')
    if language not in (None, 'en-AU', 'zh-CN'):
        raise HTTPException(422, 'Unsupported place display language')
    return await asyncio.to_thread(resolve_place_groups, places, language=language)


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


def _provider_city(details):
    if details and details.get('city'):
        return {'place': details['city'], 'hierarchy': ['Earth', *filter(None,
            (details.get('country'), details.get('region'), details['city']))], 'granularity': 'city'}
    return None


def resolve_place_groups(places, *, allow_provider=True, language=None):
    cities = [place for place in places if place['granularity'] == 'city']
    records, lookups, provider_available = [], 0, True

    def lookup(place):
        nonlocal lookups, provider_available
        if not allow_provider or lookups >= MAX_LOOKUPS or not provider_available:
            return None
        lookups += 1
        query = ', '.join(reversed(_path(place)))
        options = {'language': language} if language else {}
        if place['granularity'] == 'landmark':
            options['landmark'] = True
        try:
            return search_place_details(query, **options)
        except (GeocodingUnavailable, httpx.HTTPError, ValueError, TypeError):
            provider_available = False
            return None

    for index, place in enumerate(places):
        path = [_label(label) for label in _path(place)]
        ancestors = [city for city in cities if len(_path(city)) <= len(path)
                     and [_label(label) for label in _path(city)] == path[:len(_path(city))]]
        # The containing city owns the view, even if a child was labelled city.
        city = deepcopy(min(ancestors, key=lambda item: len(_path(item)))) if ancestors else None
        canonical_city_key = _key(city) if city else None
        own_coordinates = _coordinates(place)
        same_as_parent = bool(city and _key(city) != _key(place) and own_coordinates
                              and place.get('latitude') == city.get('latitude')
                              and place.get('longitude') == city.get('longitude'))
        pin = {**deepcopy(place), 'accuracy': 'approximate'} if own_coordinates and not same_as_parent else None
        details = lookup(place) if not city or not pin or language else None
        if details:
            if resolved_city := _provider_city(details):
                if city and _coordinates(city):
                    resolved_city['latitude'], resolved_city['longitude'] = city['latitude'], city['longitude']
                if language or city is None or _key(city) != _key(resolved_city):
                    city = resolved_city
            if language and own_coordinates:
                pass  # Translating labels must retain an already known source pin.
            elif not details.get('partial_match'):
                pin = {**deepcopy(place), 'latitude': details['latitude'], 'longitude': details['longitude'],
                       'accuracy': 'public-map', 'attribution': details.get('attribution', 'Public map')}
            else:
                pin = None
        city = city or deepcopy(place)
        # A provider can return only the city centre despite matching the query.
        # It remains a usable map target, never an independent child's position.
        city_identity = canonical_city_key if canonical_city_key is not None else _key(city)
        place_key = _key(place)
        if (pin and city_identity != place_key
                and pin['latitude'] == city.get('latitude')
                and pin['longitude'] == city.get('longitude')):
            pin = None
        if (pin and city_identity == place_key and city['granularity'] == 'city'
                and _label(city['place']) == _label(place['place']) and not _coordinates(city)):
            city.update(latitude=pin['latitude'], longitude=pin['longitude'])
        records.append({'index': index, 'city_key': _key(city), 'city': city, 'pin': pin,
                        'pin_status': 'READY' if pin else 'UNRESOLVED'})
    # Spend remaining lookups on city centres after resolving individual pins.
    for record, place in zip(records, places):
        city = record['city']
        if (record['pin'] is not None or record['city_key'] == _key(place)
                or city['granularity'] != 'city' or _coordinates(city)):
            continue
        centre = lookup(city)
        match = _provider_city(centre)
        if match and _key(match) == record['city_key'] and not centre.get('partial_match') and _coordinates(centre):
            city.update(latitude=centre['latitude'], longitude=centre['longitude'])
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
    return {'schema_version': 1, 'places': records,
            'status': 'READY' if all(record['pin'] for record in records) else 'PARTIAL'}
