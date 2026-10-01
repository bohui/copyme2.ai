"""Resolve public place centres with Google Geocoding; parents never overwrite the named place."""
from __future__ import annotations

from functools import lru_cache
import math
import os
from threading import Lock

import httpx

_lock = Lock()
GOOGLE_GEOCODING_URL = "https://maps.googleapis.com/maps/api/geocode/json"


class GoogleMapsUnavailable(RuntimeError):
    """The Google provider is unavailable or not configured."""


@lru_cache(maxsize=1024)
def _geocode_record(query: str):
    api_key = os.environ.get("GOOGLE_MAPS_GEOCODING_API_KEY", "").strip()
    if not api_key:
        raise GoogleMapsUnavailable("Google Maps geocoding API key is not configured")

    # Serialize and cache this low-volume provider boundary. The key stays server-side;
    # the browser receives only its separately restricted Map Tiles key.
    with _lock:
        response = httpx.get(
            os.environ.get("GOOGLE_MAPS_GEOCODING_URL", GOOGLE_GEOCODING_URL),
            params={"address": query, "key": api_key},
            headers={"Accept": "application/json"}, timeout=5,
        )
        response.raise_for_status()
        body = response.json()
    if not isinstance(body, dict):
        raise ValueError("Google Geocoding returned an invalid response")
    provider_status = body.get("status")
    if provider_status == "ZERO_RESULTS":
        return None
    if provider_status != "OK":
        raise GoogleMapsUnavailable(f"Google Geocoding returned {provider_status or 'no status'}")
    results = body.get("results")
    if not isinstance(results, list) or not results or not isinstance(results[0], dict):
        return None
    try:
        location = results[0]["geometry"]["location"]
        latitude, longitude = float(location["lat"]), float(location["lng"])
        if not (math.isfinite(latitude) and math.isfinite(longitude) and -90 <= latitude <= 90 and -180 <= longitude <= 180):
            return None
    except (KeyError, TypeError, ValueError):
        return None
    return {**results[0], 'latitude': latitude, 'longitude': longitude}


def search_place(query: str):
    record = _geocode_record(query)
    return {'latitude': record['latitude'], 'longitude': record['longitude'],
            'attribution': 'Google Maps'} if record else None


search_place.cache_clear = _geocode_record.cache_clear


def search_place_details(query: str):
    """Public administrative membership; partial results are not precise pins."""
    record = _geocode_record(query)
    if not record:
        return None
    components = {kind: part.get('long_name', '') for part in record.get('address_components', [])
                  for kind in part.get('types', [])}
    city = components.get('locality', '')
    prefecture = components.get('administrative_area_level_2', '')
    if prefecture.endswith('市'):
        city = prefecture
    return {'latitude': record['latitude'], 'longitude': record['longitude'],
            'city': city, 'region': components.get('administrative_area_level_1', ''),
            'country': components.get('country', ''),
            'partial_match': bool(record.get('partial_match')), 'attribution': 'Google Maps'}


def resolve_place_map(journey: dict, saved_places: list) -> dict:
    labels = [label for label in journey["hierarchy"] if label.casefold() != "earth"]
    if not labels or labels[-1] != journey["place"]:
        labels.append(journey["place"])
    unavailable = False
    for end in range(len(labels), 0, -1):
        target_path = labels[:end]
        name = target_path[-1]
        candidates = ([journey] if end == len(labels) else []) + saved_places
        for candidate in candidates:
            candidate_path = [label for label in candidate.get("hierarchy", []) if label.casefold() != "earth"]
            if not candidate_path or candidate_path[-1] != candidate.get("place"):
                candidate_path.append(candidate.get("place"))
            lat, lon = candidate.get("latitude"), candidate.get("longitude")
            if candidate_path == target_path and all(isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) for value in (lat, lon)) and -90 <= lat <= 90 and -180 <= lon <= 180:
                return {"status": "READY", "target": {"place": name, "latitude": lat, "longitude": lon}, "fallback": end < len(labels)}
        if unavailable:
            continue
        try:
            coordinates = search_place(", ".join(reversed(target_path)))
        except (GoogleMapsUnavailable, httpx.HTTPError, ValueError, TypeError):
            unavailable = True
            continue
        if coordinates:
            return {"status": "READY", "target": {"place": name, **coordinates}, "fallback": end < len(labels)}
    return {"status": "UNAVAILABLE" if unavailable else "NO_MATCH", "target": None, "fallback": False}
