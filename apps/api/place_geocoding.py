"""Resolve public place centres; parents never overwrite the named place."""
from __future__ import annotations

from functools import lru_cache
import math
import os
from threading import Lock

import httpx
from .place_identity import geographic_label, place_path

_lock = Lock()
GOOGLE_GEOCODING_URL = "https://maps.googleapis.com/maps/api/geocode/json"
GEOAPIFY_GEOCODING_URL = "https://api.geoapify.com/v1/geocode/search"
GEOAPIFY_MIN_CONFIDENCE = 0.95
GEOAPIFY_RESULT_FIELDS = {
    'country': ('country', 'country_code'), 'state': ('state', 'state_code', 'region'),
    'county': ('county',), 'city': ('city', 'municipality', 'town', 'village'),
    'district': ('district',), 'suburb': ('suburb',), 'locality': ('locality',),
}


class GeocodingUnavailable(RuntimeError):
    """The selected geocoding provider is unavailable or not configured."""


def geo_provider() -> str:
    return os.environ.get("MEMOIR_GEO_PROVIDER", "google").strip().lower() or "google"


def _geoapify_trusted_fields(record: dict, rank: dict):
    confidences = [rank.get('confidence')]
    if record.get('city') and 'confidence_city_level' in rank:
        confidences.append(rank['confidence_city_level'])
    for confidence in confidences:
        if (not isinstance(confidence, (int, float)) or isinstance(confidence, bool)
                or not math.isfinite(confidence) or not GEOAPIFY_MIN_CONFIDENCE <= confidence <= 1):
            return None
    return GEOAPIFY_RESULT_FIELDS.get(record.get('result_type'))


def _geoapify_matches_query(record: dict, rank: dict, query: str) -> bool:
    target_fields = _geoapify_trusted_fields(record, rank)
    labels = [geographic_label(label) for label in query.split(',') if label.strip()]
    if not target_fields or not labels:
        return False
    if len(labels) > 1 and labels[-1] not in {
            geographic_label(record.get('country', '')), geographic_label(record.get('country_code', ''))}:
        return False
    targets = {geographic_label(record.get(field, '')) for field in target_fields}
    # A qualified source label may omit 镇; its containing city must still match.
    containing_city = {geographic_label(record[field]) for field in ('city', 'municipality') if record.get(field)}
    if containing_city.intersection(labels[1:-1]) and record.get('result_type') == 'suburb':
        targets.update(label[:-1] for label in list(targets) if label.endswith('镇'))
    if labels[0] not in targets:
        return False
    # Match every supplied parent, in order, so a same-name place cannot jump regions.
    parents = iter(geographic_label(record.get(field, ''))
                   for fields in GEOAPIFY_RESULT_FIELDS.values() for field in fields)
    return all(any(parent == label for parent in parents) for label in reversed(labels[1:]))


