"""Resolve public place centres; parent targets never overwrite the named place."""
from __future__ import annotations

from functools import lru_cache
import math
import os
from threading import Lock
import time

import httpx

_lock = Lock()
_last_request = 0.0


@lru_cache(maxsize=1024)
def search_place(query: str):
    global _last_request
    # Serialize and cache this low-volume provider boundary. Multi-worker deployments
    # should configure a shared geocoding proxy with application-wide rate limiting.
    with _lock:
        time.sleep(max(0, 1.1 - (time.monotonic() - _last_request)))
        _last_request = time.monotonic()
        response = httpx.get(
            os.environ.get("MEMOIR_GEOCODING_URL", "https://nominatim.openstreetmap.org/search"),
            params={"q": query, "format": "jsonv2", "limit": 1, "layer": "address"},
            headers={"User-Agent": "CopyMe2-Memoir/1.0 (place journey maps)"}, timeout=5,
        )
        response.raise_for_status()
        results = response.json()
    if not isinstance(results, list) or not results:
        return None
    try:
        latitude, longitude = float(results[0]["lat"]), float(results[0]["lon"])
        if not (math.isfinite(latitude) and math.isfinite(longitude) and -90 <= latitude <= 90 and -180 <= longitude <= 180):
            return None
    except (KeyError, TypeError, ValueError):
        return None
    return {"latitude": latitude, "longitude": longitude, "attribution": "© OpenStreetMap contributors"}


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
        except (httpx.HTTPError, ValueError, TypeError):
            unavailable = True
            continue
        if coordinates:
            return {"status": "READY", "target": {"place": name, **coordinates}, "fallback": end < len(labels)}
    return {"status": "UNAVAILABLE" if unavailable else "NO_MATCH", "target": None, "fallback": False}