@lru_cache(maxsize=1024)
def _geocode_record(provider: str, query: str, language: str | None = None):
    if provider == "google":
        api_key = os.environ.get("GOOGLE_MAPS_GEOCODING_API_KEY", "").strip()
        url = os.environ.get("GOOGLE_MAPS_GEOCODING_URL", GOOGLE_GEOCODING_URL)
        params = {"address": query, "key": api_key}
        if language:
            params['language'] = 'zh-CN' if language == 'zh-CN' else 'en'
    elif provider == "geoapify":
        api_key = os.environ.get("GEOAPIFY_API_KEY", "").strip()
        url = os.environ.get("GEOAPIFY_GEOCODING_URL", GEOAPIFY_GEOCODING_URL)
        params = {"text": query, "format": "json", "limit": 1, "apiKey": api_key,
                  "bias": "countrycode:none"}
        if language:
            params['lang'] = 'zh' if language == 'zh-CN' else 'en'
    else:
        raise GeocodingUnavailable("MEMOIR_GEO_PROVIDER must be google or geoapify")
    if not api_key:
        raise GeocodingUnavailable(f"{provider} geocoding API key is not configured")

    # Cache by provider as well as query so a flag change cannot reuse the other provider.
    # Geocoding credentials stay server-side; the browser gets a separate tile key.
    with _lock:
        response = httpx.get(
            url, params=params, headers={"Accept": "application/json"}, timeout=5,
        )
        response.raise_for_status()
        body = response.json()
    if not isinstance(body, dict):
        raise ValueError("Geocoding returned an invalid response")
    if provider == "google":
        provider_status = body.get("status")
        if provider_status == "ZERO_RESULTS":
            return None
        if provider_status != "OK":
            raise GeocodingUnavailable(f"Google Geocoding returned {provider_status or 'no status'}")
    results = body.get("results")
    if not isinstance(results, list) or not results or not isinstance(results[0], dict):
        return None
    record = results[0]
    try:
        location = record["geometry"]["location"] if provider == "google" else record
        lat, lon = location["lat"], location["lng" if provider == "google" else "lon"]
        if isinstance(lat, bool) or isinstance(lon, bool):
            return None
        latitude, longitude = float(lat), float(lon)
        if not (math.isfinite(latitude) and math.isfinite(longitude) and -90 <= latitude <= 90 and -180 <= longitude <= 180):
            return None
    except (KeyError, TypeError, ValueError):
        return None
    if provider == "google":
        components = {kind: part.get('long_name', '') for part in record.get('address_components', [])
                      for kind in part.get('types', [])}
        city = components.get('locality', '')
        prefecture = components.get('administrative_area_level_2', '')
        if prefecture.endswith('市'):
            city = prefecture
        region, country = components.get('administrative_area_level_1', ''), components.get('country', '')
        partial_match = bool(record.get('partial_match'))
        attribution = 'Google Maps'
    else:
        city = (record.get('city') or record.get('municipality') or record.get('town')
                or record.get('village') or record.get('locality') or '')
        region, country = record.get('state') or record.get('region') or '', record.get('country') or ''
        rank = record.get('rank') or {}
        if not isinstance(rank, dict):
            raise ValueError("Geoapify geocoding returned invalid match metadata")
        place_id = record.get('place_id')
        identity = (place_id, record.get('result_type')) if isinstance(place_id, str) and place_id.strip() else None
        partial_match = rank.get('match_type') != 'full_match'
        if not _geoapify_matches_query(record, rank, query):
            # Translate only the same provider feature; nearby places can have different levels and identities.
            if not language or not _geoapify_trusted_fields(record, rank):
                return None
            canonical = _geocode_record(provider, query, None)
            if not identity or not canonical or canonical.get('_geoapify_identity') != identity:
                return None
            latitude, longitude = canonical['latitude'], canonical['longitude']
            partial_match = partial_match or canonical['partial_match']
        attribution = 'Geoapify / OpenStreetMap'
    details = {'latitude': latitude, 'longitude': longitude, 'city': city, 'region': region,
               'country': country, 'partial_match': partial_match, 'attribution': attribution}
    if provider == 'geoapify':
        details['_geoapify_identity'] = identity
    return details


def search_place(query: str):
    provider = geo_provider()
    record = _geocode_record(provider, query, None)
    if record and provider == 'geoapify' and record['partial_match']:
        return None
    return {'latitude': record['latitude'], 'longitude': record['longitude'],
            'attribution': record['attribution']} if record else None


search_place.cache_clear = _geocode_record.cache_clear


def search_place_details(query: str, *, language: str | None = None):
    """Public administrative membership; partial results are not precise pins."""
    record = _geocode_record(geo_provider(), query, language)
    if not record:
        return None
    details = dict(record)
    details.pop('_geoapify_identity', None)
    return details


def resolve_place_map(journey: dict, saved_places: list) -> dict:
    labels = place_path(journey)
    unavailable = False
    for end in range(len(labels), 0, -1):
        target_path = labels[:end]
        target_identity = tuple(map(geographic_label, target_path))
        name = target_path[-1]
        candidates = ([journey] if end == len(labels) else []) + saved_places
        for candidate in candidates:
            candidate_path = place_path(candidate, normalized=True)
            lat, lon = candidate.get("latitude"), candidate.get("longitude")
            if candidate_path == target_identity and all(isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) for value in (lat, lon)) and -90 <= lat <= 90 and -180 <= lon <= 180:
                return {"status": "READY", "target": {"place": name, "latitude": lat, "longitude": lon}, "fallback": end < len(labels)}
        if unavailable:
            continue
        try:
            coordinates = search_place(", ".join(reversed(target_path)))
        except (GeocodingUnavailable, httpx.HTTPError, ValueError, TypeError):
            unavailable = True
            continue
        if coordinates:
            return {"status": "READY", "target": {"place": name, **coordinates}, "fallback": end < len(labels)}
    return {"status": "UNAVAILABLE" if unavailable else "NO_MATCH", "target": None, "fallback": False}
